import pytest
from pathlib import Path

from sqlalchemy import func, select

import backend.api.jobs as jobs
from backend.core.enums import SpendKind
from backend.core.models import ApplicantInfo
from backend.db.models import ContractStatus, OpportunityDB, OpportunityKind, SpendEventDB
from scripts.prepare_apply import (
    ResumePreflightError, build_apply_package, validate_resume,
)


def test_validate_resume_accepts_pdf(tmp_path):
    f = tmp_path / "resume.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    validate_resume(f)  # no raise


def test_validate_resume_rejects_bad_ext_and_oversize(tmp_path):
    bad = tmp_path / "resume.pages"
    bad.write_bytes(b"x")
    with pytest.raises(ResumePreflightError):
        validate_resume(bad)
    big = tmp_path / "resume.pdf"
    big.write_bytes(b"0" * (3 * 1024 * 1024))
    with pytest.raises(ResumePreflightError):
        validate_resume(big)
    with pytest.raises(ResumePreflightError):
        validate_resume(tmp_path / "missing.pdf")


def test_resume_source_prefers_full_when_present(tmp_path, monkeypatch):
    """When data/resume_full.pdf exists, applies attach it (real work history)
    without a per-apply swap, regardless of the profile's configured resume_path."""
    import backend.platforms.apply_staging as pa
    full = tmp_path / "resume_full.pdf"
    full.write_bytes(b"%PDF-1.4 full-history")
    monkeypatch.setattr(pa, "_FULL_RESUME_PATH", full, raising=False)
    assert pa._resume_source_path() == full


def test_resume_source_falls_back_to_configured_when_full_absent(tmp_path, monkeypatch):
    """If the full resume was never generated, fall back to the profile's
    configured resume_path (capability-only resume)."""
    import backend.platforms.apply_staging as pa
    from types import SimpleNamespace
    missing_full = tmp_path / "resume_full.pdf"  # not created
    configured = tmp_path / "configured.pdf"
    configured.write_bytes(b"%PDF-1.4 capability")
    monkeypatch.setattr(pa, "_FULL_RESUME_PATH", missing_full, raising=False)
    monkeypatch.setattr(
        pa, "get_profile",
        lambda: SimpleNamespace(applicant=SimpleNamespace(resume_path=str(configured))),
    )
    assert pa._resume_source_path() == configured


def test_build_apply_package_shape():
    applicant = ApplicantInfo(
        first_name="Pat", last_name="Sample", email="pat@example.com",
        phone="555-0100", linkedin="https://example.com/in/pat", website="https://example.com",
        work_history=[{"title": "Analyst", "company": "Acme", "start": "2019-01"}],
        education=[{"school": "State U", "degree": "BS"}],
        skills=["Power BI", "SQL"],
    )
    pkg = build_apply_package(
        job_id=1934, title="Reporting Analyst II", cover_letter="Dear team,",
        applicant=applicant,
        resolved_url="https://maguire.wd5.myworkdayjobs.com/job/X_R1/apply/autofillWithResume",
        url_source="apply_options-host-match",
        resume_path="/shared/Pat_Resume.pdf", cover_letter_pdf_path="/shared/Pat_CL.pdf",
        generated=False,
    )
    assert pkg["job_id"] == 1934
    assert pkg["resolved_url"].endswith("/apply/autofillWithResume")
    assert pkg["url_source"] == "apply_options-host-match"
    assert pkg["generated"] is False
    assert pkg["applicant"]["phone"] == "555-0100"
    assert pkg["applicant"]["email"] == "pat@example.com"
    assert pkg["work_history"][0]["company"] == "Acme"
    assert pkg["education"][0]["degree"] == "BS"
    assert pkg["skills"] == ["Power BI", "SQL"]
    assert pkg["resume_path"] == "/shared/Pat_Resume.pdf"


# ── Task 5 end-to-end (added now; orchestration implemented in Task 5) ──────────


def _fake_generate_fn(session):
    async def _gen(opp):
        return {"cover_letter": "Dear team, Pat here.", "screening_answers": None,
                "review_flags": [], "cost_usd": 0.02}
    return _gen


async def test_prepare_end_to_end_reuses_and_resolves(db_session, tmp_path, monkeypatch):
    from scripts.prepare_apply import prepare
    monkeypatch.setattr(jobs, "_make_generate_fn", _fake_generate_fn)
    resume = tmp_path / "resume.pdf"; resume.write_bytes(b"%PDF-1.4 x")
    monkeypatch.setattr("backend.platforms.apply_staging._resume_source_path", lambda: resume)

    j = OpportunityDB(
        platform="external", external_id="wd:e2e", title="Reporting Analyst II",
        kind=OpportunityKind.job, match_score=0.9, description_fit=0.9,
        status=ContractStatus.reviewed, is_finalist=True,
        url="https://maguire.wd5.myworkdayjobs.com/en-US/External/job/Reporting_R194131-1",
    )
    db_session.add(j); await db_session.flush(); jid = j.id

    out = tmp_path / "artifacts"
    pkg = await prepare(db_session, jid, out_dir=out)
    assert pkg["generated"] is True
    assert pkg["resolved_url"].endswith("/apply/autofillWithResume")
    assert pkg["url_source"] == "job_apply_link"
    assert Path(pkg["resume_path"]).exists() and Path(pkg["resume_path"]).parent == out
    assert Path(pkg["cover_letter_pdf_path"]).exists()

    pkg2 = await prepare(db_session, jid, out_dir=out)
    assert pkg2["generated"] is False
    n_gen = await db_session.scalar(
        select(func.count()).select_from(SpendEventDB).where(SpendEventDB.kind == SpendKind.generation))
    assert n_gen == 1
