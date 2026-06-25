# tests/test_scanner_search_api.py
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.db.models import Base


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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_search_endpoint_returns_running_status(client, monkeypatch):
    import backend.api.scanner as scanner
    scanner.reset_job_search_status()

    async def fake_run():
        return None

    monkeypatch.setattr(scanner, "_run_job_search", fake_run)
    r = await client.post("/api/scanner/search")
    assert r.status_code == 200
    assert r.json()["state"] in ("running", "idle", "complete")


@pytest.mark.asyncio
async def test_search_status_endpoint(client):
    import backend.api.scanner as scanner
    scanner.reset_job_search_status()

    r = await client.get("/api/scanner/search/status")
    assert r.status_code == 200
    body = r.json()
    assert "state" in body
    assert body["state"] in ("idle", "running", "complete", "error")
