# tests/test_browser_engine.py
import pytest

from backend.platforms.browser.engine import BrowserEngine, PageSnapshot
from backend.platforms.browser.fake_engine import FakeEngine
from backend.platforms.form_fill import FormField


def test_fake_engine_is_a_browser_engine():
    assert issubclass(FakeEngine, BrowserEngine)


async def test_snapshot_returns_scripted_fields():
    snap = PageSnapshot(fields=[FormField(label="First Name", id="first_name")])
    engine = FakeEngine(snapshots=[snap])
    out = await engine.snapshot()
    assert [f.label for f in out.fields] == ["First Name"]
    assert ("snapshot", ()) in [(c.op, c.args) for c in engine.calls]


async def test_fill_select_click_record_ops():
    engine = FakeEngine()
    await engine.goto("https://x.test/apply")
    await engine.fill("#first_name", "Pat")
    await engine.select("#country", "United States")
    await engine.click("#next")
    ops = [(c.op, c.args) for c in engine.calls]
    assert ("goto", ("https://x.test/apply",)) in ops
    assert ("fill", ("#first_name", "Pat")) in ops
    assert ("select", ("#country", "United States")) in ops
    assert ("click", ("#next",)) in ops


async def test_upload_returns_confirmed_flag():
    assert await FakeEngine(upload_confirmed=True).upload("#resume", "/tmp/r.pdf") is True
    assert await FakeEngine(upload_confirmed=False).upload("#resume", "/tmp/r.pdf") is False


async def test_snapshot_sequence_consumes_then_reuses_last():
    snaps = [PageSnapshot(fields=[FormField(label="A", id="a")]),
             PageSnapshot(fields=[FormField(label="B", id="b")])]
    engine = FakeEngine(snapshots=snaps)
    first = await engine.snapshot()
    second = await engine.snapshot()
    third = await engine.snapshot()
    assert [f.label for f in first.fields] == ["A"]
    assert [f.label for f in second.fields] == ["B"]
    assert [f.label for f in third.fields] == ["B"]  # last is reused


async def test_captcha_and_await_human_and_close():
    engine = FakeEngine(captcha=True)
    assert await engine.has_visible_captcha() is True
    await engine.await_human("filled; awaiting human submit")
    assert engine.human_reason == "filled; awaiting human submit"
    await engine.close()
    assert engine.closed is True
