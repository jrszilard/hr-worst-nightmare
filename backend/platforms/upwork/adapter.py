"""Upwork platform adapter — delegates to ChromeScanner and ChromeSubmitter."""

from __future__ import annotations

from typing import Callable

from backend.core.enums import SubmissionChannel
from backend.core.models import ContractCreate
from backend.core.platform import PlatformAdapter, SubmitResult
from backend.platforms.upwork.chrome_scanner import ChromeScanner
from backend.platforms.upwork.chrome_submit import ChromeSubmitter


class UpworkAdapter(PlatformAdapter):
    """Concrete :class:`PlatformAdapter` for Upwork (direct-fill channel)."""

    submission_channel = SubmissionChannel.direct
    required_artifacts = ["cover_letter", "screening_answers"]

    def __init__(
        self,
        chrome_scanner: ChromeScanner,
        chrome_submitter: ChromeSubmitter,
    ) -> None:
        self.scanner = chrome_scanner
        self.submitter = chrome_submitter

    async def scan_contracts(
        self,
        search_config: dict,
        on_contract: Callable[[ContractCreate], None],
    ) -> int:
        """Scan Upwork for contracts matching *search_config*."""
        return await self.scanner.scan(search_config, on_contract)

    async def submit_application(self, contract, application) -> SubmitResult:
        """Fill the Upwork proposal form (does NOT click submit)."""
        filled = await self.submitter.fill(contract, application)
        return SubmitResult(filled=bool(filled), submitted=False)
