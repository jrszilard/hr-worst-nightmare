"""Tests for backend.onboarding.extractor — parses Claude's structured output."""

import json

import pytest

from backend.onboarding.extractor import extract_profile
from backend.onboarding.ingest import IngestResult


class _Resp:
    def __init__(self, text):
        self.content = [type("B", (), {"text": text})()]
        self.usage = type("U", (), {"input_tokens": 100, "output_tokens": 200})()


class _Messages:
    def __init__(self, text):
        self._text = text

    async def create(self, **kwargs):
        return _Resp(self._text)


class _Client:
    def __init__(self, text):
        self.messages = _Messages(text)


_CANNED = json.dumps({
    "profile": {
        "name": "Pat", "studio": "Sample Studio", "positioning": "Data and AI consultant.",
        "location": "Vermont", "framing": "a Sample Studio partnership", "tone": "Plain.",
        "selling_points": ["dashboards"],
        "key_differentiators": {"reporting": {"description": "BI", "skills": ["Power BI"]}},
        "applicant": {"first_name": "Pat", "last_name": "Sample", "email": "pat@example.com"},
    },
    "case_studies": [{
        "slug": "demo", "title": "Demo", "client": "Example Co", "category": "Data",
        "lead": "Cut reporting time", "challenge": "Slow reports", "solution": "Built a pipeline",
        "tools": ["Python"], "metrics": ["90% faster"],
    }],
    "needs_review": ["LinkedIn returned a login wall"],
})


@pytest.mark.asyncio
async def test_extract_profile_parses_structured_output():
    ingest = IngestResult(resume_text="Pat Sample, Power BI, Python")
    result = await extract_profile(ingest, client=_Client(_CANNED))
    assert result.profile["name"] == "Pat"
    assert result.profile["location"] == "Vermont"
    assert result.case_studies[0]["slug"] == "demo"
    assert "LinkedIn" in result.needs_review[0]
