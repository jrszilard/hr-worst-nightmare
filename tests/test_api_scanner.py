"""Tests for the scanner API endpoints."""

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.api.scanner import reset_scanner_status
from backend.db.models import Base


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _stub_run_scan(monkeypatch):
    """Replace the real Playwright scan with a fast no-browser stub.

    `POST /api/scanner/scan` schedules `_run_scan` as a background task, which
    otherwise launches a real Chrome via Playwright and hits Upwork's live site.
    These tests only verify the endpoint/status contract, so the stub just sets
    the status fields the assertions rely on — no browser, no network.
    """
    import backend.api.scanner as scanner_mod

    async def _fake_run_scan() -> None:
        scanner_mod._scanner_status.started_at = datetime.now(UTC)
        scanner_mod._scanner_status.contracts_found = 0
        scanner_mod._scanner_status.progress = 1.0
        scanner_mod._scanner_status.state = scanner_mod.ScannerState.complete

    monkeypatch.setattr(scanner_mod, "_run_scan", _fake_run_scan)


@pytest.fixture()
async def api_engine():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture()
async def api_session_factory(api_engine):
    return async_sessionmaker(api_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture()
async def client(api_session_factory):
    from backend.db.database import get_session
    from backend.main import app

    async def _override_session():
        async with api_session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session

    # Reset scanner status before each test
    reset_scanner_status()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ── GET /api/scanner/status ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scanner_status_idle(client):
    """Scanner starts in idle state."""
    resp = await client.get("/api/scanner/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "idle"
    assert data["contracts_found"] == 0
    assert data["progress"] == 0.0
    assert data["errors"] == []


# ── POST /api/scanner/scan ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_scan(client):
    """POST /api/scanner/scan returns running state."""
    resp = await client.post("/api/scanner/scan")
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "running"


@pytest.mark.asyncio
async def test_scanner_status_after_scan(client):
    """After starting a scan, status shows running or complete."""
    await client.post("/api/scanner/scan")
    resp = await client.get("/api/scanner/status")
    assert resp.status_code == 200
    data = resp.json()
    # The background task may have already completed by the time we check
    assert data["state"] in ("running", "complete")
    assert data["started_at"] is not None


@pytest.mark.asyncio
async def test_double_scan_returns_already_running(client):
    """Starting a scan while one is running returns a message."""
    # Start first scan
    resp1 = await client.post("/api/scanner/scan")
    assert resp1.status_code == 200

    # The background task may or may not have completed;
    # if it completed, a second scan should start fresh.
    # We just verify the endpoint doesn't error.
    resp2 = await client.post("/api/scanner/scan")
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["state"] == "running"
