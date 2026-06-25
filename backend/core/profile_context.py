"""Resolve all per-person paths from a single PROFILE_DIR.

Every per-user input — profile.yaml, résumés, case studies, search/board config,
the SQLite database, apply artifacts — lives under one directory. This module is
the single seam other code uses instead of hardcoded ``data/...`` paths, so the
app can be pointed at any user's folder via the PROFILE_DIR setting.
"""

from __future__ import annotations

from pathlib import Path

from backend.config import settings

# Project root = three levels up from this file (backend/core/profile_context.py).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ProfileContext:
    """Resolves per-person paths under a single profile directory.

    ``root`` may be passed explicitly (used by tests); otherwise it comes from
    ``settings.PROFILE_DIR``. Relative roots resolve against the project root.
    """

    def __init__(self, root: Path | str | None = None) -> None:
        raw = settings.PROFILE_DIR if root is None else root
        candidate = Path(raw)
        self.root = candidate if candidate.is_absolute() else _PROJECT_ROOT / candidate

    @property
    def inputs_dir(self) -> Path:
        return self.root / "inputs"

    @property
    def profile_yaml(self) -> Path:
        return self.root / "profile.yaml"

    @property
    def case_studies_dir(self) -> Path:
        return self.root / "case-studies"

    @property
    def resume_path(self) -> Path:
        return self.root / "resume.pdf"

    @property
    def resume_full_path(self) -> Path:
        return self.root / "resume_full.pdf"

    @property
    def searches_yaml(self) -> Path:
        return self.root / "searches.yaml"

    @property
    def job_boards_yaml(self) -> Path:
        return self.root / "job_boards.yaml"

    @property
    def job_search_yaml(self) -> Path:
        return self.root / "job_search.yaml"

    @property
    def jobs_to_screen_yaml(self) -> Path:
        return self.root / "jobs_to_screen.yaml"

    @property
    def apply_artifacts_dir(self) -> Path:
        return self.root / "apply_artifacts"

    @property
    def onboarding_report(self) -> Path:
        return self.root / "onboarding_report.md"

    @property
    def database_path(self) -> Path:
        return self.root / "contracts.db"

    @property
    def database_url(self) -> str:
        if settings.DATABASE_URL:
            return settings.DATABASE_URL
        return f"sqlite+aiosqlite:///{self.database_path}"

    @property
    def browser_engine(self) -> str:
        """Configured browser engine name (the factory builds the instance)."""
        return settings.BROWSER_ENGINE


def get_profile_context() -> ProfileContext:
    """Return the profile context derived from the PROFILE_DIR setting."""
    return ProfileContext()
