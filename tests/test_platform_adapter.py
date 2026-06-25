"""Tests for the PlatformAdapter ABC and UpworkAdapter."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.enums import SubmissionChannel
from backend.core.models import ContractCreate
from backend.core.platform import PlatformAdapter, SubmitResult
from backend.platforms.upwork.adapter import UpworkAdapter
from backend.platforms.upwork.chrome_scanner import ChromeScanner
from backend.platforms.upwork.chrome_submit import ChromeSubmitter


# ── PlatformAdapter is truly abstract ─────────────────────────────────────


def test_platform_adapter_cannot_be_instantiated():
    """PlatformAdapter is abstract and cannot be instantiated directly."""
    with pytest.raises(TypeError):
        PlatformAdapter()  # type: ignore[abstract]


def test_platform_adapter_requires_scan_contracts():
    """A subclass that omits scan_contracts raises TypeError."""

    class Incomplete(PlatformAdapter):
        async def submit_application(self, contract, application) -> SubmitResult:
            return SubmitResult(filled=True)

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


def test_platform_adapter_requires_submit_application():
    """A subclass that omits submit_application raises TypeError."""

    class Incomplete(PlatformAdapter):
        async def scan_contracts(self, search_config, on_contract) -> int:
            return 0

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


def test_complete_subclass_instantiates():
    """A fully implemented subclass can be instantiated."""

    class Complete(PlatformAdapter):
        async def scan_contracts(self, search_config, on_contract) -> int:
            return 0

        async def submit_application(self, contract, application) -> SubmitResult:
            return SubmitResult(filled=True)

    adapter = Complete()
    assert isinstance(adapter, PlatformAdapter)


# ── UpworkAdapter delegates correctly ─────────────────────────────────────


def _make_mock_scanner_and_submitter():
    """Create mock scanner and submitter for UpworkAdapter tests."""
    mcp_client = AsyncMock()
    mcp_client.list_tools = AsyncMock(return_value=[])
    mcp_client.call_tool = AsyncMock(return_value="ok")

    anthropic_client = AsyncMock()

    scanner = ChromeScanner(mcp_client, anthropic_client)
    submitter = ChromeSubmitter(mcp_client, anthropic_client)
    return scanner, submitter


def test_upwork_adapter_is_platform_adapter():
    """UpworkAdapter is a subclass of PlatformAdapter."""
    scanner, submitter = _make_mock_scanner_and_submitter()
    adapter = UpworkAdapter(scanner, submitter)
    assert isinstance(adapter, PlatformAdapter)


async def test_upwork_adapter_scan_delegates_to_scanner():
    """scan_contracts() delegates to ChromeScanner.scan()."""
    scanner, submitter = _make_mock_scanner_and_submitter()
    adapter = UpworkAdapter(scanner, submitter)

    # Patch scanner.scan to return a known value
    scanner.scan = AsyncMock(return_value=5)

    callback = MagicMock()
    result = await adapter.scan_contracts({"query": "python"}, callback)

    scanner.scan.assert_awaited_once_with({"query": "python"}, callback)
    assert result == 5


async def test_upwork_adapter_fill_delegates_to_submitter():
    """submit_application() delegates to ChromeSubmitter.fill()."""
    scanner, submitter = _make_mock_scanner_and_submitter()
    adapter = UpworkAdapter(scanner, submitter)

    submitter.fill = AsyncMock(return_value=True)

    contract = SimpleNamespace(url="https://upwork.com/jobs/~01abc")
    proposal = SimpleNamespace(content="Hello", bid_amount=50, estimated_duration="1 month")

    result = await adapter.submit_application(contract, proposal)

    submitter.fill.assert_awaited_once_with(contract, proposal)
    assert isinstance(result, SubmitResult)
    assert result.filled is True
    assert result.submitted is False


async def test_upwork_adapter_fill_returns_false_on_failure():
    """submit_application() wraps False fill result in SubmitResult."""
    scanner, submitter = _make_mock_scanner_and_submitter()
    adapter = UpworkAdapter(scanner, submitter)

    submitter.fill = AsyncMock(return_value=False)

    contract = SimpleNamespace(url="https://upwork.com/jobs/~01abc")
    proposal = SimpleNamespace(content="Hello", bid_amount=50, estimated_duration="1 month")

    result = await adapter.submit_application(contract, proposal)
    assert isinstance(result, SubmitResult)
    assert result.filled is False
    assert result.submitted is False


# ── New interface: submit_application + channel/artifact declarations ───────


def test_upwork_declares_direct_channel_and_artifacts():
    adapter = UpworkAdapter(chrome_scanner=AsyncMock(), chrome_submitter=AsyncMock())
    assert adapter.submission_channel == SubmissionChannel.direct
    assert "cover_letter" in adapter.required_artifacts


async def test_upwork_submit_application_fills_but_does_not_submit():
    submitter = AsyncMock()
    submitter.fill = AsyncMock(return_value=True)
    adapter = UpworkAdapter(chrome_scanner=AsyncMock(), chrome_submitter=submitter)

    result = await adapter.submit_application(contract="C", application="P")

    assert isinstance(result, SubmitResult)
    assert result.filled is True
    assert result.submitted is False     # human-in-loop invariant
    submitter.fill.assert_awaited_once_with("C", "P")
