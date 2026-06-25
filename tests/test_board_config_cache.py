"""Regression test: load_board_config must not re-parse the YAML on every call.

Root cause of the /api/jobs pool-exhaustion incident (2026-06-08): the jobs list
endpoint calls load_board_config() ~2x per job row, and each call re-read + re-parsed
data/job_boards.yaml. With ~1,400 job rows that was ~3,160 disk parses (~13s) per
request, holding a pooled DB connection the whole time and exhausting the pool under
concurrency. load_board_config() must memoize the parse, keyed on file mtime so edits
are still picked up.
"""

import os

import pytest

import backend.core.board_scan as bs
from backend.config import settings


@pytest.fixture()
def temp_config(tmp_path, monkeypatch):
    cfg = tmp_path / "job_boards.yaml"
    cfg.write_text("greenhouse: [acme]\ncriteria: {us_only: true}\n", encoding="utf-8")
    monkeypatch.setattr(settings, "PROFILE_DIR", str(tmp_path))
    bs._reset_board_config_cache()
    return cfg


def _count_parses(monkeypatch):
    counter = {"n": 0}
    real = bs.yaml.safe_load

    def counting(text):
        counter["n"] += 1
        return real(text)

    monkeypatch.setattr(bs.yaml, "safe_load", counting)
    return counter


def test_repeated_calls_parse_file_once(temp_config, monkeypatch):
    counter = _count_parses(monkeypatch)
    a = bs.load_board_config()
    b = bs.load_board_config()
    c = bs.load_board_config()
    assert a == b == c == {"greenhouse": ["acme"], "criteria": {"us_only": True}}
    assert counter["n"] == 1, "config should be parsed once, then served from cache"


def test_cache_invalidated_when_file_changes(temp_config, monkeypatch):
    counter = _count_parses(monkeypatch)
    first = bs.load_board_config()
    assert first["greenhouse"] == ["acme"]

    temp_config.write_text("greenhouse: [other]\ncriteria: {us_only: false}\n", encoding="utf-8")
    # Force a distinct mtime in case the filesystem clock resolution is coarse.
    st = temp_config.stat()
    os.utime(temp_config, (st.st_atime, st.st_mtime + 5))

    second = bs.load_board_config()
    assert second["greenhouse"] == ["other"]
    assert counter["n"] == 2, "a changed file (new mtime) must trigger a re-parse"
