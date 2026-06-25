"""Stage the résumé + cover-letter PDF into a predictable, session-shared directory.

Shared by both `scripts/prepare_apply.py` (the offline CLI) and the assisted-apply
endpoint (`backend/api/jobs.py`), so every apply path stages documents to the SAME place
(`<PROFILE_DIR>/apply_artifacts/`). Browser extensions can't set a file input from JS, so
résumé/cover attachment is always a human step — this guarantees the files are always
present and discoverable for that step.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from backend.core.models import ApplicantInfo
from backend.core.profile_context import get_profile_context
from backend.platforms.form_fill import _build_document_filename, _generate_cover_letter_pdf
from backend.portfolio.profile_loader import get_profile

_ROOT = Path(__file__).resolve().parents[2]

# Workday accepts PDF/DOC/DOCX; silently fails on .pages/.odt and oversize files.
_ALLOWED_RESUME_EXT = {".pdf", ".doc", ".docx"}
_MAX_RESUME_BYTES = 2 * 1024 * 1024  # ~2 MB
# Full real-history resume (scripts/build_full_resume.py). Preferred for applies so they
# attach the complete work history without a per-apply swap; falls back to the profile's
# configured resume_path when this hasn't been generated.
_FULL_RESUME_PATH = get_profile_context().resume_full_path


class ResumePreflightError(Exception):
    """The resume file is missing, the wrong type, or too large for upload."""


def validate_resume(path: Path | str) -> None:
    """Raise ResumePreflightError unless *path* is an existing PDF/DOC/DOCX < ~2 MB."""
    p = Path(path)
    if not p.exists():
        raise ResumePreflightError(f"Resume not found: {p}")
    if p.suffix.lower() not in _ALLOWED_RESUME_EXT:
        raise ResumePreflightError(
            f"Resume must be PDF/DOC/DOCX (Workday silently fails on others); got {p.suffix}")
    if p.stat().st_size > _MAX_RESUME_BYTES:
        raise ResumePreflightError(f"Resume is {p.stat().st_size} bytes; keep it under ~2 MB")


def _resume_source_path() -> Path:
    """The resume file to attach: prefer the full real-history resume_full.pdf when it
    exists, else the profile's configured resume_path, else data/resume.pdf. (seam for tests)."""
    if _FULL_RESUME_PATH.exists():
        return _FULL_RESUME_PATH
    applicant = get_profile().applicant
    raw = (applicant.resume_path if applicant else "") or str(get_profile_context().resume_path)
    p = Path(raw)
    return p if p.is_absolute() else _ROOT / p


def stage_documents(applicant: ApplicantInfo, title: str, company: str,
                    cover_letter: str, out_dir: Path) -> tuple[str, str]:
    """Copy the resume and render the cover-letter PDF into *out_dir* (session-shared,
    so a human file-picker can attach them). Returns (resume_path, cover_letter_pdf_path)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    src = _resume_source_path()
    validate_resume(src)
    artifact = {"job_title": title, "company": company}
    resume_name = _build_document_filename(applicant, artifact, "Resume")
    resume_dest = out_dir / resume_name
    shutil.copy2(src, resume_dest)

    cl_name = _build_document_filename(applicant, artifact, "CoverLetter")
    tmp_pdf = Path(_generate_cover_letter_pdf(cover_letter, cl_name))
    cl_dest = out_dir / cl_name
    shutil.move(str(tmp_pdf), cl_dest)
    return str(resume_dest), str(cl_dest)
