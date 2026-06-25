"""BrowserEngine that drives the sibling ai-in-browser adapter over MCP (stdio).

Thin: it maps the mechanical ops onto ai-in-browser's MCP tools and re-resolves the
engine-neutral FormField.key to a fresh (ref, observationId) per action (ai-in-browser
refs are per-observation). All policy, gating, never-auto-submit, and audit redaction
live in ai-in-browser's bridge — this engine never re-implements them.
"""

from __future__ import annotations

import logging
import os
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from backend.platforms.browser.aiinbrowser_map import (
    observation_to_fields,
    parse_observation,
    resolve_ref,
)
from backend.platforms.browser.engine import BrowserEngine, PageSnapshot, SelectOutcome

logger = logging.getLogger(__name__)


class AiInBrowserEngine(BrowserEngine):
    def __init__(self, *, repo: str, connect_ms: int = 35_000, session=None) -> None:
        self._repo = repo
        self._connect_ms = connect_ms
        self._session = session  # injected in tests; None -> lazily spawned (Task 3)
        self._stack = None       # AsyncExitStack owning a spawned session (Task 3)

    async def _ensure(self):
        """Lazily spawn the ai-in-browser adapter and open an MCP session.

        The session + subprocess are held open across ops by an AsyncExitStack and
        torn down in close(). The adapter starts the bridge WS; the user's Brave
        extension connects to it (the adapter waits up to AIB_CONNECT_MS).
        """
        if self._session is not None:
            return self._session
        entry = os.path.join(self._repo, "packages", "adapter-mcp", "src", "main.ts")
        params = StdioServerParameters(
            command="corepack",
            args=["pnpm", "exec", "tsx", entry],
            cwd=self._repo,
            env={**os.environ, "AIB_CONNECT_MS": str(self._connect_ms)},
        )
        self._stack = AsyncExitStack()
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        return self._session

    async def _invoke(self, name: str, arguments: dict) -> tuple[str, bool]:
        """Call an MCP tool, returning (text, is_error) WITHOUT raising on a tool error.

        The raising policy is the caller's: most ops use _call (raise -> abort, never
        submit), but select translates an error into an escalation rather than aborting."""
        session = await self._ensure()
        res = await session.call_tool(name, arguments)
        text = "\n".join(c.text for c in res.content if getattr(c, "type", "") == "text")
        return text, bool(res.isError)

    async def _call(self, name: str, arguments: dict) -> str:
        text, is_error = await self._invoke(name, arguments)
        if is_error:
            raise RuntimeError(f"ai-in-browser {name} failed: {text}")
        return text

    async def _observe(self) -> dict:
        return parse_observation(await self._call("browser_observe", {}))

    async def goto(self, url: str) -> None:
        await self._call("browser_navigate", {"url": url})

    async def snapshot(self) -> PageSnapshot:
        return PageSnapshot(fields=observation_to_fields(await self._observe()))

    async def fill(self, key: str, value: str) -> None:
        ref, oid = resolve_ref(await self._observe(), key)
        await self._call("browser_type", {"ref": ref, "value": value, "observationId": oid})

    async def select(self, key: str, option: str) -> SelectOutcome:
        ref, oid = resolve_ref(await self._observe(), key)
        # A failed select (status: error / stale_ref, surfaced as an MCP isError) is a
        # per-field miss, not an apply-fatal error: parse it to ok=False so the driver
        # re-matches/escalates just this field. A genuinely dead browser aborts earlier,
        # at the _observe() above (which uses the raising _call).
        text, _is_error = await self._invoke(
            "browser_select", {"ref": ref, "option": option, "observationId": oid})
        return self._parse_select_result(text)

    @staticmethod
    def _parse_select_result(text: str) -> SelectOutcome:
        """Parse a browser_select formatResult into a SelectOutcome.

        The adapter's formatResult emits `status: executed|no_match` on the first line
        and, on a miss, an `availableOptions: A, B, C` line. Anything other than an
        explicit `executed` status is treated as a miss so the driver re-matches/escalates
        rather than silently reporting a fill."""
        ok = False
        options: list[str] = []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("status:"):
                ok = line[len("status:"):].strip() == "executed"
            elif line.startswith("availableOptions:"):
                raw = line[len("availableOptions:"):].strip()
                options = [o.strip() for o in raw.split(",") if o.strip()]
        return SelectOutcome(ok=ok, available_options=options)

    async def click(self, key: str) -> None:
        ref, oid = resolve_ref(await self._observe(), key)
        await self._call("browser_click", {"ref": ref, "observationId": oid})

    async def upload(self, key: str, path: str) -> bool:
        # ai-in-browser slice 1 has no upload execution: escalate to the human and
        # report the upload unconfirmed (apply_driver treats that as a handoff reason).
        await self._call("browser_await_human", {"reason": f"upload {path} to {key}"})
        return False

    async def has_visible_captcha(self) -> bool:
        return bool((await self._observe()).get("captchaPresent"))

    async def screenshot(self) -> bytes:
        return b""  # no screenshot capability in ai-in-browser slice 1

    async def await_human(self, reason: str) -> None:
        # await_human is the terminal handoff and blocks until the human takes over. The user's
        # browser tab is independent of our MCP control bridge, so release the bridge here — in
        # the SAME task that opened it (close() -> AsyncExitStack.aclose()). Leaving it for the
        # GC instead exits the adapter's anyio cancel scope in a finalizer (a different task),
        # printing a noisy "Attempted to exit cancel scope in a different task" RuntimeError.
        # This mirrors PlaywrightEngine.await_human, which also owns its own teardown policy.
        try:
            await self._call("browser_await_human", {"reason": reason})
        finally:
            await self.close()

    async def close(self) -> None:
        # Idempotent + never raises. The spawned-session teardown is added in Task 3;
        # with an injected session there is nothing to tear down.
        if self._stack is not None:
            try:
                await self._stack.aclose()
            except Exception:  # noqa: BLE001
                logger.warning("ai-in-browser session close failed")
            finally:
                self._stack = None
        self._session = None
