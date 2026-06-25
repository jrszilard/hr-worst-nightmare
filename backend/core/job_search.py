"""JSearch discovery orchestrator. Parallels board_scan.scan_job_boards.

`fetch(query, *, location, remote_only, page, api_key)` is injected so tests use fixtures
and production uses backend.platforms.jsearch.client.fetch_jsearch. No Claude calls.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Awaitable, Callable

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.core.job_screening import screen_and_store
from backend.core.profile_context import get_profile_context
from backend.platforms.jsearch.mapper import map_jsearch_jobs
from backend.portfolio.profile_loader import load_profile

logger = logging.getLogger(__name__)

FetchFn = Callable[..., Awaitable[dict]]

# mtime-keyed cache (same pattern as board_scan.load_board_config).
_SEARCH_CONFIG_CACHE: dict[str, tuple[float, dict]] = {}


def _reset_search_config_cache() -> None:
    _SEARCH_CONFIG_CACHE.clear()


def load_search_config() -> dict:
    config_path = get_profile_context().job_search_yaml
    if not config_path.exists():
        return {}
    key = str(config_path)
    mtime = config_path.stat().st_mtime
    cached = _SEARCH_CONFIG_CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    _SEARCH_CONFIG_CACHE[key] = (mtime, data)
    return data


def _vocab(profile) -> list[str]:
    return [s.name for s in profile.core_skills + profile.adjacent_skills]


async def search_jobs(session: AsyncSession, *, config: dict, fetch: FetchFn,
                      threshold: float) -> dict:
    profile = load_profile()
    vocab = _vocab(profile)
    location = config.get("location", "United States")
    remote_only = bool(config.get("remote_only", True))
    pages = int(config.get("pages_per_query", 1))

    specs: list[dict] = []
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    for query in config.get("queries", []) or []:
        for page in range(1, pages + 1):
            try:
                payload = await fetch(query, location=location, remote_only=remote_only,
                                      page=page, api_key=settings.JSEARCH_API_KEY)
            except Exception as exc:  # noqa: BLE001 — one bad query must not abort the rest
                logger.warning("jsearch query %r page %s failed: %s", query, page, exc)
                errors.append(f"{query} p{page}: {exc}")
                continue
            for spec in map_jsearch_jobs(payload, vocab=vocab):
                key = (spec["platform"], spec["external_id"])
                if key in seen:
                    continue
                seen.add(key)
                specs.append(spec)

    summary = await screen_and_store(session, specs, profile, threshold,
                                     remote_only=remote_only)
    summary["errors"] = errors
    return summary
