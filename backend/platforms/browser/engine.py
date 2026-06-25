"""The mechanical browser-control seam.

A BrowserEngine exposes primitive operations only — no model, no application logic.
Every engine produces the same engine-neutral PageSnapshot (a list of form_fill.FormField
descriptors), so orchestrators above are fully engine-agnostic. The field reference passed
to ops is the FormField.key string ('#<id>' or the label text).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field as dc_field

from backend.platforms.form_fill import FormField


@dataclass
class PageSnapshot:
    """A structured, engine-neutral read of a page's fillable fields."""

    fields: list[FormField] = dc_field(default_factory=list)


@dataclass
class SelectOutcome:
    """Outcome of a ``select`` op so the driver's completeness gate is honest.

    ``ok`` is True when the option was actually chosen on-page. On a miss the engine
    reports the live ``available_options`` so the driver can deterministically re-match
    the intended value (e.g. "No" -> "No, I don't") before escalating to the human.
    ``upload -> bool`` is the precedent for a non-None op return.
    """

    ok: bool
    available_options: list[str] = dc_field(default_factory=list)


class BrowserEngine(ABC):
    """Mechanical browser operations. Implementations never click a final submit."""

    @abstractmethod
    async def goto(self, url: str) -> None: ...

    @abstractmethod
    async def snapshot(self) -> PageSnapshot:
        """Read the page's fillable fields as an engine-neutral PageSnapshot.

        Implementations MUST return a COMPLETE snapshot: combobox/select fields must
        have their ``options`` populated, so the driver's form_fill.plan_fill can match
        dropdown choices instead of escalating them as unfilled.
        """
        ...

    @abstractmethod
    async def fill(self, key: str, value: str) -> None: ...

    @abstractmethod
    async def select(self, key: str, option: str) -> SelectOutcome: ...

    @abstractmethod
    async def upload(self, key: str, path: str) -> bool:
        """Upload a file; return True if the upload was confirmed on-page."""
        ...

    @abstractmethod
    async def click(self, key: str) -> None: ...

    @abstractmethod
    async def has_visible_captcha(self) -> bool: ...

    @abstractmethod
    async def screenshot(self) -> bytes: ...

    @abstractmethod
    async def await_human(self, reason: str) -> None:
        """The single human-in-the-loop handoff (captcha / account wall / final submit)."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release the browser. MUST be safe to call more than once and MUST NOT raise."""
        ...
