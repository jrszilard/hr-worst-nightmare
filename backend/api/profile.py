"""Read/update the raw profile.yaml for the onboarding review step."""

from __future__ import annotations

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.profile_context import get_profile_context
from backend.portfolio.profile_loader import clear_profile_cache

router = APIRouter(tags=["profile"])


class ProfileYamlBody(BaseModel):
    yaml: str


@router.get("/api/profile")
async def get_profile_yaml() -> dict:
    ctx = get_profile_context()
    if not ctx.profile_yaml.exists():
        raise HTTPException(status_code=404, detail="No profile yet — run ./onboard.sh")
    return {"yaml": ctx.profile_yaml.read_text(encoding="utf-8")}


@router.put("/api/profile")
async def put_profile_yaml(body: ProfileYamlBody) -> dict:
    try:
        data = yaml.safe_load(body.yaml)
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Profile must be a YAML mapping")

    ctx = get_profile_context()
    ctx.root.mkdir(parents=True, exist_ok=True)
    ctx.profile_yaml.write_text(body.yaml, encoding="utf-8")
    clear_profile_cache()
    return {"ok": True}
