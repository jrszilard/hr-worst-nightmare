"""Tests for ChromeScanner and ChromeSubmitter.

Both the MCP client and the Anthropic API client are fully mocked so no
external services are needed.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from backend.core.models import ContractCreate
from backend.platforms.upwork.chrome_scanner import ChromeScanner, SCANNER_SYSTEM_PROMPT
from backend.platforms.upwork.chrome_submit import ChromeSubmitter, SUBMIT_SYSTEM_PROMPT


# ── Helpers ───────────────────────────────────────────────────────────────


def _text_block(text: str) -> SimpleNamespace:
    """Create a mock Anthropic text content block."""
    return SimpleNamespace(type="text", text=text)


def _tool_use_block(tool_id: str, name: str, input_data: dict) -> SimpleNamespace:
    """Create a mock Anthropic tool_use content block."""
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=input_data)


def _make_mcp_client(tools: list[dict] | None = None) -> AsyncMock:
    """Create a mock MCP client."""
    client = AsyncMock()
    client.list_tools = AsyncMock(return_value=tools or [
        {
            "name": "navigate",
            "description": "Navigate to URL",
            "input_schema": {"type": "object", "properties": {"url": {"type": "string"}}},
        },
        {
            "name": "read_page",
            "description": "Read page content",
            "input_schema": {"type": "object"},
        },
    ])
    client.call_tool = AsyncMock(return_value="Page content loaded.")
    return client


def _make_anthropic_client(responses: list) -> AsyncMock:
    """Create a mock Anthropic client that returns *responses* in order.

    Each element in *responses* should be a list of content blocks.
    """
    client = AsyncMock()
    mock_messages = AsyncMock()

    # Convert lists of blocks into SimpleNamespace response objects
    response_objects = [SimpleNamespace(content=blocks) for blocks in responses]
    mock_messages.create = AsyncMock(side_effect=response_objects)

    client.messages = mock_messages
    return client


# ── Contract JSON helpers ─────────────────────────────────────────────────


SAMPLE_CONTRACT_JSON = {
    "title": "Build a REST API",
    "external_id": "~01abc123",
    "url": "https://www.upwork.com/jobs/~01abc123",
    "description": "We need a Python developer to build a REST API.",
    "budget_min": 1000,
    "budget_max": 2000,
    "contract_type": "fixed",
    "duration": "1 to 3 months",
    "skills_required": ["Python", "FastAPI"],
    "proposals_count": 10,
    "client_hire_rate": 85.0,
    "client_total_spent": 50000.0,
    "client_location": "United States",
    "connects_cost": 12,
    "client_questions": ["What is your experience with FastAPI?"],
    "posted_at": None,
}

SAMPLE_CONTRACT_JSON_2 = {
    "title": "React Dashboard",
    "external_id": "~02def456",
    "url": "https://www.upwork.com/jobs/~02def456",
    "description": "Build a dashboard with React.",
    "budget_min": None,
    "budget_max": None,
    "contract_type": "hourly",
    "duration": "3 to 6 months",
    "skills_required": ["React", "TypeScript"],
    "proposals_count": 5,
    "client_hire_rate": 70.0,
    "client_total_spent": 20000.0,
    "client_location": "Germany",
    "connects_cost": 6,
    "client_questions": [],
    "posted_at": None,
}


# ══════════════════════════════════════════════════════════════════════════
# ChromeScanner tests
# ══════════════════════════════════════════════════════════════════════════


class TestChromeScanner:
    """Tests for the ChromeScanner agent loop."""

    # -- Tool discovery -----------------------------------------------------

    async def test_get_anthropic_tools_mirrors_mcp_tools(self):
        """_get_anthropic_tools converts MCP tool schemas to Anthropic format."""
        mcp = _make_mcp_client()
        anthropic = _make_anthropic_client([[_text_block("<done/>")]])
        scanner = ChromeScanner(mcp, anthropic)

        tools = await scanner._get_anthropic_tools()

        assert len(tools) == 2
        assert tools[0]["name"] == "navigate"
        assert tools[1]["name"] == "read_page"
        assert "input_schema" in tools[0]

    # -- Text parsing -------------------------------------------------------

    async def test_parse_single_contract_from_text(self):
        """Contracts wrapped in <contract>...</contract> tags are parsed."""
        text = f"<contract>{json.dumps(SAMPLE_CONTRACT_JSON)}</contract>\n<done/>"
        callback = MagicMock()

        count = ChromeScanner._parse_contracts_from_text(text, callback)

        assert count == 1
        callback.assert_called_once()
        contract = callback.call_args[0][0]
        assert isinstance(contract, ContractCreate)
        assert contract.title == "Build a REST API"
        assert contract.external_id == "~01abc123"
        assert contract.platform == "upwork"
        assert contract.budget_min == 1000
        assert contract.budget_max == 2000
        assert contract.skills_required == ["Python", "FastAPI"]

    async def test_parse_multiple_contracts_from_text(self):
        """Multiple <contract> tags each produce a callback."""
        text = (
            f"<contract>{json.dumps(SAMPLE_CONTRACT_JSON)}</contract>\n"
            f"<contract>{json.dumps(SAMPLE_CONTRACT_JSON_2)}</contract>\n"
            f"<done/>"
        )
        callback = MagicMock()

        count = ChromeScanner._parse_contracts_from_text(text, callback)

        assert count == 2
        assert callback.call_count == 2
        titles = {callback.call_args_list[i][0][0].title for i in range(2)}
        assert titles == {"Build a REST API", "React Dashboard"}

    async def test_parse_skips_invalid_json(self):
        """Malformed JSON inside <contract> tags is skipped, not raised."""
        text = (
            "<contract>{not valid json}</contract>\n"
            f"<contract>{json.dumps(SAMPLE_CONTRACT_JSON)}</contract>\n"
        )
        callback = MagicMock()

        count = ChromeScanner._parse_contracts_from_text(text, callback)

        assert count == 1
        callback.assert_called_once()

    async def test_parse_skips_missing_external_id(self):
        """Contracts without external_id are skipped."""
        bad = {"title": "No ID Contract"}
        text = f"<contract>{json.dumps(bad)}</contract>\n"
        callback = MagicMock()

        count = ChromeScanner._parse_contracts_from_text(text, callback)

        assert count == 0
        callback.assert_not_called()

    async def test_parse_no_contract_tags(self):
        """Text with no <contract> tags returns 0."""
        callback = MagicMock()
        count = ChromeScanner._parse_contracts_from_text("No contracts here.", callback)
        assert count == 0
        callback.assert_not_called()

    # -- Agent loop: text-only response (no tool use) -----------------------

    async def test_scan_text_only_response(self):
        """When Claude returns text with contracts and no tool calls, they are parsed."""
        contract_text = (
            f"<contract>{json.dumps(SAMPLE_CONTRACT_JSON)}</contract>\n"
            f"<contract>{json.dumps(SAMPLE_CONTRACT_JSON_2)}</contract>\n"
            "<done/>"
        )

        mcp = _make_mcp_client()
        anthropic = _make_anthropic_client([[_text_block(contract_text)]])
        scanner = ChromeScanner(mcp, anthropic)

        callback = MagicMock()
        total = await scanner.scan({"query": "python", "category": "web-dev"}, callback)

        assert total == 2
        assert callback.call_count == 2

    # -- Agent loop: tool use then text response ----------------------------

    async def test_scan_tool_use_then_text(self):
        """Agent loop: Claude calls a tool, then returns text with contracts."""
        # Turn 1: Claude wants to navigate
        turn1 = [
            _tool_use_block("call_1", "navigate", {"url": "https://upwork.com/search"}),
        ]
        # Turn 2: After tool result, Claude returns contracts
        contract_text = f"<contract>{json.dumps(SAMPLE_CONTRACT_JSON)}</contract>\n<done/>"
        turn2 = [_text_block(contract_text)]

        mcp = _make_mcp_client()
        anthropic = _make_anthropic_client([turn1, turn2])
        scanner = ChromeScanner(mcp, anthropic)

        callback = MagicMock()
        total = await scanner.scan({"query": "python"}, callback)

        assert total == 1
        assert callback.call_count == 1
        mcp.call_tool.assert_awaited_once_with("navigate", {"url": "https://upwork.com/search"})

    async def test_scan_multiple_tool_calls(self):
        """Agent calls multiple tools in one turn, then returns contracts."""
        turn1 = [
            _tool_use_block("call_1", "navigate", {"url": "https://upwork.com"}),
            _tool_use_block("call_2", "read_page", {}),
        ]
        contract_text = f"<contract>{json.dumps(SAMPLE_CONTRACT_JSON)}</contract>\n<done/>"
        turn2 = [_text_block(contract_text)]

        mcp = _make_mcp_client()
        anthropic = _make_anthropic_client([turn1, turn2])
        scanner = ChromeScanner(mcp, anthropic)

        callback = MagicMock()
        total = await scanner.scan({"query": "python"}, callback)

        assert total == 1
        assert mcp.call_tool.await_count == 2

    # -- CAPTCHA detection --------------------------------------------------

    async def test_scan_stops_on_captcha_in_tool_result(self):
        """If an MCP tool returns text mentioning 'captcha', scanning stops."""
        turn1 = [
            _tool_use_block("call_1", "navigate", {"url": "https://upwork.com"}),
        ]
        mcp = _make_mcp_client()
        mcp.call_tool = AsyncMock(return_value="CAPTCHA detected on page")

        # The second response should never be reached
        anthropic = _make_anthropic_client([turn1, [_text_block("<done/>")]])
        scanner = ChromeScanner(mcp, anthropic)

        callback = MagicMock()
        total = await scanner.scan({"query": "python"}, callback)

        assert total == 0
        callback.assert_not_called()

    # -- Multiple searches --------------------------------------------------

    async def test_scan_multiple_searches(self):
        """When search_config has a 'searches' list, each search runs separately."""
        contract_text_1 = f"<contract>{json.dumps(SAMPLE_CONTRACT_JSON)}</contract>\n<done/>"
        contract_text_2 = f"<contract>{json.dumps(SAMPLE_CONTRACT_JSON_2)}</contract>\n<done/>"

        mcp = _make_mcp_client()
        anthropic = _make_anthropic_client([
            [_text_block(contract_text_1)],
            [_text_block(contract_text_2)],
        ])
        scanner = ChromeScanner(mcp, anthropic)

        callback = MagicMock()
        total = await scanner.scan(
            {"searches": [{"query": "python"}, {"query": "react"}]},
            callback,
        )

        assert total == 2
        assert callback.call_count == 2

    # -- MCP tool call error handling ----------------------------------------

    async def test_tool_call_error_returns_error_string(self):
        """When an MCP tool call raises, the error is returned as a string."""
        turn1 = [_tool_use_block("call_1", "navigate", {"url": "x"})]
        contract_text = f"<contract>{json.dumps(SAMPLE_CONTRACT_JSON)}</contract>\n<done/>"
        turn2 = [_text_block(contract_text)]

        mcp = _make_mcp_client()
        mcp.call_tool = AsyncMock(side_effect=RuntimeError("connection lost"))
        anthropic = _make_anthropic_client([turn1, turn2])
        scanner = ChromeScanner(mcp, anthropic)

        callback = MagicMock()
        # Should not raise — error is caught and returned as a tool result
        total = await scanner.scan({"query": "python"}, callback)

        assert total == 1

    # -- Search URL building ------------------------------------------------

    def test_build_search_url_from_query(self):
        """_build_search_url produces correct Upwork URL from query + category."""
        url = ChromeScanner._build_search_url({"query": "python", "category": "531770282580668418"})
        assert "q=python" in url
        assert "category2_uid=531770282580668418" in url
        assert url.startswith("https://www.upwork.com/nx/search/jobs/")

    def test_build_search_url_passthrough(self):
        """If 'url' key is present, it's returned directly."""
        url = ChromeScanner._build_search_url({"url": "https://example.com/custom"})
        assert url == "https://example.com/custom"

    def test_build_search_url_with_filters(self):
        """Filters dict entries are appended as query params."""
        url = ChromeScanner._build_search_url({
            "query": "react",
            "category": "",
            "filters": {"payment_verified": "1", "sort": "recency"},
        })
        assert "payment_verified=1" in url
        assert "sort=recency" in url

    # -- Contract JSON -> ContractCreate ------------------------------------

    def test_parse_contract_from_json(self):
        """_parse_contract_from_json produces a valid ContractCreate."""
        contract = ChromeScanner._parse_contract_from_json(SAMPLE_CONTRACT_JSON)

        assert isinstance(contract, ContractCreate)
        assert contract.platform == "upwork"
        assert contract.external_id == "~01abc123"
        assert contract.title == "Build a REST API"
        assert contract.budget_min == 1000
        assert contract.contract_type == "fixed"
        assert contract.skills_required == ["Python", "FastAPI"]
        assert contract.fetched_at is not None

    def test_parse_contract_from_json_minimal(self):
        """Minimal JSON with just external_id still produces a ContractCreate."""
        contract = ChromeScanner._parse_contract_from_json({"external_id": "~0min"})

        assert contract.platform == "upwork"
        assert contract.external_id == "~0min"
        assert contract.title is None

    # -- System prompt is non-empty -----------------------------------------

    def test_scanner_system_prompt_not_empty(self):
        assert len(SCANNER_SYSTEM_PROMPT) > 100
        assert "Upwork" in SCANNER_SYSTEM_PROMPT
        assert "<contract>" in SCANNER_SYSTEM_PROMPT


# ══════════════════════════════════════════════════════════════════════════
# ChromeSubmitter tests
# ══════════════════════════════════════════════════════════════════════════


class TestChromeSubmitter:
    """Tests for the ChromeSubmitter form filler."""

    async def test_fill_success(self):
        """When the agent outputs <filled/>, fill() returns True."""
        mcp = _make_mcp_client()
        anthropic = _make_anthropic_client([[_text_block("All fields filled.\n<filled/>")]])
        submitter = ChromeSubmitter(mcp, anthropic)

        contract = SimpleNamespace(
            url="https://www.upwork.com/jobs/~01abc",
            external_id="~01abc",
        )
        proposal = SimpleNamespace(content="I am a great fit.", bid_amount=75, estimated_duration="1 month")

        result = await submitter.fill(contract, proposal)
        assert result is True

    async def test_fill_captcha(self):
        """When the agent outputs <captcha/>, fill() returns False."""
        mcp = _make_mcp_client()
        anthropic = _make_anthropic_client([[_text_block("<captcha/>")]])
        submitter = ChromeSubmitter(mcp, anthropic)

        contract = SimpleNamespace(url="https://www.upwork.com/jobs/~01abc", external_id="~01abc")
        proposal = SimpleNamespace(content="Hello", bid_amount=50, estimated_duration="1 month")

        result = await submitter.fill(contract, proposal)
        assert result is False

    async def test_fill_error(self):
        """When the agent outputs <error>...</error>, fill() returns False."""
        mcp = _make_mcp_client()
        anthropic = _make_anthropic_client([[_text_block("<error>Page not found</error>")]])
        submitter = ChromeSubmitter(mcp, anthropic)

        contract = SimpleNamespace(url="https://www.upwork.com/jobs/~01abc", external_id="~01abc")
        proposal = SimpleNamespace(content="Hello", bid_amount=50, estimated_duration="1 month")

        result = await submitter.fill(contract, proposal)
        assert result is False

    async def test_fill_with_tool_use(self):
        """Agent uses a tool to navigate, then reports <filled/>."""
        turn1 = [_tool_use_block("call_1", "navigate", {"url": "https://upwork.com"})]
        turn2 = [_text_block("Done filling.\n<filled/>")]

        mcp = _make_mcp_client()
        anthropic = _make_anthropic_client([turn1, turn2])
        submitter = ChromeSubmitter(mcp, anthropic)

        contract = SimpleNamespace(url="https://www.upwork.com/jobs/~01abc", external_id="~01abc")
        proposal = SimpleNamespace(content="Hello", bid_amount=50, estimated_duration="1 month")

        result = await submitter.fill(contract, proposal)
        assert result is True
        mcp.call_tool.assert_awaited_once()

    async def test_fill_exhausts_turns(self):
        """If max turns are reached without <filled/>, returns False."""
        mcp = _make_mcp_client()
        # Return text without <filled/> signal
        anthropic = _make_anthropic_client([[_text_block("Still thinking...")]])
        submitter = ChromeSubmitter(mcp, anthropic, max_agent_turns=1)

        contract = SimpleNamespace(url="https://www.upwork.com/jobs/~01abc", external_id="~01abc")
        proposal = SimpleNamespace(content="Hello", bid_amount=50, estimated_duration="1 month")

        result = await submitter.fill(contract, proposal)
        assert result is False

    async def test_fill_tool_error_handled(self):
        """If MCP tool call raises, error is caught and returned as result."""
        turn1 = [_tool_use_block("call_1", "form_input", {"selector": "#cover", "value": "Hi"})]
        turn2 = [_text_block("<filled/>")]

        mcp = _make_mcp_client()
        mcp.call_tool = AsyncMock(side_effect=RuntimeError("connection error"))
        anthropic = _make_anthropic_client([turn1, turn2])
        submitter = ChromeSubmitter(mcp, anthropic)

        contract = SimpleNamespace(url="https://www.upwork.com/jobs/~01abc", external_id="~01abc")
        proposal = SimpleNamespace(content="Hello", bid_amount=50, estimated_duration="1 month")

        result = await submitter.fill(contract, proposal)
        assert result is True

    def test_get_proposal_url_from_job_url(self):
        """_get_proposal_url converts /jobs/ URLs to /proposals/job/ URLs."""
        contract = SimpleNamespace(url="https://www.upwork.com/jobs/~01abc", external_id="~01abc")
        url = ChromeSubmitter._get_proposal_url(contract)
        assert url == "https://www.upwork.com/proposals/job/~01abc/apply/"

    def test_get_proposal_url_fallback_to_external_id(self):
        """When URL has no /jobs/, falls back to external_id."""
        contract = SimpleNamespace(url="", external_id="~01abc")
        url = ChromeSubmitter._get_proposal_url(contract)
        assert url == "https://www.upwork.com/proposals/job/~01abc/apply/"

    def test_submit_system_prompt_not_empty(self):
        assert len(SUBMIT_SYSTEM_PROMPT) > 50
        assert "Upwork" in SUBMIT_SYSTEM_PROMPT
        assert "submit" in SUBMIT_SYSTEM_PROMPT.lower()
