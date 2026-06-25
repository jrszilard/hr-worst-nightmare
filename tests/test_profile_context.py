"""Unit tests for backend.core.profile_context.ProfileContext."""

from pathlib import Path

from backend.config import settings
from backend.core.profile_context import (
    ProfileContext,
    get_profile_context,
    _PROJECT_ROOT,
)


def test_relative_root_resolves_against_project_root():
    ctx = ProfileContext(root="data")
    assert ctx.root == _PROJECT_ROOT / "data"
    assert ctx.profile_yaml == _PROJECT_ROOT / "data" / "profile.yaml"
    assert ctx.case_studies_dir == _PROJECT_ROOT / "data" / "case-studies"


def test_absolute_root_used_verbatim(tmp_path):
    ctx = ProfileContext(root=tmp_path)
    assert ctx.root == tmp_path
    assert ctx.searches_yaml == tmp_path / "searches.yaml"
    assert ctx.job_boards_yaml == tmp_path / "job_boards.yaml"
    assert ctx.job_search_yaml == tmp_path / "job_search.yaml"
    assert ctx.jobs_to_screen_yaml == tmp_path / "jobs_to_screen.yaml"
    assert ctx.resume_path == tmp_path / "resume.pdf"
    assert ctx.resume_full_path == tmp_path / "resume_full.pdf"
    assert ctx.apply_artifacts_dir == tmp_path / "apply_artifacts"
    assert ctx.inputs_dir == tmp_path / "inputs"
    assert ctx.onboarding_report == tmp_path / "onboarding_report.md"


def test_database_url_derived_from_root_when_setting_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", "")
    ctx = ProfileContext(root=tmp_path)
    assert ctx.database_path == tmp_path / "contracts.db"
    assert ctx.database_url == f"sqlite+aiosqlite:///{tmp_path / 'contracts.db'}"


def test_database_url_uses_explicit_setting_when_present(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+asyncpg://x/y")
    ctx = ProfileContext(root=tmp_path)
    assert ctx.database_url == "postgresql+asyncpg://x/y"


def test_get_profile_context_uses_setting(monkeypatch):
    monkeypatch.setattr(settings, "PROFILE_DIR", "data")
    assert get_profile_context().root == _PROJECT_ROOT / "data"


def test_load_profile_respects_profile_dir(tmp_path, monkeypatch):
    """load_profile() with no arg reads PROFILE_DIR/profile.yaml, not data/."""
    from backend.portfolio.profile_loader import load_profile

    (tmp_path / "profile.yaml").write_text(
        "name: Decoupled Tester\nstudio: Test Studio\n", encoding="utf-8"
    )
    monkeypatch.setattr(settings, "PROFILE_DIR", str(tmp_path))

    profile = load_profile()
    assert profile.name == "Decoupled Tester"


def test_load_all_case_studies_respects_profile_dir(tmp_path, monkeypatch):
    from backend.portfolio.case_study_loader import load_all_case_studies

    cs_dir = tmp_path / "case-studies"
    cs_dir.mkdir()
    (cs_dir / "demo.md").write_text(
        "# Demo Project\n\n**Client:** Acme\n**Category:** Data\n**Lead:** A win\n\n"
        "Built a thing that worked.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "PROFILE_DIR", str(tmp_path))

    studies = load_all_case_studies()
    assert any(s.title == "Demo Project" for s in studies)


def test_load_board_config_respects_profile_dir(tmp_path, monkeypatch):
    from backend.core import board_scan

    (tmp_path / "job_boards.yaml").write_text("boards:\n  - vendor: greenhouse\n", encoding="utf-8")
    monkeypatch.setattr(settings, "PROFILE_DIR", str(tmp_path))
    board_scan._BOARD_CONFIG_CACHE.clear()

    assert board_scan.load_board_config() == {"boards": [{"vendor": "greenhouse"}]}


def test_load_search_config_respects_profile_dir(tmp_path, monkeypatch):
    from backend.core import job_search

    (tmp_path / "job_search.yaml").write_text("queries:\n  - data analyst\n", encoding="utf-8")
    monkeypatch.setattr(settings, "PROFILE_DIR", str(tmp_path))
    job_search._reset_search_config_cache()

    assert job_search.load_search_config() == {"queries": ["data analyst"]}
