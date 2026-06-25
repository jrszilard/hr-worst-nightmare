"""Tier 2 resolution: load the posting headlessly, follow redirects, find the
real apply link, classify it. The pure logic (choose_terminal) is unit-tested; the
real PlaywrightResolverBrowser (added separately) does the I/O and is verified live."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Protocol

from backend.platforms.ats_registry import Capability, first_known_ats
from backend.platforms.resolve.resolution import Resolution, ResolutionStatus, ResolutionTier

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PageState:
    """What the headless browser observed: the URL after redirects, the HTTP
    status of the navigation, and every (text, href) anchor on the page."""
    final_url: str
    status: int | None
    links: list[tuple[str, str]]


class ResolverBrowser(Protocol):
    """Minimal browser surface Tier 2 needs — NOT the form-oriented BrowserEngine."""
    async def load(self, url: str) -> PageState: ...
    async def close(self) -> None: ...


def _blocked() -> Resolution:
    return Resolution(None, "unknown", Capability.manual, ResolutionStatus.blocked, ResolutionTier.headless)


def choose_terminal(state: PageState) -> Resolution:
    """Pick the terminal apply URL from a loaded page + classify it.

    HTTP >= 400 -> dead. Else the first known ATS among (final_url, *link hrefs),
    preferring engine_fillable over multi_page. No known ATS -> blocked (Tier-3 queue)."""
    if state.status is not None and state.status >= 400:
        return Resolution(None, "unknown", Capability.manual, ResolutionStatus.dead, ResolutionTier.headless)
    candidates: list[str | None] = [state.final_url]
    candidates.extend(href for _text, href in state.links)
    hit = first_known_ats(candidates)
    if hit is not None:
        url, slug, cap = hit
        return Resolution(url, slug, cap, ResolutionStatus.resolved, ResolutionTier.headless)
    return _blocked()


async def resolve_headless(url: str, make_browser: Callable[[], ResolverBrowser]) -> Resolution:
    """Load *url* with a headless browser and resolve it. Any load failure
    (timeout / bot-block / network) -> blocked. The browser is always closed,
    and a teardown failure is logged but never masks the resolution."""
    browser = make_browser()
    try:
        state = await browser.load(url)
    except Exception as exc:  # noqa: BLE001 — every load failure routes to Tier 3
        logger.warning("headless load failed for %s: %s", url, exc)
        return _blocked()
    finally:
        try:
            await browser.close()
        except Exception as exc:  # noqa: BLE001 — teardown failure must not lose the resolution
            logger.warning("headless browser close failed for %s: %s", url, exc)
    return choose_terminal(state)


class FakeResolverBrowser:
    """Test double: returns a canned PageState or raises a canned error on load()."""
    def __init__(self, *, state: PageState | None = None, error: Exception | None = None) -> None:
        self._state = state
        self._error = error
        self.closed = False

    async def load(self, url: str) -> PageState:
        if self._error is not None:
            raise self._error
        assert self._state is not None
        return self._state

    async def close(self) -> None:
        self.closed = True


class PlaywrightResolverBrowser:
    """Headless Chromium that reads the post-redirect URL + all anchors. Reuses the
    same launch/teardown shape as PlaywrightEngine but is read-only (no fills)."""
    def __init__(self, *, timeout_ms: int = 45_000, settle_ms: int = 2_000) -> None:
        self.timeout_ms = timeout_ms
        self.settle_ms = settle_ms
        self._p = None
        self._browser = None
        self._page = None

    async def load(self, url: str) -> PageState:
        from playwright.async_api import async_playwright

        self._p = await async_playwright().start()
        self._browser = await self._p.chromium.launch(headless=True)
        self._page = await self._browser.new_page()
        resp = await self._page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        await self._page.wait_for_timeout(self.settle_ms)
        status = resp.status if resp is not None else None
        final_url = self._page.url
        anchors = await self._page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => [ (e.innerText || '').trim(), e.href ])",
        )
        links = [(text, href) for text, href in anchors if href]
        return PageState(final_url=final_url, status=status, links=links)

    async def close(self) -> None:
        try:
            if self._browser is not None:
                await self._browser.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._p is not None:
                await self._p.stop()
        except Exception:  # noqa: BLE001
            pass
        self._browser = self._p = self._page = None
