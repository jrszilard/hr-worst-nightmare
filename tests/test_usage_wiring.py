from types import SimpleNamespace

import pytest

from backend.ai.usage import collect_usage


class _FakeMessages:
    async def create(self, **kwargs):
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="hello")],
            usage=SimpleNamespace(input_tokens=200, output_tokens=80),
        )


class _FakeClient:
    def __init__(self):
        self.messages = _FakeMessages()


@pytest.mark.asyncio
async def test_generate_text_records_usage():
    from backend.ai.application_generator import _generate_text
    from backend.core.models import LoadedProfile

    _profile = LoadedProfile(
        name="J", studio="L", positioning="", hourly_rate_range=[1, 2],
        tone="", selling_points=[], key_differentiators={},
        core_skills=[], adjacent_skills=[], all_skills=[],
    )
    with collect_usage() as acc:
        await _generate_text("cover_letter.txt", _FakeClient(), _profile,
                             name="J", studio="L", positioning="p", selling_points="s",
                             applicant_facts="f",
                             case_studies="c", contract_title="t", contract_description="d",
                             contract_skills="x")
    assert acc.input_tokens == 200
    assert acc.output_tokens == 80


class _FakeCriticMessages:
    async def create(self, **kwargs):
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text='{"rewritten_text":"hi","changed":true,"notes":"n"}')],
            usage=SimpleNamespace(input_tokens=30, output_tokens=12),
        )


class _FakeCriticClient:
    def __init__(self):
        self.messages = _FakeCriticMessages()


@pytest.mark.asyncio
async def test_critic_records_usage():
    from backend.ai.writing.critic import critique_and_rewrite

    with collect_usage() as acc:
        await critique_and_rewrite("some draft", client=_FakeCriticClient())
    assert acc.input_tokens == 30
    assert acc.output_tokens == 12


class _FakeAnalyzerMessages:
    async def create(self, **kwargs):
        return SimpleNamespace(
            content=[SimpleNamespace(
                type="text",
                text='{"extracted_skills":["python"],"client_problem":"p","implicit_needs":[]}',
            )],
            usage=SimpleNamespace(input_tokens=150, output_tokens=45),
        )


class _FakeAnalyzerClient:
    def __init__(self):
        self.messages = _FakeAnalyzerMessages()


@pytest.mark.asyncio
async def test_analyze_contract_records_usage():
    from backend.ai.contract_analyzer import analyze_contract

    with collect_usage() as acc:
        await analyze_contract("title", "description", ["python"],
                               client=_FakeAnalyzerClient())
    assert acc.input_tokens == 150
    assert acc.output_tokens == 45
