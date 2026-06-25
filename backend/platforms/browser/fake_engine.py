"""In-memory BrowserEngine for unit-testing orchestrators without a browser."""

from __future__ import annotations

from dataclasses import dataclass

from backend.platforms.browser.engine import BrowserEngine, PageSnapshot, SelectOutcome


@dataclass
class _Call:
    op: str
    args: tuple


class FakeEngine(BrowserEngine):
    def __init__(self, snapshots: list[PageSnapshot] | None = None, *,
                 captcha: bool = False, upload_confirmed: bool = True,
                 select_outcome: SelectOutcome | None = None) -> None:
        self._snapshots = list(snapshots or [])
        self._captcha = captcha
        self._upload_confirmed = upload_confirmed
        self._select_outcome = select_outcome
        self.calls: list[_Call] = []
        self.human_reason: str | None = None
        self.closed = False

    async def goto(self, url: str) -> None:
        self.calls.append(_Call("goto", (url,)))

    async def snapshot(self) -> PageSnapshot:
        """Return the next scripted snapshot.

        Scripted snapshots are consumed in order; the last (or only) one is reused
        for any further calls, so a single scripted snapshot serves repeated reads.
        An empty script yields an empty PageSnapshot.
        """
        self.calls.append(_Call("snapshot", ()))
        if len(self._snapshots) > 1:
            return self._snapshots.pop(0)
        return self._snapshots[0] if self._snapshots else PageSnapshot(fields=[])

    async def fill(self, key: str, value: str) -> None:
        self.calls.append(_Call("fill", (key, value)))

    async def select(self, key: str, option: str) -> SelectOutcome:
        self.calls.append(_Call("select", (key, option)))
        if self._select_outcome is not None:
            # If the requested option is one of the available options, it succeeds.
            if option in self._select_outcome.available_options:
                return SelectOutcome(ok=True, available_options=self._select_outcome.available_options)
            return self._select_outcome
        return SelectOutcome(ok=True, available_options=[])

    async def upload(self, key: str, path: str) -> bool:
        self.calls.append(_Call("upload", (key, path)))
        return self._upload_confirmed

    async def click(self, key: str) -> None:
        self.calls.append(_Call("click", (key,)))

    async def has_visible_captcha(self) -> bool:
        return self._captcha

    async def screenshot(self) -> bytes:
        return b""

    async def await_human(self, reason: str) -> None:
        self.human_reason = reason
        self.calls.append(_Call("await_human", (reason,)))

    async def close(self) -> None:
        self.closed = True
        self.calls.append(_Call("close", ()))
