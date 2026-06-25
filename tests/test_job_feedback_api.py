"""Tests for feedback-biased job ranking and the feedback endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.db.models import (
    Base, ContractStatus, OpportunityDB, OpportunityKind, SkillPreferenceDB,
)


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


async def _seed_job(session_factory, ext_id, skills, match=0.5):
    async with session_factory() as s:
        s.add(OpportunityDB(
            platform="seed", external_id=ext_id, title=ext_id,
            kind=OpportunityKind.job, match_score=match, skills_required=skills,
            status=ContractStatus.reviewed,
        ))
        await s.commit()


@pytest.mark.asyncio
async def test_priority_unchanged_when_no_weights(client, session_factory):
    await _seed_job(session_factory, "j1", ["SQL"], match=0.5)
    rows = (await client.get("/api/jobs")).json()
    assert rows[0]["job_priority"] == 0.5  # base == match, no bias


@pytest.mark.asyncio
async def test_positive_weight_lifts_priority(client, session_factory):
    await _seed_job(session_factory, "j1", ["SQL"], match=0.5)
    async with session_factory() as s:
        s.add(SkillPreferenceDB(skill="sql", weight=1.0))
        await s.commit()
    rows = (await client.get("/api/jobs")).json()
    # base 0.5 + ALPHA(0.3)*bias(1.0) = 0.8
    assert rows[0]["job_priority"] == pytest.approx(0.8)


@pytest.mark.asyncio
async def test_detail_exposes_feedback_field(client, session_factory):
    await _seed_job(session_factory, "j1", ["SQL"])
    rows = (await client.get("/api/jobs")).json()
    resp = await client.get(f"/api/jobs/{rows[0]['id']}")
    assert resp.status_code == 200
    detail = resp.json()
    assert "feedback" in detail
    assert detail["feedback"] is None


@pytest.mark.asyncio
async def test_like_sets_feedback_and_trains_weights(client, session_factory):
    await _seed_job(session_factory, "j1", ["Microsoft Power BI"], match=0.5)
    rows = (await client.get("/api/jobs")).json()
    jid = rows[0]["id"]
    resp = await client.post(f"/api/jobs/{jid}/feedback", json={"feedback": "liked"})
    assert resp.status_code == 200
    assert resp.json()["feedback"] == "liked"
    # weight learned under the normalized canonical name "power bi"
    async with session_factory() as s:
        from backend.core.preference_store import PreferenceStore
        weights = await PreferenceStore.load_weights(s)
    assert weights.get("power bi") == pytest.approx(0.25)


@pytest.mark.asyncio
async def test_clearing_feedback_reverses_weight(client, session_factory):
    await _seed_job(session_factory, "j1", ["SQL"], match=0.5)
    jid = (await client.get("/api/jobs")).json()[0]["id"]
    await client.post(f"/api/jobs/{jid}/feedback", json={"feedback": "liked"})
    await client.post(f"/api/jobs/{jid}/feedback", json={"feedback": None})
    async with session_factory() as s:
        from backend.core.preference_store import PreferenceStore
        weights = await PreferenceStore.load_weights(s)
    assert weights.get("sql") == pytest.approx(0.0)
    detail = (await client.get(f"/api/jobs/{jid}")).json()
    assert detail["feedback"] is None


@pytest.mark.asyncio
async def test_invalid_feedback_value_rejected(client, session_factory):
    await _seed_job(session_factory, "j1", ["SQL"])
    jid = (await client.get("/api/jobs")).json()[0]["id"]
    resp = await client.post(f"/api/jobs/{jid}/feedback", json={"feedback": "love"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_double_like_trains_weight_only_once(client, session_factory):
    await _seed_job(session_factory, "j1", ["SQL"], match=0.5)
    jid = (await client.get("/api/jobs")).json()[0]["id"]
    await client.post(f"/api/jobs/{jid}/feedback", json={"feedback": "liked"})
    await client.post(f"/api/jobs/{jid}/feedback", json={"feedback": "liked"})
    async with session_factory() as s:
        from backend.core.preference_store import PreferenceStore
        weights = await PreferenceStore.load_weights(s)
    assert weights.get("sql") == pytest.approx(0.25)  # one STEP, not two


@pytest.mark.asyncio
async def test_get_preferences_lists_weights_sorted_desc(client, session_factory):
    async with session_factory() as s:
        s.add(SkillPreferenceDB(skill="sql", weight=0.5))
        s.add(SkillPreferenceDB(skill="sales", weight=-0.25))
        await s.commit()
    resp = await client.get("/api/preferences")
    assert resp.status_code == 200
    weights = resp.json()["weights"]
    assert [w["skill"] for w in weights] == ["sql", "sales"]  # desc by weight
    assert weights[0]["weight"] == 0.5


@pytest.mark.asyncio
async def test_read_and_scan_priority_agree(client, session_factory):
    """The read path (GET /api/jobs) returns the same biased priority the scan
    path computed for the same job + weights — guards against formula drift."""
    from backend.core.job_fit import job_fit_score
    from backend.core.job_screening import screen_and_store
    from backend.core.matching import calculate_match_score, normalize_skill
    from backend.core.preferences import biased_priority, preference_bias
    from backend.core.scoring import calculate_job_priority
    from backend.portfolio.profile_loader import load_profile

    profile = load_profile()
    async with session_factory() as s:
        s.add(SkillPreferenceDB(skill="python", weight=0.5))
        await s.commit()

    spec = {"platform": "seed", "external_id": "agree-1", "title": "PyAgree",
            "url": "u", "description": "x", "skills_required": ["Python"],
            "client_questions": None, "submission_channel": "auto",
            "platform_meta": None, "description_fit": None}
    async with session_factory() as s:
        await screen_and_store(s, [spec], profile, threshold=0.15)
        await s.commit()

    # Recompute the scan-path priority independently with the same public helpers.
    # Board specs carry no AI description_fit, so the scan path fills in a
    # deterministic job_fit_score — mirror that here.
    match = calculate_match_score(["Python"], profile)
    fit = job_fit_score("PyAgree", "x", ["Python"], profile)
    scan_priority = biased_priority(
        calculate_job_priority(match.match_score, fit),
        preference_bias({"python": 0.5}, [normalize_skill("Python")]),
    )

    rows = (await client.get("/api/jobs")).json()
    row = next(r for r in rows if r["title"] == "PyAgree")
    assert row["job_priority"] == pytest.approx(scan_priority)
