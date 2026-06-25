import json
from dataclasses import dataclass

import pytest

from backend.platforms.browser.aiinbrowser_engine import AiInBrowserEngine
from backend.platforms.browser.engine import PageSnapshot

_OBS = {
    "observationId": "o1",
    "url": "http://127.0.0.1/form",
    "title": "Form",
    "captchaPresent": False,
    "elements": [
        {"ref": "e1", "role": "textbox", "name": "First Name"},
        {"ref": "e2", "role": "combobox", "name": "Country", "options": ["United States", "Germany"]},
    ],
    "textDigest": "a form",
}
_OBS_JSON = json.dumps(_OBS)


@dataclass
class _Content:
    text: str
    type: str = "text"


@dataclass
class _Result:
    content: list
    isError: bool = False


class FakeMcpSession:
    """Returns scripted (text, isError) results in order; records every call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name, arguments=None, **_):
        self.calls.append((name, arguments or {}))
        text, is_err = self._responses.pop(0)
        return _Result(content=[_Content(text=text)], isError=is_err)


def _engine(responses):
    return AiInBrowserEngine(repo="/unused", session=FakeMcpSession(responses))


async def test_goto_calls_browser_navigate():
    eng = _engine([("status: executed", False)])
    await eng.goto("http://127.0.0.1/form")
    assert eng._session.calls == [("browser_navigate", {"url": "http://127.0.0.1/form"})]


async def test_snapshot_maps_observation_to_pagesnapshot():
    eng = _engine([(_OBS_JSON, False)])
    snap = await eng.snapshot()
    assert isinstance(snap, PageSnapshot)
    assert [f.label for f in snap.fields] == ["First Name", "Country"]
    assert eng._session.calls == [("browser_observe", {})]


async def test_fill_reobserves_then_types_with_fresh_ref():
    eng = _engine([(_OBS_JSON, False), ("status: executed", False)])
    await eng.fill("First Name", "Pat")
    assert eng._session.calls == [
        ("browser_observe", {}),
        ("browser_type", {"ref": "e1", "value": "Pat", "observationId": "o1"}),
    ]


async def test_select_reobserves_then_selects():
    eng = _engine([(_OBS_JSON, False), ("status: executed", False)])
    await eng.select("Country", "United States")
    assert eng._session.calls[-1] == (
        "browser_select",
        {"ref": "e2", "option": "United States", "observationId": "o1"},
    )


async def test_click_reobserves_then_clicks():
    eng = _engine([(_OBS_JSON, False), ("status: executed", False)])
    await eng.click("First Name")
    assert eng._session.calls[-1] == ("browser_click", {"ref": "e1", "observationId": "o1"})


async def test_upload_escalates_to_human_and_reports_unconfirmed():
    eng = _engine([("handoff outcome: continued", False)])
    confirmed = await eng.upload("First Name", "/tmp/resume.pdf")
    assert confirmed is False
    assert eng._session.calls == [
        ("browser_await_human", {"reason": "upload /tmp/resume.pdf to First Name"}),
    ]


async def test_has_visible_captcha_reads_observation_flag():
    obs = {**_OBS, "captchaPresent": True}
    eng = _engine([(json.dumps(obs), False)])
    assert await eng.has_visible_captcha() is True


async def test_screenshot_returns_empty_without_a_tool_call():
    eng = _engine([])
    assert await eng.screenshot() == b""
    assert eng._session.calls == []


async def test_await_human_passes_reason_then_releases_the_bridge():
    # await_human is the terminal handoff; after it resolves it releases the MCP control bridge
    # (close()) in the same task that opened it, so the GC never tears the adapter's anyio
    # cancel scope down in a finalizer (the "cancel scope in a different task" RuntimeError).
    session = FakeMcpSession([("handoff outcome: continued", False)])
    eng = AiInBrowserEngine(repo="/unused", session=session)
    await eng.await_human("review the filled form")
    assert session.calls == [("browser_await_human", {"reason": "review the filled form"})]
    assert eng._session is None   # bridge released after the handoff


async def test_await_human_releases_the_bridge_even_if_handoff_errors():
    # If the handoff tool itself errors we still release the bridge (finally) so the session is
    # never left for the GC to tear down out-of-task.
    session = FakeMcpSession([("no browser connected", True)])
    eng = AiInBrowserEngine(repo="/unused", session=session)
    with pytest.raises(RuntimeError):
        await eng.await_human("review the filled form")
    assert eng._session is None


async def test_tool_error_raises_so_caller_never_submits():
    eng = _engine([(_OBS_JSON, False), ("no browser connected", True)])
    with pytest.raises(RuntimeError, match="no browser connected"):
        await eng.fill("First Name", "Pat")


async def test_select_tool_error_escalates_instead_of_aborting_the_apply():
    # RC-A: one dropdown failing to actuate (the executor returns status: error and the
    # adapter marks the MCP result isError) must NOT raise out of select — it returns
    # ok=False so the driver escalates just that field instead of torching the whole apply.
    eng = _engine([(_OBS_JSON, False),
                   ("status: error\nerror: selection did not register", True)])
    outcome = await eng.select("Country", "United States")
    assert outcome.ok is False


async def test_select_error_still_surfaces_available_options_for_rematch():
    # Even on an errored select, any availableOptions in the payload are preserved so the
    # driver's fuzzy re-match can try the live options before escalating.
    eng = _engine([(_OBS_JSON, False),
                   ("status: error\navailableOptions: Yes, I do, No, I don't", True)])
    outcome = await eng.select("Country", "United States")
    assert outcome.ok is False
    assert "Yes" in outcome.available_options[0]


async def test_close_is_idempotent_and_never_raises_with_injected_session():
    eng = _engine([])
    await eng.close()
    await eng.close()  # must not raise


async def test_close_without_session_is_a_noop_and_idempotent():
    # No injected session and no spawn performed: close() must be safe to call.
    eng = AiInBrowserEngine(repo="/unused")
    await eng.close()
    await eng.close()  # must not raise


async def test_ops_without_session_attempt_a_spawn_path(monkeypatch):
    # With no injected session, _ensure must go through the spawn path (we stub it to
    # confirm ops call _ensure rather than assuming a session exists).
    eng = AiInBrowserEngine(repo="/unused")
    spawned = {}

    async def fake_ensure():
        spawned["did"] = True
        eng._session = FakeMcpSession([("status: executed", False)])
        return eng._session

    monkeypatch.setattr(eng, "_ensure", fake_ensure)
    await eng.goto("http://x")
    assert spawned.get("did") is True


# ---------------------------------------------------------------------------
# _parse_select_result — pure parser unit tests (no browser, no MCP session)
# ---------------------------------------------------------------------------

from backend.platforms.browser.engine import SelectOutcome  # noqa: E402


def test_parse_select_result_executed():
    text = "status: executed\nrisk: medium\nreason: ordinary dropdown"
    out = AiInBrowserEngine._parse_select_result(text)
    assert out == SelectOutcome(ok=True, available_options=[])


def test_parse_select_result_no_match_with_options():
    text = ("status: no_match\nrisk: medium\nreason: ordinary dropdown\n"
            "availableOptions: United States, Canada")
    out = AiInBrowserEngine._parse_select_result(text)
    assert out.ok is False
    assert out.available_options == ["United States", "Canada"]


def test_parse_select_result_no_match_without_options():
    text = "status: no_match\nrisk: medium\nreason: ordinary dropdown"
    out = AiInBrowserEngine._parse_select_result(text)
    assert out.ok is False
    assert out.available_options == []
