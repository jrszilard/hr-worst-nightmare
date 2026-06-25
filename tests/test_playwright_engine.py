import pathlib

import pytest

from backend.platforms.browser.playwright_engine import PlaywrightEngine

pytestmark = pytest.mark.browser

_FORMS = pathlib.Path(__file__).parent / "fixtures" / "forms"
_FIXTURE = _FORMS / "sample_apply.html"
_COMBOBOX_FIXTURE = _FORMS / "sample_combobox.html"


async def test_snapshot_reads_fields_and_fill_sets_value():
    engine = PlaywrightEngine(mode="launch", headless=True)
    try:
        await engine.goto(_FIXTURE.as_uri())
        snap = await engine.snapshot()
        labels = {f.label for f in snap.fields}
        assert "First Name" in labels
        assert "Additional information" in labels

        await engine.fill("#first_name", "Pat")
        value = await engine._page.locator('[id="first_name"]').input_value()
        assert value == "Pat"

        assert await engine.has_visible_captcha() is False
    finally:
        await engine.close()


async def test_snapshot_populates_combobox_options():
    # The documented snapshot() contract: combobox fields come back with their
    # options populated, so the driver's plan_fill can match dropdown choices.
    engine = PlaywrightEngine(mode="launch", headless=True)
    try:
        await engine.goto(_COMBOBOX_FIXTURE.as_uri())
        snap = await engine.snapshot()
        combos = [f for f in snap.fields if f.kind == "combobox"]
        assert combos, "expected a combobox field in the snapshot"
        assert combos[0].options == ["United States", "Canada"]
    finally:
        await engine.close()
