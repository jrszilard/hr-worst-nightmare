"""Abstract base class for platform adapters.

Each platform (Upwork, LinkedIn, Indeed, Greenhouse, etc.) implements this
interface so the rest of the system can scan for opportunities and fill
application forms without knowing platform-specific details.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable

from backend.core.enums import SubmissionChannel
from backend.core.models import ContractCreate


@dataclass
class SubmitResult:
    """Outcome of an application submission attempt.

    ``submitted`` is always False in this codebase: we fill forms but never
    auto-click the final submit (human-in-loop invariant).
    """

    filled: bool
    submitted: bool = False
    detail: str | None = None
    #: Per-dropdown planner notes the human reviews: {field, value, reasoning, confidence}.
    fill_notes: list[dict] = field(default_factory=list)


class PlatformAdapter(ABC):
    """Base class that every platform adapter must implement."""

    #: How applications are submitted on this platform.
    submission_channel: SubmissionChannel = SubmissionChannel.direct
    #: Artifacts this platform requires for an application.
    required_artifacts: list[str] = []

    @abstractmethod
    async def scan_contracts(
        self,
        search_config: dict,
        on_contract: Callable[[ContractCreate], None],
    ) -> int:
        """Scan the platform for contracts matching *search_config*."""
        ...

    @abstractmethod
    async def submit_application(self, contract, application) -> SubmitResult:
        """Fill (but never finally submit) the platform's application form.

        Returns a :class:`SubmitResult`. Implementations MUST NOT click the
        final submit button — the human reviews and submits.
        """
        ...
