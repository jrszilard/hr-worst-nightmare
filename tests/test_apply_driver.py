import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.core.models import ApplicantInfo
from backend.platforms.browser.engine import PageSnapshot
from backend.platforms.browser.fake_engine import FakeEngine
from backend.platforms.browser.apply_driver import (
    _fuzzy_match_option, _to_apply_form_url, discover_questions, fill_application,
)
from backend.platforms.form_fill import FormField


def _applicant() -> ApplicantInfo:
    return ApplicantInfo(first_name="Pat", last_name="Sample",
                         email="pat@example.com", phone="555-0100")


def test_fuzzy_match_reduces_prose_prefixed_yes_no_to_bare_option():
    # F1 fallback: when the planner prefixes its essay onto a yes/no answer
    # ("Yes, SQL has 4 years..."), the leading yes/no word must still reduce to the
    # bare on-page option. The trailing comma on "Yes," must not break the match.
    assert _fuzzy_match_option("Yes, SQL has 4 years of usage", ["Yes", "No"]) == "Yes"
    assert _fuzzy_match_option("No, I have not managed a dbt project", ["Yes", "No"]) == "No"
    # the existing "No" -> "No, I don't" expansion still works
    assert _fuzzy_match_option("No", ["Yes, I do", "No, I don't"]) == "No, I don't"


def test_to_apply_form_url_rewrites_ashby():
    assert _to_apply_form_url("https://jobs.ashbyhq.com/acme/123").endswith("/acme/123/application")


def test_to_apply_form_url_is_idempotent_for_ashby():
    already = "https://jobs.ashbyhq.com/acme/123/application"
    assert _to_apply_form_url(already) == already


def test_greenhouse_listing_becomes_embed_form_url():
    # job-boards.greenhouse.io/<company>/jobs/<id> gates the form behind an "Apply" click that
    # lazy-renders it (Coinbase #2605 -> the driver snapshotted an empty page and vacuously
    # "succeeded"). The /embed/job_app endpoint is the canonical standalone form; navigate
    # straight to it so the fields are present at snapshot time.
    assert (_to_apply_form_url("https://job-boards.greenhouse.io/coinbase/jobs/7736521")
            == "https://job-boards.greenhouse.io/embed/job_app?token=7736521&for=coinbase&gh_jid=7736521")


def test_greenhouse_embed_url_is_idempotent():
    u = "https://job-boards.greenhouse.io/embed/job_app?token=7736521&for=coinbase&gh_jid=7736521"
    assert _to_apply_form_url(u) == u


def test_older_boards_greenhouse_host_becomes_embed():
    # The legacy boards.greenhouse.io host (Chime #2708) carries the id in a gh_jid query too;
    # the path id is canonical and the embed stays on the same host.
    assert (_to_apply_form_url("https://boards.greenhouse.io/chime/jobs/8565199002?gh_jid=8565199002")
            == "https://boards.greenhouse.io/embed/job_app?token=8565199002&for=chime&gh_jid=8565199002")


def test_non_greenhouse_url_unchanged():
    assert _to_apply_form_url("https://example.com/x/jobs/9") == "https://example.com/x/jobs/9"


async def test_fill_application_emits_ops_and_awaits_human():
    fields = [
        FormField(label="First Name", id="first_name", required=True),
        FormField(label="Cover letter", id="cover", kind="textarea", required=True),
    ]
    engine = FakeEngine(snapshots=[PageSnapshot(fields=fields)])
    artifact = {"cover_letter": "Hello there", "screening_answers": []}
    result = await fill_application(engine, url="https://boards.greenhouse.io/a/jobs/1",
                                   artifact=artifact, applicant=_applicant())
    ops = [(c.op, c.args) for c in engine.calls]
    assert ("fill", ("#first_name", "Pat")) in ops
    assert ("fill", ("#cover", "Hello there")) in ops
    assert result.filled is True
    assert result.submitted is False
    assert result.detail == "filled; awaiting human submit"
    assert engine.human_reason == "filled; awaiting human submit"


async def test_fill_application_leaves_teardown_to_engine_on_success():
    # fill_application must NOT close the engine on success: teardown is the engine's own
    # await_human policy. A keep-open assisted browser (PlaywrightEngine launch mode) stays
    # open for the human to review + submit; an engine-agnostic close here would slam it shut
    # and destroy the filled, unsubmitted form. FakeEngine.await_human doesn't close, so a
    # successful fill must leave engine.closed False.
    fields = [FormField(label="First Name", id="first_name")]
    engine = FakeEngine(snapshots=[PageSnapshot(fields=fields)])
    result = await fill_application(engine, url="https://x/apply",
                                   artifact={"cover_letter": "x", "screening_answers": []},
                                   applicant=_applicant())
    assert result.filled is True
    assert engine.closed is False                           # teardown is await_human's job, not ours
    assert [c.op for c in engine.calls][-1] == "await_human"


def _planner_client(fills: list[dict]):
    block = SimpleNamespace(type="tool_use", name="submit_fill_plan", input={"fills": fills})
    resp = SimpleNamespace(content=[block],
                           usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    client = AsyncMock()
    client.messages.create = AsyncMock(return_value=resp)
    return client


async def test_fill_application_escalates_unfilled_and_captcha():
    fields = [FormField(label="Custom dropdown", id="cd", kind="combobox", required=True)]
    engine = FakeEngine(snapshots=[PageSnapshot(fields=fields)], captcha=True)
    client = _planner_client([
        {"key": "#cd", "value": "Maybe", "reasoning": "no basis", "confidence": 0.0,
         "grounded": False}])
    result = await fill_application(engine, url="https://x/apply",
                                   artifact={"cover_letter": "", "screening_answers": []},
                                   applicant=_applicant(), client=client)
    assert "manual fields" in result.detail
    assert "captcha challenge" in result.detail


async def test_planner_fills_eligible_screener_with_reasoning():
    # A skill screener the deterministic pass can't decide reaches the planner, fills, and
    # its reasoning rides into fill_notes. FakeEngine's default select returns ok=True.
    fields = [FormField(label="Years of Python experience", id="yp",
                        kind="combobox", dynamic_options=True, required=True)]
    engine = FakeEngine(snapshots=[PageSnapshot(fields=fields)])
    client = _planner_client([
        {"key": "#yp", "value": "5+ years", "reasoning": "Data Engineer since 2020",
         "confidence": 0.9, "grounded": True}])
    result = await fill_application(engine, url="https://x/apply",
                                   artifact={"cover_letter": "", "screening_answers": []},
                                   applicant=_applicant(), client=client)
    assert ("#yp", "5+ years") in [c.args for c in engine.calls if c.op == "select"]
    assert "manual fields" not in (result.detail or "")
    assert result.fill_notes == [{"field": "Years of Python experience", "value": "5+ years",
                                  "reasoning": "Data Engineer since 2020", "confidence": 0.9}]
    assert result.submitted is False


async def test_planner_ungrounded_field_escalates_and_no_note():
    fields = [FormField(label="Obscure cert you lack", id="oc",
                        kind="combobox", dynamic_options=True, required=True)]
    engine = FakeEngine(snapshots=[PageSnapshot(fields=fields)])
    client = _planner_client([
        {"key": "#oc", "value": "Yes", "reasoning": "no basis", "confidence": 0.1,
         "grounded": False}])
    result = await fill_application(engine, url="https://x/apply",
                                   artifact={"cover_letter": "", "screening_answers": []},
                                   applicant=_applicant(), client=client)
    assert "manual fields" in result.detail
    assert "Obscure cert you lack" in result.detail
    assert result.fill_notes == []
    assert [c.op for c in engine.calls][-1] == "await_human"


async def test_eeo_dropdown_never_reaches_planner():
    # An EEO dropdown is hard-blocked (is_planner_eligible False) -> the planner client is
    # never called -> the field stays unfilled and escalates.
    fields = [FormField(label="Gender", id="g", kind="combobox",
                        dynamic_options=True, required=True)]
    engine = FakeEngine(snapshots=[PageSnapshot(fields=fields)])
    client = _planner_client([])
    result = await fill_application(engine, url="https://x/apply",
                                   artifact={"cover_letter": "", "screening_answers": []},
                                   applicant=_applicant(), client=client)
    client.messages.create.assert_not_called()
    assert "manual fields" in result.detail
    assert result.fill_notes == []


async def test_never_auto_submit_invariant():
    fields = [FormField(label="First Name", id="first_name")]
    engine = FakeEngine(snapshots=[PageSnapshot(fields=fields)])
    result = await fill_application(engine, url="https://x/apply",
                                   artifact={"cover_letter": "x", "screening_answers": []},
                                   applicant=_applicant())
    ops = [c.op for c in engine.calls]
    assert ops[-1] == "await_human"          # terminal op is always the human handoff
    assert "click" not in ops                # no submit-style click emitted
    assert result.submitted is False


async def test_discover_questions_returns_safe_prompts_and_closes():
    fields = [
        FormField(label="First Name", id="first_name"),          # admin -> excluded
        FormField(label="Why do you want to work here?", id="q1"),  # open-ended -> included
    ]
    engine = FakeEngine(snapshots=[PageSnapshot(fields=fields)])
    qs = await discover_questions(engine, url="https://x/apply")
    assert qs == ["Why do you want to work here?"]
    assert engine.closed is True


async def test_select_no_match_fuzzy_rematches_against_available_options():
    from backend.platforms.browser.engine import SelectOutcome

    # plan_fill will choose "No" for this sponsorship combobox; the engine reports no_match
    # with the live options, and the driver must re-select the fuzzy-matched "No, I don't".
    fields = [FormField(label="Do you require visa sponsorship?", id="sp",
                        kind="combobox", dynamic_options=True, required=True)]
    engine = FakeEngine(
        snapshots=[PageSnapshot(fields=fields)],
        select_outcome=SelectOutcome(ok=False,
                                     available_options=["Yes, I do", "No, I don't"]),
    )
    result = await fill_application(engine, url="https://x/apply",
                                   artifact={"cover_letter": "", "screening_answers": []},
                                   applicant=_applicant())
    selects = [c.args for c in engine.calls if c.op == "select"]
    assert selects[0] == ("#sp", "No")                 # first attempt: the planned value
    assert selects[1] == ("#sp", "No, I don't")        # re-match against available_options
    assert "manual fields" not in (result.detail or "")  # gate satisfied, not escalated


async def test_select_never_matching_escalates_to_unfilled():
    from backend.platforms.browser.engine import SelectOutcome

    fields = [FormField(label="Do you require visa sponsorship?", id="sp",
                        kind="combobox", dynamic_options=True, required=True)]
    engine = FakeEngine(
        snapshots=[PageSnapshot(fields=fields)],
        select_outcome=SelectOutcome(ok=False, available_options=["Maybe", "Unsure"]),
    )
    result = await fill_application(engine, url="https://x/apply",
                                   artifact={"cover_letter": "", "screening_answers": []},
                                   applicant=_applicant())
    assert "manual fields" in result.detail
    assert "Do you require visa sponsorship?" in result.detail
    # never submits
    assert [c.op for c in engine.calls][-1] == "await_human"
    assert result.submitted is False
