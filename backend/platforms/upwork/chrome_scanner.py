"""Chrome MCP-based scanner for Upwork contract listings.

This module implements the MCP *host* pattern:
  1. Connect to a Chrome MCP server (via the ``mcp`` Python SDK).
  2. Discover the Chrome tools exposed by the server.
  3. Mirror those tool schemas as Anthropic API tool definitions.
  4. Run an agent loop: Claude API -> tool_use -> execute via MCP -> return result -> repeat.
  5. Parse Claude's structured JSON output into ``ContractCreate`` models.
  6. Call ``on_contract()`` for incremental persistence.

For V1 the MCP client is injected as a dependency so we can mock it in tests;
the real Chrome MCP connection can be swapped in later.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable, Protocol, runtime_checkable
from urllib.parse import urlencode

from backend.core.models import ContractCreate
from backend.platforms.upwork.mcp_utils import get_anthropic_tools

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocols for injectable dependencies
# ---------------------------------------------------------------------------


@runtime_checkable
class MCPClient(Protocol):
    """Minimal interface expected from an MCP client connection."""

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return the list of tool definitions exposed by the MCP server."""
        ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Execute a tool on the MCP server and return its result."""
        ...


@runtime_checkable
class AnthropicClient(Protocol):
    """Minimal interface expected from an Anthropic API client."""

    class _Messages(Protocol):
        async def create(self, **kwargs: Any) -> Any: ...

    @property
    def messages(self) -> _Messages: ...


# ---------------------------------------------------------------------------
# System prompt for the scanner agent
# ---------------------------------------------------------------------------

SCANNER_SYSTEM_PROMPT = """\
You are an Upwork contract scanner.  Your job is to navigate Upwork search
result pages in Chrome, read each listing, and extract structured data.

## Instructions
1. Navigate to the provided search URL.
2. Read the search results page.
3. For each contract on the page, click into the detail view.
   - Wait 3-5 seconds between navigations to avoid rate limiting.
4. Extract the following fields from each contract:
   - title
   - description (full text)
   - external_id (the Upwork job ID from the URL, e.g. "~01abc123")
   - url (full URL)
   - budget_min / budget_max (if listed)
   - contract_type ("hourly" or "fixed")
   - duration (e.g. "1 to 3 months")
   - skills_required (list of skill tags)
   - proposals_count (number of proposals)
   - client_hire_rate (percentage, if shown)
   - client_total_spent (dollar amount, if shown)
   - client_location (country/city)
   - client_questions (list of screening questions, if any)
   - posted_at (when the job was posted)
   - connects_cost (number of connects required)
5. Return EACH contract as a JSON object on its own line, wrapped in
   <contract>...</contract> tags so they can be parsed incrementally.
6. After processing all results, output <done/> to signal completion.

## Error handling
- If you encounter a CAPTCHA, output <captcha/> and stop immediately.
- If a contract page fails to load, skip it and continue to the next.
- If an element is missing, use null for that field.

## Output format
<contract>{"title": "...", "external_id": "~01abc", ...}</contract>
<contract>{"title": "...", "external_id": "~02def", ...}</contract>
<done/>
"""


# ---------------------------------------------------------------------------
# ChromeScanner
# ---------------------------------------------------------------------------


class ChromeScanner:
    """Orchestrates an Anthropic-powered agent loop that uses Chrome MCP
    tools to scan Upwork for contracts.

    Parameters
    ----------
    mcp_client:
        An MCP client connected to the Chrome MCP server.
    anthropic_client:
        An ``anthropic.AsyncAnthropic``-compatible client.
    model:
        Which Claude model to use for the agent loop.
    max_agent_turns:
        Safety limit on the number of agent loop iterations.
    """

    def __init__(
        self,
        mcp_client: MCPClient,
        anthropic_client: AnthropicClient,
        *,
        model: str = "claude-sonnet-4-6",
        max_agent_turns: int = 100,
    ) -> None:
        self.mcp_client = mcp_client
        self.anthropic_client = anthropic_client
        self.model = model
        self.max_agent_turns = max_agent_turns

    # -- public API ---------------------------------------------------------

    async def scan(
        self,
        search_config: dict,
        on_contract: Callable[[ContractCreate], None],
    ) -> int:
        """Run the scanner agent loop for every search URL in *search_config*.

        Returns the total number of contracts found across all searches.
        """
        searches: list[dict] = search_config.get("searches", [])
        if not searches:
            searches = [search_config]

        total_found = 0
        for search in searches:
            count = await self._scan_single(search, on_contract)
            total_found += count
        return total_found

    # -- internals ----------------------------------------------------------

    async def _scan_single(
        self,
        search: dict,
        on_contract: Callable[[ContractCreate], None],
    ) -> int:
        """Run one agent conversation for a single search configuration."""
        tools = await self._get_anthropic_tools()
        search_url = self._build_search_url(search)

        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": (
                    f"Please scan the Upwork search results at this URL: {search_url}\n"
                    f"Extract every contract listing you find."
                ),
            },
        ]

        contracts_found = 0
        for _turn in range(self.max_agent_turns):
            response = await self._call_anthropic(messages, tools)

            # Context window exceeded — stop this search gracefully
            if response is None:
                break

            # Collect assistant content blocks
            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})

            # Check for tool use blocks
            tool_use_blocks = [b for b in assistant_content if getattr(b, "type", None) == "tool_use"]

            if not tool_use_blocks:
                # No tool calls -- parse text for contracts and finish
                text = self._extract_text(assistant_content)
                found = self._parse_contracts_from_text(text, on_contract)
                contracts_found += found
                break

            # Execute tool calls and build tool_result messages
            tool_results: list[dict[str, Any]] = []
            for block in tool_use_blocks:
                result = await self._execute_tool_call(block.name, block.input)

                # Check for CAPTCHA in result text
                result_text = str(result)
                if "<captcha/>" in result_text.lower() or "captcha" in result_text.lower():
                    logger.warning("CAPTCHA detected — stopping scan.")
                    return contracts_found

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    }
                )

            messages.append({"role": "user", "content": tool_results})

            # Parse any intermediate text for contracts
            text = self._extract_text(assistant_content)
            found = self._parse_contracts_from_text(text, on_contract)
            contracts_found += found

        return contracts_found

    async def _get_anthropic_tools(self) -> list[dict[str, Any]]:
        """Discover MCP tools and convert them to Anthropic tool definitions."""
        return await get_anthropic_tools(self.mcp_client)

    async def _call_anthropic(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        """Make a single Anthropic API call with retry on 429."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return await self.anthropic_client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=SCANNER_SYSTEM_PROMPT,
                    messages=messages,
                    tools=tools,
                )
            except Exception as exc:
                # Context window exceeded — caller should split into a new conversation
                status = getattr(exc, "status_code", None)
                if status == 400:
                    exc_str = str(exc).lower()
                    if "context" in exc_str or "token" in exc_str:
                        logger.warning("Context window exceeded, stopping this search")
                        return None
                # Detect rate-limit (429) errors for exponential backoff
                if status == 429 and attempt < max_retries - 1:
                    wait = 2 ** (attempt + 1)
                    logger.warning("Anthropic 429 — backing off %ds", wait)
                    await asyncio.sleep(wait)
                    continue
                raise

    async def _execute_tool_call(self, name: str, arguments: dict[str, Any]) -> Any:
        """Forward a tool call to the MCP client."""
        try:
            return await self.mcp_client.call_tool(name, arguments)
        except Exception:
            logger.exception("MCP tool call failed: %s", name)
            return f"Error: tool '{name}' failed"

    # -- parsing helpers ----------------------------------------------------

    @staticmethod
    def _extract_text(content_blocks: list[Any]) -> str:
        """Pull plain-text segments out of Anthropic content blocks."""
        parts: list[str] = []
        for block in content_blocks:
            if getattr(block, "type", None) == "text":
                parts.append(block.text)
        return "\n".join(parts)

    @staticmethod
    def _parse_contract_from_json(data: dict[str, Any]) -> ContractCreate:
        """Convert a raw JSON dict into a ``ContractCreate`` model."""
        return ContractCreate(
            platform="upwork",
            external_id=data.get("external_id", ""),
            url=data.get("url"),
            title=data.get("title"),
            description=data.get("description"),
            skills_required=data.get("skills_required"),
            budget_min=data.get("budget_min"),
            budget_max=data.get("budget_max"),
            contract_type=data.get("contract_type"),
            duration=data.get("duration"),
            proposals_count=data.get("proposals_count"),
            client_hire_rate=data.get("client_hire_rate"),
            client_total_spent=data.get("client_total_spent"),
            client_location=data.get("client_location"),
            connects_cost=data.get("connects_cost"),
            client_questions=data.get("client_questions"),
            posted_at=data.get("posted_at"),
            fetched_at=datetime.now(timezone.utc),
        )

    @classmethod
    def _parse_contracts_from_text(
        cls,
        text: str,
        on_contract: Callable[[ContractCreate], None],
    ) -> int:
        """Extract ``<contract>...</contract>`` JSON blocks from agent text output.

        Calls *on_contract* for each successfully parsed contract.
        Returns the number of contracts parsed.
        """
        count = 0
        for match in re.finditer(r"<contract>(.*?)</contract>", text, re.DOTALL):
            raw = match.group(1).strip()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Failed to parse contract JSON: %.200s", raw)
                continue

            if not data.get("external_id"):
                logger.warning("Contract JSON missing external_id — skipping")
                continue

            try:
                contract = cls._parse_contract_from_json(data)
                on_contract(contract)
                count += 1
            except Exception:
                logger.exception("Failed to create ContractCreate from JSON")
        return count

    @staticmethod
    def _build_search_url(search: dict) -> str:
        """Build an Upwork search URL from a search config dict."""
        if "url" in search:
            return search["url"]

        base = "https://www.upwork.com/nx/search/jobs/"
        params: dict[str, str] = {}

        query = search.get("query", "")
        if query:
            params["q"] = query

        category = search.get("category", "")
        if category:
            params["category2_uid"] = category

        filters = search.get("filters", {})
        params.update(filters)

        return base + ("?" + urlencode(params) if params else "")
