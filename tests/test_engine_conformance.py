"""Conformance: any BrowserEngine honors the same op contract.

Runs against FakeEngine always; against PlaywrightEngine under `-m browser`. This is
what makes "model-agnostic" CI-enforced — a future engine (e.g. AiInBrowserEngine) runs
the same suite and is known to be a drop-in.
"""

import pathlib

import pytest

from backend.platforms.browser.engine import BrowserEngine, PageSnapshot
from backend.platforms.browser.fake_engine import FakeEngine
from backend.platforms.form_fill import FormField

_FORMS = pathlib.Path(__file__).parent / "fixtures" / "forms"
_APPLY_URL = (_FORMS / "sample_apply.html").as_uri()


def _fake():
    # Scripted to mirror the sample_apply.html fixture's first field.
    snap = PageSnapshot(fields=[FormField(label="First Name", id="first_name")])
    return FakeEngine(snapshots=[snap])


def _playwright():
    from backend.platforms.browser.playwright_engine import PlaywrightEngine

    return PlaywrightEngine(mode="launch", headless=True)


_ENGINES = [
    pytest.param(_fake, id="fake"),
    pytest.param(_playwright, id="playwright", marks=pytest.mark.browser),
]


async def assert_honors_op_contract(engine: BrowserEngine, apply_url: str) -> None:
    """The shared op contract every BrowserEngine must honor."""
    assert isinstance(engine, BrowserEngine)
    try:
        await engine.goto(apply_url)
        snap = await engine.snapshot()
        first = next((f for f in snap.fields if f.label == "First Name"), None)
        assert first is not None, "snapshot must surface the First Name field"
        await engine.fill(first.key, "Pat")          # engine's own key — must not raise
        assert await engine.has_visible_captcha() is False
        from backend.platforms.browser.engine import SelectOutcome
        outcome = await engine.select(first.key, "Pat")   # may be a miss; only the shape is asserted
        assert isinstance(outcome, SelectOutcome)
        assert isinstance(outcome.available_options, list)
    finally:
        await engine.close()
    await engine.close()  # close() is idempotent and must not raise


@pytest.mark.parametrize("make_engine", _ENGINES)
async def test_engine_honors_op_contract(make_engine):
    await assert_honors_op_contract(make_engine(), _APPLY_URL)


@pytest.mark.parametrize("make_engine", _ENGINES)
async def test_engine_select_returns_outcome(make_engine):
    from backend.platforms.browser.engine import SelectOutcome

    engine = make_engine()
    try:
        await engine.goto(_APPLY_URL)
        await engine.snapshot()
        outcome = await engine.select("First Name", "Pat")
        assert isinstance(outcome, SelectOutcome)
        assert isinstance(outcome.ok, bool)
        assert isinstance(outcome.available_options, list)
    finally:
        await engine.close()


async def test_fake_engine_select_can_force_no_match():
    from backend.platforms.browser.engine import SelectOutcome

    engine = FakeEngine(
        snapshots=[PageSnapshot(fields=[FormField(label="Country", kind="combobox")])],
        select_outcome=SelectOutcome(ok=False, available_options=["United States", "Canada"]),
    )
    outcome = await engine.select("Country", "USA")
    assert outcome.ok is False
    assert outcome.available_options == ["United States", "Canada"]
