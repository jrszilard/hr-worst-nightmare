"""GET/PUT /api/profile against a temp PROFILE_DIR."""

import httpx
import pytest

from backend.config import settings
from backend.main import app


@pytest.mark.asyncio
async def test_get_then_put_profile_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PROFILE_DIR", str(tmp_path))
    (tmp_path / "profile.yaml").write_text("name: Pat\nstudio: Sample Studio\n", encoding="utf-8")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        got = await ac.get("/api/profile")
        assert got.status_code == 200
        assert "name: Pat" in got.json()["yaml"]

        new_yaml = "name: Pat\nstudio: Renamed Studio\n"
        put = await ac.put("/api/profile", json={"yaml": new_yaml})
        assert put.status_code == 200

        assert "Renamed Studio" in (tmp_path / "profile.yaml").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_put_rejects_invalid_yaml(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PROFILE_DIR", str(tmp_path))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.put("/api/profile", json={"yaml": "name: [unclosed"})
        assert resp.status_code == 400
