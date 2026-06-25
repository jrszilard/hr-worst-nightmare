import pytest
from backend.platforms.jsearch.client import build_search_request


def test_build_search_request_encodes_query_and_remote():
    url, headers, params = build_search_request(
        query="Data Analyst", location="United States", remote_only=True, page=1, api_key="KEY",
    )
    assert url.endswith("/search")
    assert headers["X-RapidAPI-Key"] == "KEY"
    assert params["query"] == "Data Analyst in United States"
    assert params["remote_jobs_only"] == "true"
    assert params["page"] == "1"
