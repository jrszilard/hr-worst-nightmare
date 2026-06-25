"""JSearch (RapidAPI Google-for-Jobs) HTTP client. Network calls live here only."""

from __future__ import annotations

import httpx

_BASE = "https://jsearch.p.rapidapi.com"
_HOST = "jsearch.p.rapidapi.com"


def build_search_request(*, query: str, location: str, remote_only: bool,
                         page: int, api_key: str) -> tuple[str, dict, dict]:
    """Return (url, headers, params) for a JSearch /search call."""
    full_query = f"{query} in {location}" if location else query
    headers = {"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": _HOST}
    params = {
        "query": full_query,
        "page": str(page),
        "num_pages": "1",
        "remote_jobs_only": "true" if remote_only else "false",
    }
    return f"{_BASE}/search", headers, params


async def fetch_jsearch(query: str, *, location: str, remote_only: bool,
                        page: int, api_key: str) -> dict:
    """Call JSearch /search and return parsed JSON. Raises on HTTP error."""
    url, headers, params = build_search_request(
        query=query, location=location, remote_only=remote_only, page=page, api_key=api_key,
    )
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()
