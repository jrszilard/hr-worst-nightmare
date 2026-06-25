"""Tests for the LLM critic rewrite pass (backend.ai.writing.critic)."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.ai.writing.critic import critique_and_rewrite, CriticReport


def _mock_client(text: str) -> AsyncMock:
    response = SimpleNamespace(content=[SimpleNamespace(text=text)])
    client = AsyncMock()
    client.messages.create = AsyncMock(return_value=response)
    return client


async def test_critic_returns_rewritten_text():
    payload = json.dumps({
        "rewritten_text": "I build clean dashboards, fast.",
        "changed": True,
        "notes": "removed filler",
    })
    client = _mock_client(payload)
    out, report = await critique_and_rewrite("I will leverage robust dashboards.", client=client)
    assert out == "I build clean dashboards, fast."
    assert isinstance(report, CriticReport)
    assert report.available and report.rewritten


async def test_critic_passes_style_rules_to_model():
    payload = json.dumps({"rewritten_text": "ok", "changed": False, "notes": ""})
    client = _mock_client(payload)
    await critique_and_rewrite("draft text", client=client)
    sent = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "em-dash" in sent.lower() or "em dash" in sent.lower()


async def test_critic_falls_back_on_bad_json():
    client = _mock_client("not json at all")
    out, report = await critique_and_rewrite("original draft", client=client)
    assert out == "original draft"          # original preserved
    assert not report.available


async def test_critic_falls_back_on_exception():
    client = AsyncMock()
    client.messages.create = AsyncMock(side_effect=RuntimeError("boom"))
    out, report = await critique_and_rewrite("original draft", client=client)
    assert out == "original draft"
    assert not report.available
