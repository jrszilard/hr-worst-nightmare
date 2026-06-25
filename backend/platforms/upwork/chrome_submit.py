"""Chrome MCP-based proposal form filler for Upwork.

Uses the same MCP host pattern as the scanner: an Anthropic agent loop
drives Chrome via MCP tools to read the proposal page and fill form fields.

**Human-in-the-loop:** the agent fills every field but does NOT click the
final submit button — the freelancer reviews and clicks it manually.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.platforms.upwork.chrome_scanner import AnthropicClient, MCPClient
from backend.platforms.upwork.mcp_utils import get_anthropic_tools

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System prompt for the form-filler agent
# ---------------------------------------------------------------------------

SUBMIT_SYSTEM_PROMPT = """\
You are an Upwork proposal form filler.  Your job is to navigate to the
proposal submission page in Chrome and fill out the form fields.

## Instructions
1. Navigate to the given proposal URL.
2. Wait for the page to fully load.
3. Read the form fields present on the page.
4. Fill in the following fields with the provided values:
   - Cover letter text area — paste the provided cover letter.
   - Bid amount — enter the provided bid amount.
   - Estimated duration — select the provided duration option.
   - Answer any client screening questions with the provided answers.
5. Do NOT click "Submit Proposal" — the human will review and submit.
6. After filling, output <filled/> to signal success.

## Error handling
- If a field cannot be found, output <field_missing>field_name</field_missing>.
- If the page shows a CAPTCHA, output <captcha/> and stop immediately.
- If the page fails to load, output <error>description</error>.
"""


# ---------------------------------------------------------------------------
# ChromeSubmitter
# ---------------------------------------------------------------------------


class ChromeSubmitter:
    """Fills the Upwork proposal form via an Anthropic agent + Chrome MCP tools.

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
        max_agent_turns: int = 30,
    ) -> None:
        self.mcp_client = mcp_client
        self.anthropic_client = anthropic_client
        self.model = model
        self.max_agent_turns = max_agent_turns

    # -- public API ---------------------------------------------------------

    async def fill(self, contract: Any, proposal: Any) -> bool:
        """Fill the Upwork proposal form for *contract* with *proposal* data.

        Returns ``True`` if the form was filled successfully (agent output
        ``<filled/>``), ``False`` otherwise.
        """
        tools = await self._get_anthropic_tools()
        proposal_url = self._get_proposal_url(contract)

        cover_letter = getattr(proposal, "content", "") or ""
        bid_amount = getattr(proposal, "bid_amount", None)
        duration = getattr(proposal, "estimated_duration", None)

        user_message = (
            f"Please fill the Upwork proposal form at: {proposal_url}\n\n"
            f"## Cover letter\n{cover_letter}\n\n"
            f"## Bid amount\n{bid_amount}\n\n"
            f"## Duration\n{duration}\n"
        )

        messages: list[dict[str, Any]] = [
            {"role": "user", "content": user_message},
        ]

        for _turn in range(self.max_agent_turns):
            response = await self.anthropic_client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=SUBMIT_SYSTEM_PROMPT,
                messages=messages,
                tools=tools,
            )

            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})

            tool_use_blocks = [b for b in assistant_content if getattr(b, "type", None) == "tool_use"]

            if not tool_use_blocks:
                text = self._extract_text(assistant_content)
                if "<filled/>" in text:
                    logger.info("Proposal form filled successfully.")
                    return True
                if "<captcha/>" in text:
                    logger.warning("CAPTCHA detected — cannot fill form.")
                    return False
                if "<error>" in text:
                    logger.warning("Error filling form: %s", text)
                    return False
                # No tool calls and no signal — might still be in progress;
                # but if we reached here the agent has finished without success.
                return False

            tool_results: list[dict[str, Any]] = []
            for block in tool_use_blocks:
                try:
                    result = await self.mcp_client.call_tool(block.name, block.input)
                    result_text = str(result)
                except Exception:
                    logger.exception("MCP tool call failed: %s", block.name)
                    result_text = f"Error: tool '{block.name}' failed"

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    }
                )

            messages.append({"role": "user", "content": tool_results})

        logger.warning("Agent exhausted max turns without filling the form.")
        return False

    # -- internals ----------------------------------------------------------

    async def _get_anthropic_tools(self) -> list[dict[str, Any]]:
        """Discover MCP tools and convert to Anthropic tool definitions."""
        return await get_anthropic_tools(self.mcp_client)

    @staticmethod
    def _extract_text(content_blocks: list[Any]) -> str:
        parts: list[str] = []
        for block in content_blocks:
            if getattr(block, "type", None) == "text":
                parts.append(block.text)
        return "\n".join(parts)

    @staticmethod
    def _get_proposal_url(contract: Any) -> str:
        """Derive the Upwork proposal submission URL from a contract."""
        url = getattr(contract, "url", None) or ""
        if "/jobs/" in url:
            return url.replace("/jobs/", "/proposals/job/") + "/apply/"
        external_id = getattr(contract, "external_id", "")
        return f"https://www.upwork.com/proposals/job/{external_id}/apply/"
