from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import backend.api.finalists as fin
from backend.ai.application_generator import ScreeningAnswer
from backend.core.enums import OpportunityKind, SubmissionChannel
from backend.core.platform import SubmitResult
from backend.db.models import Base, JobApplicationDB, OpportunityDB


@pytest.fixture()
async def api_engine():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def session_factory(api_engine):
    return async_sessionmaker(api_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture()
async def client(session_factory):
    from httpx import ASGITransport, AsyncClient
    from backend.db.database import get_session
    from backend.main import app

    async def _override():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_run_apply_uses_injected_submitter(monkeypatch, client, session_factory):
    async with session_factory() as s:
        s.add(OpportunityDB(platform="greenhouse", external_id="g9", title="T",
                            kind=OpportunityKind.job, is_finalist=True, match_score=0.9,
                            description_fit=0.9, connects_cost=0,
                            submission_channel=SubmissionChannel.auto))
        await s.commit()

    # Real _make_generate_fn is sync and returns an async closure; match that shape.
    def fake_gen_fn(session):
        async def _g(opp):
            return {"cover_letter": "hi", "screening_answers": None, "review_flags": [],
                    "cost_usd": 0.01}
        return _g

    async def fake_submit(opp, artifact):
        return SubmitResult(filled=True, submitted=True, detail="submitted")

    monkeypatch.setattr(fin, "_make_generate_fn", fake_gen_fn)
    monkeypatch.setattr(fin, "_make_submit_fn", lambda: fake_submit)

    resp = await client.post("/api/finalists/apply", json={})
    assert resp.status_code == 200

    async with session_factory() as s:
        app_row = (await s.execute(
            select(JobApplicationDB).join(OpportunityDB).where(OpportunityDB.external_id == "g9"))
        ).scalar_one()
        assert app_row.applied is True


@pytest.mark.asyncio
async def test_run_apply_reports_awaiting_submit(monkeypatch, client, session_factory):
    async with session_factory() as s:
        s.add(OpportunityDB(platform="greenhouse", external_id="g_aw", title="T",
                            kind=OpportunityKind.job, is_finalist=True, match_score=0.9,
                            description_fit=0.9, connects_cost=0,
                            submission_channel=SubmissionChannel.browser))
        await s.commit()

    def fake_gen_fn(session):
        async def _g(opp):
            return {"cover_letter": "hi", "screening_answers": None, "review_flags": [],
                    "cost_usd": 0.01}
        return _g

    async def fake_submit(opp, artifact):
        return SubmitResult(filled=True, submitted=False, detail="filled; awaiting human submit")

    monkeypatch.setattr(fin, "_make_generate_fn", fake_gen_fn)
    monkeypatch.setattr(fin, "_make_submit_fn", lambda: fake_submit)

    resp = await client.post("/api/finalists/apply", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert any("awaiting" in a["detail"] for a in body["awaiting_submit"])
    assert body["processed"]  # still processed (generated)


@pytest.mark.asyncio
async def test_make_generate_fn_prefetches_browser_form_questions(monkeypatch, session_factory):
    async with session_factory() as s:
        row = OpportunityDB(platform="greenhouse", external_id="g_q", title="T",
                            url="https://example.test/job", kind=OpportunityKind.job,
                            is_finalist=True, match_score=0.9, description_fit=0.9,
                            connects_cost=0, submission_channel=SubmissionChannel.browser,
                            client_questions=["Existing question?"])
        s.add(row)
        await s.commit()
        await s.refresh(row)

        async def fake_discover(opp):
            assert opp.url == "https://example.test/job"
            return ["Why Anthropic?", "Existing question?"]

        captured = {}

        async def fake_generate_application(**kwargs):
            opp = kwargs["opportunity"]
            captured["questions"] = list(opp.client_questions or [])
            return SimpleNamespace(
                cover_letter="hi",
                screening_answers=[ScreeningAnswer(question="Why Anthropic?", answer="Mission.")],
                review_flags=[],
                sections=None,
                bid_amount=None,
                estimated_duration=None,
            )

        monkeypatch.setattr(fin, "_discover_client_questions", fake_discover)
        monkeypatch.setattr(fin, "generate_application", fake_generate_application)

        gen = fin._make_generate_fn(s)
        artifact = await gen(row)

        assert captured["questions"] == ["Existing question?", "Why Anthropic?"]
        assert row.client_questions == ["Existing question?", "Why Anthropic?"]
        assert artifact["screening_answers"] == [
            {"question": "Why Anthropic?", "answer": "Mission."},
        ]
