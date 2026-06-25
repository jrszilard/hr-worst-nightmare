import pytest
from httpx import ASGITransport, AsyncClient

import backend.api.scanner as scanner_mod
from backend.main import app


@pytest.mark.asyncio
async def test_job_scan_endpoint_runs(monkeypatch, db_session):
    async def fake_run_job_scan():
        scanner_mod._job_scanner_status.state = scanner_mod.ScannerState.complete
        scanner_mod._job_scanner_status.contracts_found = 3

    monkeypatch.setattr(scanner_mod, "_run_job_scan", fake_run_job_scan)
    scanner_mod.reset_job_scanner_status()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        start = await ac.post("/api/scanner/jobs")
        assert start.status_code == 200
        status = await ac.get("/api/scanner/jobs/status")
    assert status.status_code == 200
    body = status.json()
    assert body["state"] in ("running", "complete")
