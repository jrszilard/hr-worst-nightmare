"""Tests for finalist promotion + listing."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.db.models import Base, OpportunityDB, OpportunityKind


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


@pytest.fixture()
async def seeded(session_factory):
    async with session_factory() as s:
        job = OpportunityDB(platform="seed", external_id="j1", title="A Job",
                            kind=OpportunityKind.job, match_score=0.6, description_fit=0.9)
        con = OpportunityDB(platform="upwork", external_id="c1", title="A Contract",
                            kind=OpportunityKind.contract, match_score=0.8,
                            roi_score=0.5, connects_cost=10)
        s.add_all([job, con]); await s.commit()
        return {"job": job.id, "con": con.id}


async def test_promote_and_list_finalist(client: AsyncClient, seeded):
    r = await client.post(f"/api/opportunities/{seeded['job']}/finalist", json={"is_finalist": True})
    assert r.status_code == 200 and r.json()["is_finalist"] is True
    items = (await client.get("/api/finalists")).json()
    assert [it["id"] for it in items] == [seeded["job"]]


async def test_demote_removes_from_list(client: AsyncClient, seeded):
    await client.post(f"/api/opportunities/{seeded['con']}/finalist", json={"is_finalist": True})
    await client.post(f"/api/opportunities/{seeded['con']}/finalist", json={"is_finalist": False})
    items = (await client.get("/api/finalists")).json()
    assert items == []


async def test_finalist_item_includes_kind_and_connects(client: AsyncClient, seeded):
    await client.post(f"/api/opportunities/{seeded['con']}/finalist", json={"is_finalist": True})
    item = (await client.get("/api/finalists")).json()[0]
    assert item["kind"] == "contract"
    assert item["connects_cost"] == 10


async def test_plan_endpoint_is_dry_run(client: AsyncClient, seeded, session_factory):
    await client.post(f"/api/opportunities/{seeded['con']}/finalist", json={"is_finalist": True})
    body = (await client.post("/api/finalists/plan", json={"per_run_max_apps": None})).json()
    assert len(body["will_process"]) == 1
    assert body["totals"]["connects"] == 10
    # dry run: no spend events written
    from backend.db.models import SpendEventDB
    from sqlalchemy import select
    async with session_factory() as s:
        rows = (await s.execute(select(SpendEventDB))).scalars().all()
    assert rows == []


async def test_apply_endpoint_records_spend(client: AsyncClient, seeded, session_factory, monkeypatch):
    # Avoid real Claude calls: stub the generator the endpoint uses.
    import backend.api.finalists as fin
    async def fake_gen(opp):
        return {"cover_letter": "c", "screening_answers": None, "review_flags": [],
                "sections": None, "bid_amount": None, "estimated_duration": None}
    monkeypatch.setattr(fin, "_make_generate_fn", lambda session: fake_gen)

    await client.post(f"/api/opportunities/{seeded['con']}/finalist", json={"is_finalist": True})
    body = (await client.post("/api/finalists/apply", json={"per_run_max_apps": None})).json()
    assert len(body["processed"]) == 1
    from backend.db.models import SpendEventDB
    from sqlalchemy import select
    async with session_factory() as s:
        rows = (await s.execute(select(SpendEventDB))).scalars().all()
    assert any(r.kind.value == "connects" and r.amount == 10 for r in rows)
    assert any(r.kind.value == "generation" for r in rows)
