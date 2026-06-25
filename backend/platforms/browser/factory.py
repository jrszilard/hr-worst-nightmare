"""Build the configured BrowserEngine. The engine is a global config choice; the
driver varies per ATS (via SubmissionChannel) above this layer."""

from __future__ import annotations

from pathlib import Path

from backend.config import settings
from backend.core.profile_context import ProfileContext
from backend.platforms.browser.engine import BrowserEngine


def get_browser_engine(ctx: ProfileContext, *, headless: bool = False,
                       keep_open: bool = False) -> BrowserEngine:
    name = settings.BROWSER_ENGINE.lower()

    # ai-in-browser drives the user's VISIBLE real Brave; it cannot do a silent
    # headless read, so a headless request always falls through to Playwright.
    if name == "aiinbrowser" and not headless:
        from backend.platforms.browser.aiinbrowser_engine import AiInBrowserEngine

        repo = settings.AIINBROWSER_REPO or str(
            Path(__file__).resolve().parents[3].parent / "ai-in-browser"
        )
        return AiInBrowserEngine(repo=repo, connect_ms=settings.AIINBROWSER_CONNECT_MS)

    if name not in {"playwright", "aiinbrowser"}:
        raise ValueError(f"Unknown BROWSER_ENGINE: {name!r}")

    mode = settings.BROWSER_MODE.lower()
    if mode not in {"launch", "cdp"}:
        raise ValueError(f"Unknown BROWSER_MODE: {mode!r}")

    from backend.platforms.browser.playwright_engine import PlaywrightEngine

    # A headless request is a silent background read (e.g. question-discovery preflight).
    # cdp would attach to the user's visible Chrome and ignore headless, so headless
    # always launches.
    if mode == "cdp" and not headless:
        return PlaywrightEngine(mode="cdp", cdp_url=settings.CHROME_MCP_URL,
                                headless=headless, keep_open=keep_open)
    return PlaywrightEngine(mode="launch",
                            user_data_dir=str(ctx.root / "browser_profile"),
                            headless=headless, keep_open=keep_open)
