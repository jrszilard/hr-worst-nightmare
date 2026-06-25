"""Scan configured Greenhouse/Lever boards and ingest postings as job opportunities.

`fetch(vendor, slug)` returns the raw JSON for one board; it is injected so tests use
fixtures and production uses httpx. One board's failure is logged and skipped — others
still ingest. No Claude calls.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Awaitable, Callable

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.job_screening import screen_and_store
from backend.core.profile_context import get_profile_context
from backend.platforms.ashby.board_client import map_ashby_jobs
from backend.platforms.greenhouse.board_client import map_greenhouse_jobs
from backend.platforms.lever.board_client import map_lever_jobs
from backend.portfolio.profile_loader import load_profile

logger = logging.getLogger(__name__)

FetchFn = Callable[[str, str], Awaitable]


def _norm_text(value: str | None) -> str:
    return " ".join((value or "").lower().split())


def _term_matches(haystack: str, needle: str) -> bool:
    term = _norm_text(needle)
    if not term:
        return False
    # Short terms like "AI", "BI", and "SQL" must match as standalone words;
    # substring matching would keep unrelated text such as "paid", "billing", etc.
    if len(term) <= 3 and term.replace(" ", "").isalnum():
        return re.search(rf"\b{re.escape(term)}\b", haystack) is not None
    return term in haystack


def _count_matches(haystack: str, needles: list[str]) -> int:
    if not needles:
        return 0
    return sum(1 for n in needles if _term_matches(haystack, n))


def _contains_any(haystack: str, needles: list[str]) -> bool:
    return _count_matches(haystack, needles) > 0


_US_STATE_ABBRS = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}
_US_STATE_NAMES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming",
}
_US_CITY_TERMS = {
    "san francisco", "new york", "seattle", "mountain view", "bellevue",
    "washington, dc", "st. louis", "boston", "austin", "chicago", "denver",
    "los angeles", "palo alto", "atlanta", "miami", "dallas", "phoenix",
}
_AMBIGUOUS_STATE_ABBRS = {"IN", "ME", "OR"}


def _has_state_abbr(raw: str, abbr: str) -> bool:
    upper = raw.upper()
    if abbr in _AMBIGUOUS_STATE_ABBRS:
        # Avoid treating phrases like "Dublin OR London" as Oregon. Ambiguous state
        # abbreviations must look like address tokens (", OR", "| IN", etc.) AND be
        # uppercase in the source — so the lowercase conjunction "or"/"in"/"me"
        # (e.g. "BC, or NS Only") is not read as a state. Match raw, not upper.
        return re.search(rf"(?:^|[,;|•()/.-]\s*){abbr}(?:$|[\s,;|•()/.-])", raw) is not None
    return re.search(rf"(?:^|[\s,;|•()/.-]){abbr}(?:$|[\s,;|•()/.-])", upper) is not None


def is_remote_location(location: str | None) -> bool:
    """Best-effort remote-work detector for board location strings."""
    lower = _norm_text(location)
    return bool(re.search(r"\b(?:remote|remote-friendly|work from home|distributed)\b", lower))


def work_mode_from_location(location: str | None) -> str:
    return "remote" if is_remote_location(location) else "location"


def is_us_location(location: str | None) -> bool:
    """Best-effort US location gate for company-board location strings."""
    raw = (location or "").strip()
    if not raw:
        return False
    lower = _norm_text(raw)
    if re.search(r"\b(?:united states|usa|u\.s\.|u\.s\.?a|us)\b", lower):
        return True
    if any(re.search(rf"\b{re.escape(name)}\b", lower) for name in _US_STATE_NAMES):
        return True
    if any(term in lower for term in _US_CITY_TERMS):
        return True
    # Match delimited state abbreviations (", CA", "| NY", " DC").
    return any(_has_state_abbr(raw, abbr) for abbr in _US_STATE_ABBRS)


def _location(spec: dict) -> str | None:
    meta = spec.get("platform_meta") or {}
    if isinstance(meta, dict):
        return meta.get("location")
    return None


def _matches_criteria(spec: dict, criteria: dict | None) -> bool:
    """Return True when a posting matches the configured job-search criteria.

    Criteria are intentionally lightweight and config-driven. Board APIs are company-board
    endpoints, not global search, so this filter prevents broad watchlists from storing
    obvious non-fit roles before the normal skill/preference scorer runs.
    """
    if not criteria:
        return True

    location = _location(spec)
    if criteria.get("us_only") and not is_us_location(location):
        return False
    if _contains_any(_norm_text(location), criteria.get("exclude_location_any") or []):
        return False

    title = _norm_text(spec.get("title"))
    description = _norm_text(spec.get("description"))
    skills = _norm_text(" ".join(spec.get("skills_required") or []))
    full_text = " ".join(p for p in [title, description, skills] if p)

    if _contains_any(title, criteria.get("exclude_title_any") or []):
        return False
    if _contains_any(full_text, criteria.get("exclude_text_any") or []):
        return False

    title_terms = criteria.get("title_include_any") or []
    text_terms = criteria.get("text_include_any") or []
    skill_terms = criteria.get("skills_include_any") or []
    if not title_terms and not text_terms and not skill_terms:
        return True

    title_match = _contains_any(title, title_terms)
    text_match_count = _count_matches(description, text_terms)
    skill_match_count = _count_matches(skills, skill_terms)
    text_min = int(criteria.get("text_include_min", 1))
    skill_min = int(criteria.get("skills_include_min", 1))

    return (
        title_match
        or (text_terms and text_match_count >= text_min)
        or (skill_terms and skill_match_count >= skill_min)
    )


def _apply_criteria(specs: list[dict], criteria: dict | None) -> tuple[list[dict], int]:
    kept = [spec for spec in specs if _matches_criteria(spec, criteria)]
    return kept, len(specs) - len(kept)


# Parsing job_boards.yaml is pure disk I/O of a static file, but the jobs list
# endpoint calls this ~2x per job row. Memoize the parse keyed on (path, mtime) so
# repeated calls within a request are free while edits to the file are still picked
# up on the next call. Read-only: callers never mutate the returned dict.
_BOARD_CONFIG_CACHE: dict[str, tuple[float, dict]] = {}


def _reset_board_config_cache() -> None:
    """Clear the memoized config (test isolation)."""
    _BOARD_CONFIG_CACHE.clear()


def load_board_config() -> dict:
    config_path = get_profile_context().job_boards_yaml
    if not config_path.exists():
        return {}
    key = str(config_path)
    mtime = config_path.stat().st_mtime
    cached = _BOARD_CONFIG_CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    _BOARD_CONFIG_CACHE[key] = (mtime, data)
    return data


def _vocab(profile) -> list[str]:
    return [s.name for s in profile.core_skills + profile.adjacent_skills]


async def scan_job_boards(session: AsyncSession, *, config: dict, fetch: FetchFn,
                          threshold: float) -> dict:
    profile = load_profile()
    vocab = _vocab(profile)
    specs: list[dict] = []
    errors: list[str] = []

    for slug in config.get("greenhouse", []) or []:
        try:
            payload = await fetch("greenhouse", slug)
            specs.extend(map_greenhouse_jobs(slug, payload, vocab=vocab))
        except Exception as exc:  # noqa: BLE001 — skip a bad board, keep the rest
            logger.warning("greenhouse:%s scan failed: %s", slug, exc)
            errors.append(f"greenhouse:{slug}: {exc}")

    for slug in config.get("lever", []) or []:
        try:
            payload = await fetch("lever", slug)
            specs.extend(map_lever_jobs(slug, payload, vocab=vocab))
        except Exception as exc:  # noqa: BLE001
            logger.warning("lever:%s scan failed: %s", slug, exc)
            errors.append(f"lever:{slug}: {exc}")

    for slug in config.get("ashby", []) or []:
        try:
            payload = await fetch("ashby", slug)
            specs.extend(map_ashby_jobs(slug, payload, vocab=vocab))
        except Exception as exc:  # noqa: BLE001
            logger.warning("ashby:%s scan failed: %s", slug, exc)
            errors.append(f"ashby:{slug}: {exc}")

    specs, criteria_filtered = _apply_criteria(
        specs, config.get("criteria") or config.get("job_criteria")
    )

    summary = await screen_and_store(session, specs, profile, threshold)
    summary["errors"] = errors
    summary["criteria_filtered"] = criteria_filtered
    return summary
