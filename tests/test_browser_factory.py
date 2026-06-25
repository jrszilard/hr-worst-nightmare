import pytest

from backend.config import settings
from backend.core.profile_context import ProfileContext, get_profile_context
from backend.platforms.browser.aiinbrowser_engine import AiInBrowserEngine
from backend.platforms.browser.engine import BrowserEngine
from backend.platforms.browser.factory import get_browser_engine
from backend.platforms.browser.playwright_engine import PlaywrightEngine


@pytest.fixture
def ctx(tmp_path):
    return ProfileContext(tmp_path)


def test_default_engine_is_playwright_launch(ctx, monkeypatch):
    monkeypatch.setattr(settings, "BROWSER_ENGINE", "playwright")
    monkeypatch.setattr(settings, "BROWSER_MODE", "launch")
    engine = get_browser_engine(ctx, headless=True)
    assert isinstance(engine, BrowserEngine)
    assert engine.mode == "launch"
    assert engine.headless is True


def test_cdp_mode_wires_cdp_url(ctx, monkeypatch):
    monkeypatch.setattr(settings, "BROWSER_ENGINE", "playwright")
    monkeypatch.setattr(settings, "BROWSER_MODE", "cdp")
    monkeypatch.setattr(settings, "CHROME_MCP_URL", "http://localhost:9222")
    engine = get_browser_engine(ctx)
    assert engine.mode == "cdp"
    assert engine.cdp_url == "http://localhost:9222"


def test_headless_request_never_attaches_to_real_chrome(ctx, monkeypatch):
    # A headless (silent preflight) request must launch, never cdp-attach to the
    # user's visible Chrome — even when cdp is the configured mode.
    monkeypatch.setattr(settings, "BROWSER_ENGINE", "playwright")
    monkeypatch.setattr(settings, "BROWSER_MODE", "cdp")
    engine = get_browser_engine(ctx, headless=True)
    assert engine.mode == "launch"


def test_unknown_engine_raises(ctx, monkeypatch):
    monkeypatch.setattr(settings, "BROWSER_ENGINE", "nope")
    with pytest.raises(ValueError):
        get_browser_engine(ctx)


def test_unknown_mode_raises(ctx, monkeypatch):
    monkeypatch.setattr(settings, "BROWSER_ENGINE", "playwright")
    monkeypatch.setattr(settings, "BROWSER_MODE", "weird")
    with pytest.raises(ValueError):
        get_browser_engine(ctx)


def test_profile_context_browser_engine_property(monkeypatch):
    monkeypatch.setattr(settings, "BROWSER_ENGINE", "playwright")
    assert ProfileContext("data").browser_engine == "playwright"


async def test_aiinbrowser_visible_returns_aiinbrowser_engine(monkeypatch):
    monkeypatch.setattr(settings, "BROWSER_ENGINE", "aiinbrowser")
    monkeypatch.setattr(settings, "AIINBROWSER_REPO", "/tmp/ai-in-browser")
    engine = get_browser_engine(get_profile_context(), headless=False)
    try:
        assert isinstance(engine, AiInBrowserEngine)
    finally:
        await engine.close()


def test_aiinbrowser_headless_falls_back_to_playwright(monkeypatch):
    # Silent background reads cannot use the user's visible Brave -> Playwright.
    monkeypatch.setattr(settings, "BROWSER_ENGINE", "aiinbrowser")
    monkeypatch.setattr(settings, "BROWSER_MODE", "launch")
    engine = get_browser_engine(get_profile_context(), headless=True)
    assert isinstance(engine, PlaywrightEngine)


def test_unknown_engine_still_raises(monkeypatch):
    monkeypatch.setattr(settings, "BROWSER_ENGINE", "bogus")
    with pytest.raises(ValueError):
        get_browser_engine(get_profile_context(), headless=False)
