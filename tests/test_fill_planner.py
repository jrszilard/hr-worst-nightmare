"""Tests for the hybrid LLM fill-planner."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.ai.fill_planner import (
    PlannedField, _fields_payload, _parse_plan, _profile_block, plan_dropdown_fields,
)
from backend.core.models import ApplicantInfo, Education, WorkExperience
from backend.platforms.form_fill import FormField


def _applicant() -> ApplicantInfo:
    return ApplicantInfo(
        first_name="Pat", last_name="Sample", email="pat@example.com", phone="555-0100",
        country="United States", work_authorization="US citizen",
        skills=["Python", "SQL", "Power BI"],
        work_history=[WorkExperience(title="Data Engineer", company="Acme",
                                     start="2020-01", current=True,
                                     description="Built Python ETL and BI dashboards.")],
        education=[Education(school="Pitt", degree="B.S.", field="Information Science",
                             start="2011", end="2015")],
    )


def test_fields_payload_includes_options_when_known_and_none_when_not():
    fields = [
        FormField(label="Years of Python", id="yp", kind="combobox", dynamic_options=True,
                  required=True),
        FormField(label="Education level", id="ed", kind="combobox",
                  options=["High school", "Bachelor's", "Master's"]),
    ]
    payload = _fields_payload(fields)
    assert '"key": "#yp"' in payload
    assert '"options": null' in payload          # React-Select: options deferred
    assert "Bachelor's" in payload               # native select: options carried


def test_profile_block_names_real_facts_only():
    block = _profile_block(_applicant())
    assert "Data Engineer at Acme" in block
    assert "Python" in block
    assert "B.S." in block
    assert "US citizen" in block


def test_parse_plan_keeps_grounded_known_key():
    fields = [FormField(label="Years of Python", id="yp", kind="combobox", dynamic_options=True)]
    out = _parse_plan({"fills": [
        {"key": "#yp", "value": "5+", "reasoning": "10y Python in work history",
         "confidence": 0.9, "grounded": True}]}, fields)
    assert out == [PlannedField(key="#yp", value="5+",
                                reasoning="10y Python in work history",
                                confidence=0.9, grounded=True)]


def test_parse_plan_drops_unknown_and_empty():
    fields = [FormField(label="Years of Python", id="yp", kind="combobox")]
    out = _parse_plan({"fills": [
        {"key": "#ghost", "value": "x", "reasoning": "", "confidence": 1.0, "grounded": True},
        {"key": "#yp", "value": "", "reasoning": "", "confidence": 1.0, "grounded": True},
    ]}, fields)
    assert out == []                              # invented key dropped; empty value dropped


def test_parse_plan_snaps_known_option_or_escalates():
    fields = [FormField(label="Education level", id="ed", kind="combobox",
                        options=["High school", "Bachelor's degree", "Master's degree"])]
    # paraphrase snaps to the exact on-page option
    snapped = _parse_plan({"fills": [
        {"key": "#ed", "value": "Bachelor's", "reasoning": "B.S. from Pitt",
         "confidence": 0.95, "grounded": True}]}, fields)
    assert snapped[0].value == "Bachelor's degree" and snapped[0].grounded is True
    # a value that matches no known option is forced ungrounded (escalates)
    miss = _parse_plan({"fills": [
        {"key": "#ed", "value": "PhD", "reasoning": "", "confidence": 0.9, "grounded": True}]},
        fields)
    assert miss[0].grounded is False


def _tool_response(fills: list[dict]):
    block = SimpleNamespace(type="tool_use", name="submit_fill_plan", input={"fills": fills})
    return SimpleNamespace(content=[block],
                           usage=SimpleNamespace(input_tokens=10, output_tokens=5))


def _planner_client(fills: list[dict]) -> AsyncMock:
    client = AsyncMock()
    client.messages.create = AsyncMock(return_value=_tool_response(fills))
    return client


async def test_plan_dropdown_fields_returns_grounded_answer():
    fields = [FormField(label="Years of Python", id="yp", kind="combobox",
                        dynamic_options=True, required=True)]
    client = _planner_client([
        {"key": "#yp", "value": "5+ years", "reasoning": "Data Engineer at Acme since 2020",
         "confidence": 0.9, "grounded": True}])
    out = await plan_dropdown_fields(fields, _applicant(),
                                     {"job_title": "BI Engineer", "company": "DoorDash"},
                                     client=client)
    assert len(out) == 1
    assert out[0].key == "#yp" and out[0].value == "5+ years" and out[0].grounded is True
    client.messages.create.assert_awaited_once()
    # forced tool-use was requested
    kwargs = client.messages.create.await_args.kwargs
    assert kwargs["tool_choice"] == {"type": "tool", "name": "submit_fill_plan"}


async def test_plan_dropdown_fields_empty_skips_client():
    client = AsyncMock()
    out = await plan_dropdown_fields([], _applicant(), {}, client=client)
    assert out == []
    client.messages.create.assert_not_called()
