"""End-to-end onboarding run with a fake Claude client (no network)."""

import json

import pytest

from backend.core.profile_context import ProfileContext
from backend.onboarding import run_onboarding
from backend.portfolio.profile_loader import load_profile


class _Resp:
    def __init__(self, text):
        self.content = [type("B", (), {"text": text})()]
        self.usage = type("U", (), {"input_tokens": 1, "output_tokens": 1})()


class _Client:
    def __init__(self, text):
        self.messages = type("M", (), {"create": lambda self, **k: _async(_Resp(text))})()


async def _async(v):
    return v


_CANNED = json.dumps({
    "profile": {"name": "Pat", "studio": "Sample Studio", "positioning": "C.",
                "location": "Vermont", "framing": "", "tone": "", "selling_points": [],
                "key_differentiators": {}, "applicant": {"first_name": "Pat", "last_name": "Sample"}},
    "case_studies": [], "needs_review": [],
})


@pytest.mark.asyncio
async def test_run_onboarding_writes_profile(tmp_path):
    ctx = ProfileContext(root=tmp_path)
    ctx.inputs_dir.mkdir(parents=True)
    (ctx.inputs_dir / "links.txt").write_text("", encoding="utf-8")

    await run_onboarding(ctx, client=_Client(_CANNED))

    assert load_profile(ctx.profile_yaml).name == "Pat"
    assert ctx.onboarding_report.exists()
