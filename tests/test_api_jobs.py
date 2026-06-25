"""Tests for the jobs API endpoints."""

from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.platform import SubmitResult
from backend.db.models import (
    Base, ContractStatus, JobApplicationDB, OpportunityDB, OpportunityKind,
)


@pytest.fixture()
async def api_engine():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def session_factory(api_engine):
    return async_sessionmaker(api_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture()
async def client(session_factory):
    from backend.db.database import get_session
    from backend.main import app

    async def _override():
        async with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture()
async def seeded(session_factory):
    """Seed one ready, one applied, one skipped job, and one contract."""
    async with session_factory() as s:
        ready = OpportunityDB(
            platform="seed", external_id="ready-1", title="Ready Job",
            url="https://job-boards.greenhouse.io/acme/jobs/ready-1",
            kind=OpportunityKind.job, match_score=0.67, description_fit=0.92,
            status=ContractStatus.reviewed,
            description="Build data products with Python and SQL for business teams.",
            skills_required=["Python", "SQL"],
            platform_meta={"company": "demo-co", "location": "Remote - United States"},
        )
        applied = OpportunityDB(
            platform="seed", external_id="applied-1", title="Applied Job",
            kind=OpportunityKind.job, match_score=0.9, description_fit=0.8,
            status=ContractStatus.applied,
        )
        skipped = OpportunityDB(
            platform="seed", external_id="skipped-1", title="Skipped Job",
            kind=OpportunityKind.job, match_score=0.0, description_fit=0.05,
            status=ContractStatus.skipped, skip_reason="low_fit",
        )
        contract = OpportunityDB(
            platform="upwork", external_id="contract-1", title="A Contract",
            kind=OpportunityKind.contract, match_score=0.5,
        )
        s.add_all([ready, applied, skipped, contract])
        await s.flush()
        s.add_all([
            JobApplicationDB(
                opportunity_id=ready.id, cover_letter="Ready cover",
                screening_answers=[{"question": "Q", "answer": "A"}],
                review_flags=[], applied=False,
            ),
            JobApplicationDB(
                opportunity_id=applied.id, cover_letter="Applied cover",
                review_flags=[{"type": "trap", "category": "identity_probe"}],
                applied=True, applied_at=datetime(2026, 5, 21),
            ),
        ])
        await s.commit()
        return {"ready": ready.id, "applied": applied.id, "skipped": skipped.id,
                "contract": contract.id}


async def test_list_jobs_returns_only_jobs_with_buckets(client: AsyncClient, seeded):
    resp = await client.get("/api/jobs")
    assert resp.status_code == 200
    items = resp.json()
    # 3 jobs, contract excluded
    assert len(items) == 3
    by_title = {it["title"]: it for it in items}
    assert by_title["Ready Job"]["bucket"] == "candidate"
    assert by_title["Applied Job"]["bucket"] == "applied"
    assert by_title["Skipped Job"]["bucket"] == "skipped"


async def test_list_jobs_computes_job_priority_and_flag_count(client: AsyncClient, seeded):
    items = (await client.get("/api/jobs")).json()
    by_title = {it["title"]: it for it in items}
    # job_priority = 0.5*match + 0.5*desc_fit = 0.5*0.67 + 0.5*0.92 = 0.795
    assert by_title["Ready Job"]["job_priority"] == pytest.approx(0.795, abs=1e-3)
    assert by_title["Applied Job"]["flag_count"] == 1
    assert by_title["Ready Job"]["flag_count"] == 0
    assert by_title["Skipped Job"]["skip_reason"] == "low_fit"
    assert by_title["Applied Job"]["applied_at"] is not None


async def test_list_jobs_includes_preview_metadata(client: AsyncClient, seeded):
    items = (await client.get("/api/jobs")).json()
    ready = {it["title"]: it for it in items}["Ready Job"]
    assert ready["company"] == "demo-co"
    assert ready["location"] == "Remote - United States"
    assert ready["work_mode"] == "remote"
    assert ready["skills_required"] == ["Python", "SQL"]
    assert "Python and SQL" in ready["description_excerpt"]


async def test_get_job_detail_returns_application(client: AsyncClient, seeded):
    resp = await client.get(f"/api/jobs/{seeded['ready']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Ready Job"
    assert body["bucket"] == "candidate"
    assert body["cover_letter"] == "Ready cover"
    assert body["screening_answers"] == [{"question": "Q", "answer": "A"}]
    assert body["company"] == "demo-co"
    assert body["location"] == "Remote - United States"
    assert body["work_mode"] == "remote"
    assert body["description_excerpt"]
    assert body["applied"] is False


async def test_get_skipped_job_detail_has_no_application(client: AsyncClient, seeded):
    resp = await client.get(f"/api/jobs/{seeded['skipped']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["bucket"] == "skipped"
    assert body["cover_letter"] is None
    assert body["screening_answers"] is None


async def test_get_job_detail_404_for_contract_kind(client: AsyncClient, seeded):
    resp = await client.get(f"/api/jobs/{seeded['contract']}")
    assert resp.status_code == 404


async def test_get_job_detail_404_for_missing_id(client: AsyncClient, seeded):
    resp = await client.get("/api/jobs/999999")
    assert resp.status_code == 404


async def test_update_job_application_edits_prepared_content(client: AsyncClient, seeded):
    resp = await client.put(
        f"/api/jobs/{seeded['ready']}/application",
        json={
            "cover_letter": "Edited cover",
            "screening_answers": [{"question": "Q", "answer": "Edited A"}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["cover_letter"] == "Edited cover"
    assert body["screening_answers"] == [{"question": "Q", "answer": "Edited A"}]


async def test_fill_prepared_application_uses_saved_artifact(monkeypatch, client: AsyncClient, seeded):
    import backend.api.jobs as jobs_api

    captured = {}

    async def fake_fill_application(engine, *, url, artifact, applicant):
        captured["url"] = url
        captured["artifact"] = artifact
        captured["applicant"] = applicant
        return SubmitResult(filled=True, submitted=False, detail="filled; awaiting human submit")

    monkeypatch.setattr(jobs_api, "fill_application", fake_fill_application)
    monkeypatch.setattr(
        jobs_api,
        "get_profile",
        lambda: type("Profile", (), {"applicant": object()})(),
    )

    resp = await client.post(f"/api/jobs/{seeded['ready']}/fill")
    assert resp.status_code == 200
    assert resp.json() == {
        "filled": True,
        "submitted": False,
        "detail": "filled; awaiting human submit",
    }
    assert captured["url"] == "https://job-boards.greenhouse.io/acme/jobs/ready-1"
    assert captured["artifact"]["cover_letter"] == "Ready cover"
    assert captured["artifact"]["screening_answers"] == [{"question": "Q", "answer": "A"}]


async def test_fill_prepared_application_rejects_placeholder_url(monkeypatch, client: AsyncClient, session_factory):
    async with session_factory() as s:
        row = OpportunityDB(platform="seed", external_id="placeholder", title="Placeholder Job",
                            url="https://example.com/jobs/fde", kind=OpportunityKind.job,
                            match_score=0.8, status=ContractStatus.reviewed)
        s.add(row)
        await s.flush()
        s.add(JobApplicationDB(opportunity_id=row.id, cover_letter="hi", applied=False))
        await s.commit()
        row_id = row.id

    resp = await client.post(f"/api/jobs/{row_id}/fill")
    assert resp.status_code == 400
    assert "placeholder" in resp.text.lower()


async def test_mark_applied_sets_flag_and_timestamp(client: AsyncClient, seeded):
    resp = await client.post(
        f"/api/jobs/{seeded['ready']}/applied", json={"applied": True}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["bucket"] == "applied"
    assert body["applied"] is True
    assert body["applied_at"] is not None


async def test_unmark_applied_clears_timestamp(client: AsyncClient, seeded):
    resp = await client.post(
        f"/api/jobs/{seeded['applied']}/applied", json={"applied": False}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["bucket"] == "candidate"
    assert body["applied"] is False
    assert body["applied_at"] is None


async def test_mark_applied_on_skipped_job_is_400(client: AsyncClient, seeded):
    resp = await client.post(
        f"/api/jobs/{seeded['skipped']}/applied", json={"applied": True}
    )
    assert resp.status_code == 400


async def test_list_jobs_hides_stale_non_us_board_rows(client: AsyncClient, session_factory):
    async with session_factory() as s:
        s.add_all([
            OpportunityDB(platform="greenhouse", external_id="us-1", title="US Data Job",
                          kind=OpportunityKind.job, match_score=0.8,
                          status=ContractStatus.reviewed,
                          platform_meta={"company": "demo", "location": "Remote - United States"}),
            OpportunityDB(platform="greenhouse", external_id="uk-1", title="UK Data Job",
                          kind=OpportunityKind.job, match_score=0.8,
                          status=ContractStatus.reviewed,
                          platform_meta={"company": "demo", "location": "London, UK"}),
        ])
        await s.commit()
    items = (await client.get("/api/jobs")).json()
    titles = {it["title"] for it in items}
    assert "US Data Job" in titles
    assert "UK Data Job" not in titles


async def test_list_jobs_displays_only_us_location_segments(client: AsyncClient, session_factory):
    async with session_factory() as s:
        s.add(OpportunityDB(platform="greenhouse", external_id="global-1", title="Global Remote Job",
                            kind=OpportunityKind.job, match_score=0.8,
                            status=ContractStatus.reviewed,
                            platform_meta={
                                "company": "demo",
                                "location": "Remote, Canada; Remote, US; Remote, United Kingdom; Remote, US-Southeast",
                            }))
        await s.commit()
    items = (await client.get("/api/jobs")).json()
    item = next(it for it in items if it["title"] == "Global Remote Job")
    assert item["location"] == "Remote, US; Remote, US-Southeast"


async def test_list_jobs_splits_mixed_comma_locations_for_display(client: AsyncClient, session_factory):
    async with session_factory() as s:
        s.add(OpportunityDB(platform="greenhouse", external_id="mixed-1", title="Mixed Remote Job",
                            kind=OpportunityKind.job, match_score=0.8,
                            status=ContractStatus.reviewed,
                            platform_meta={
                                "company": "demo",
                                "location": "Canada, US-Remote, Chicago, Atlanta",
                            }))
        await s.commit()
    items = (await client.get("/api/jobs")).json()
    item = next(it for it in items if it["title"] == "Mixed Remote Job")
    assert item["location"] == "US-Remote; Chicago; Atlanta"
    assert item["work_mode"] == "remote"


async def test_list_jobs_finalist_and_candidate_buckets(client: AsyncClient, session_factory):
    from backend.db.models import OpportunityDB, OpportunityKind, ContractStatus
    async with session_factory() as s:
        cand = OpportunityDB(platform="seed", external_id="cand-1", title="Candidate Job",
                             kind=OpportunityKind.job, match_score=0.6, description_fit=0.9,
                             is_finalist=False, status=ContractStatus.reviewed)
        fin = OpportunityDB(platform="seed", external_id="fin-1", title="Finalist Job",
                            kind=OpportunityKind.job, match_score=0.6, description_fit=0.9,
                            is_finalist=True, status=ContractStatus.reviewed)
        s.add_all([cand, fin]); await s.commit()
    items = (await client.get("/api/jobs")).json()
    by_title = {it["title"]: it for it in items}
    assert by_title["Candidate Job"]["bucket"] == "candidate"
    assert by_title["Finalist Job"]["bucket"] == "finalist"


async def test_list_jobs_dedupes_same_company_title_across_locations(
    client: AsyncClient, session_factory
):
    """Same role posted to multiple US offices collapses into one merged card."""
    from backend.db.models import OpportunityDB, OpportunityKind, ContractStatus
    async with session_factory() as s:
        s.add_all([
            OpportunityDB(
                platform="greenhouse", external_id="acme:1", title="Data Engineer",
                kind=OpportunityKind.job, match_score=0.9, description_fit=0.8,
                status=ContractStatus.reviewed,
                platform_meta={"company": "Acme", "location": "San Francisco, CA"},
            ),
            OpportunityDB(
                platform="greenhouse", external_id="acme:2", title="Data Engineer",
                kind=OpportunityKind.job, match_score=0.9, description_fit=0.8,
                status=ContractStatus.reviewed,
                platform_meta={"company": "Acme", "location": "New York, NY"},
            ),
            OpportunityDB(
                platform="greenhouse", external_id="acme:3", title="Data Engineer",
                kind=OpportunityKind.job, match_score=0.9, description_fit=0.8,
                status=ContractStatus.reviewed,
                platform_meta={"company": "Acme", "location": "San Francisco, CA"},
            ),
        ])
        await s.commit()
    items = (await client.get("/api/jobs")).json()
    de = [it for it in items if it["title"] == "Data Engineer" and it["company"] == "Acme"]
    assert len(de) == 1, "duplicate company+title rows should collapse to one"
    # Distinct locations merged, deduped.
    assert de[0]["location"] == "San Francisco, CA; New York, NY"


async def test_list_jobs_dedupe_keeps_most_progressed_row(
    client: AsyncClient, session_factory
):
    """When duplicates span buckets, the applied/finalist row is the survivor."""
    from backend.db.models import (
        OpportunityDB, OpportunityKind, ContractStatus, JobApplicationDB,
    )
    async with session_factory() as s:
        cand = OpportunityDB(
            platform="greenhouse", external_id="beta:1", title="AI Engineer",
            kind=OpportunityKind.job, match_score=0.9, description_fit=0.8,
            status=ContractStatus.reviewed,
            platform_meta={"company": "Beta", "location": "Austin, TX"},
        )
        applied = OpportunityDB(
            platform="greenhouse", external_id="beta:2", title="AI Engineer",
            kind=OpportunityKind.job, match_score=0.9, description_fit=0.8,
            status=ContractStatus.applied,
            platform_meta={"company": "Beta", "location": "Seattle, WA"},
        )
        s.add_all([cand, applied])
        await s.flush()
        s.add(JobApplicationDB(opportunity_id=applied.id, cover_letter="x",
                              review_flags=[], applied=True))
        await s.commit()
    items = (await client.get("/api/jobs")).json()
    ai = [it for it in items if it["title"] == "AI Engineer" and it["company"] == "Beta"]
    assert len(ai) == 1
    assert ai[0]["bucket"] == "applied"


async def test_apply_job_generates_then_keep_open_fills(client: AsyncClient, session_factory, monkeypatch):
    """POST /api/jobs/{id}/apply generates (if needed) then runs assisted fill."""
    import backend.api.jobs as jobs
    from backend.core.platform import SubmitResult
    from backend.db.models import OpportunityDB, OpportunityKind, ContractStatus
    async with session_factory() as s:
        j = OpportunityDB(
            platform="greenhouse", external_id="apply:1", title="Data Engineer",
            kind=OpportunityKind.job, match_score=0.9, description_fit=0.9,
            status=ContractStatus.reviewed, is_finalist=True,
            url="https://job-boards.greenhouse.io/acme/jobs/123",
            platform_meta={"company": "Acme", "location": "Remote - US"},
        )
        s.add(j); await s.commit(); jid = j.id

    def fake_make_generate_fn(session):
        async def _gen(opp):
            return {"cover_letter": "Hi, I'm Pat.",
                    "screening_answers": [{"question": "Why?", "answer": "Because."}],
                    "review_flags": [], "cost_usd": 0.12}
        return _gen

    captured = {}

    async def fake_fill_application(engine, *, url, artifact, applicant):
        captured["cover_letter"] = artifact["cover_letter"]
        captured["url"] = url
        return SubmitResult(filled=True, submitted=False, detail="filled; awaiting human submit")

    monkeypatch.setattr(jobs, "_make_generate_fn", fake_make_generate_fn)
    monkeypatch.setattr(jobs, "fill_application", fake_fill_application)

    r = await client.post(f"/api/jobs/{jid}/apply")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["generated"] is True
    assert body["filled"] is True
    assert body["submitted"] is False
    assert captured["cover_letter"] == "Hi, I'm Pat."
    assert captured["url"] == "https://job-boards.greenhouse.io/acme/jobs/123"
    # persisted so a later /fill or refresh sees it
    detail = (await client.get(f"/api/jobs/{jid}")).json()
    assert detail["cover_letter"] == "Hi, I'm Pat."


async def test_apply_job_stages_documents_and_returns_paths(
    client: AsyncClient, session_factory, monkeypatch
):
    """POST /api/jobs/{id}/apply auto-stages the résumé + cover-letter PDF, returns both paths,
    and feeds the staged résumé path into the fill artifact so the engine's upload escalation
    names the staged file. Fixes the recurring 'files not where I expect them' problem: staging
    is part of the apply, not a separate script the assisted path skipped."""
    import backend.api.jobs as jobs
    from backend.core.platform import SubmitResult
    from backend.db.models import OpportunityDB, OpportunityKind, ContractStatus
    async with session_factory() as s:
        j = OpportunityDB(
            platform="greenhouse", external_id="apply:stage", title="Data Analyst III",
            kind=OpportunityKind.job, match_score=0.9, description_fit=0.9,
            status=ContractStatus.reviewed, is_finalist=True,
            url="https://job-boards.greenhouse.io/acme/jobs/789",
            platform_meta={"company": "Acme", "location": "Remote - US"},
        )
        s.add(j); await s.commit(); jid = j.id

    def fake_make_generate_fn(session):
        async def _gen(opp):
            return {"cover_letter": "Hi, I'm Pat.", "screening_answers": None,
                    "review_flags": [], "cost_usd": 0.1}
        return _gen

    captured = {}

    async def fake_fill_application(engine, *, url, artifact, applicant):
        captured["artifact"] = artifact
        return SubmitResult(filled=True, submitted=False, detail="filled; awaiting human submit")

    def fake_stage(applicant, title, company, cover_letter, out_dir):
        return ("/artifacts/Pat_Resume_Data_Analyst_III_acme.pdf",
                "/artifacts/Pat_CoverLetter_Data_Analyst_III_acme.pdf")

    monkeypatch.setattr(jobs, "_make_generate_fn", fake_make_generate_fn)
    monkeypatch.setattr(jobs, "fill_application", fake_fill_application)
    monkeypatch.setattr(jobs, "stage_documents", fake_stage, raising=False)

    r = await client.post(f"/api/jobs/{jid}/apply")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["resume_path"] == "/artifacts/Pat_Resume_Data_Analyst_III_acme.pdf"
    assert body["cover_letter_pdf_path"] == "/artifacts/Pat_CoverLetter_Data_Analyst_III_acme.pdf"
    # staged résumé path is fed into the fill so the upload escalation names the staged file
    assert captured["artifact"]["resume_path"] == "/artifacts/Pat_Resume_Data_Analyst_III_acme.pdf"


async def test_apply_job_staging_failure_does_not_abort_fill(
    client: AsyncClient, session_factory, monkeypatch
):
    """A staging hiccup (missing résumé, etc.) must never block the form fill — the fill still
    runs and the paths come back null."""
    import backend.api.jobs as jobs
    from backend.core.platform import SubmitResult
    from backend.db.models import OpportunityDB, OpportunityKind, ContractStatus
    async with session_factory() as s:
        j = OpportunityDB(
            platform="greenhouse", external_id="apply:stagefail", title="Data Analyst III",
            kind=OpportunityKind.job, match_score=0.9, description_fit=0.9,
            status=ContractStatus.reviewed, is_finalist=True,
            url="https://job-boards.greenhouse.io/acme/jobs/790",
            platform_meta={"company": "Acme", "location": "Remote - US"},
        )
        s.add(j); await s.commit(); jid = j.id

    def fake_make_generate_fn(session):
        async def _gen(opp):
            return {"cover_letter": "Hi.", "screening_answers": None, "review_flags": [],
                    "cost_usd": 0.1}
        return _gen

    async def fake_fill_application(engine, *, url, artifact, applicant):
        return SubmitResult(filled=True, submitted=False, detail="filled; awaiting human submit")

    def boom_stage(*a, **k):
        raise jobs.ResumePreflightError("no resume on this machine")

    monkeypatch.setattr(jobs, "_make_generate_fn", fake_make_generate_fn)
    monkeypatch.setattr(jobs, "fill_application", fake_fill_application)
    monkeypatch.setattr(jobs, "stage_documents", boom_stage, raising=False)

    r = await client.post(f"/api/jobs/{jid}/apply")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["filled"] is True
    assert body["resume_path"] is None
    assert body["cover_letter_pdf_path"] is None


async def test_apply_job_reuses_existing_application_without_regenerating(
    client: AsyncClient, session_factory, monkeypatch
):
    import backend.api.jobs as jobs
    from backend.core.platform import SubmitResult
    from backend.db.models import (
        OpportunityDB, OpportunityKind, ContractStatus, JobApplicationDB,
    )
    async with session_factory() as s:
        j = OpportunityDB(
            platform="greenhouse", external_id="apply:2", title="Analytics Engineer",
            kind=OpportunityKind.job, match_score=0.9, description_fit=0.9,
            status=ContractStatus.reviewed, is_finalist=True,
            url="https://job-boards.greenhouse.io/acme/jobs/456",
            platform_meta={"company": "Acme", "location": "Remote - US"},
        )
        s.add(j); await s.flush()
        s.add(JobApplicationDB(opportunity_id=j.id, cover_letter="Existing letter",
                              review_flags=[], applied=False))
        await s.commit(); jid = j.id

    def boom(session):
        async def _gen(opp):
            raise AssertionError("generation must not run when an application exists")
        return _gen

    async def fake_fill_application(engine, *, url, artifact, applicant):
        assert artifact["cover_letter"] == "Existing letter"
        return SubmitResult(filled=True, submitted=False, detail="filled")

    monkeypatch.setattr(jobs, "_make_generate_fn", boom)
    monkeypatch.setattr(jobs, "fill_application", fake_fill_application)

    r = await client.post(f"/api/jobs/{jid}/apply")
    assert r.status_code == 200, r.text
    assert r.json()["generated"] is False
    assert r.json()["filled"] is True


async def test_apply_job_rejects_unsupported_url(client: AsyncClient, session_factory):
    from backend.db.models import OpportunityDB, OpportunityKind, ContractStatus
    async with session_factory() as s:
        j = OpportunityDB(
            platform="seed", external_id="apply:3", title="Placeholder",
            kind=OpportunityKind.job, match_score=0.9, description_fit=0.9,
            status=ContractStatus.reviewed, is_finalist=True,
            url="https://example.com/jobs/x",
        )
        s.add(j); await s.commit(); jid = j.id
    r = await client.post(f"/api/jobs/{jid}/apply")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_resolve_endpoint_data_tier_flips_channel(client, session_factory):
    from backend.core.enums import SubmissionChannel
    from sqlalchemy import select
    async with session_factory() as s:
        job = OpportunityDB(
            platform="external", external_id="jsearch:r9",
            url="https://www.linkedin.com/jobs/view/9", title="Data Analyst",
            kind=OpportunityKind.job, submission_channel=SubmissionChannel.external,
            platform_meta={"apply_options": [{"apply_link": "https://boards.greenhouse.io/a/jobs/9"}]},
        )
        s.add(job)
        await s.commit()
        job_id = job.id

    resp = await client.post(f"/api/jobs/{job_id}/resolve")
    assert resp.status_code == 200
    body = resp.json()
    assert body["detected_ats"] == "greenhouse"
    assert body["capability"] == "engine_fillable"
    assert body["status"] == "resolved"
    assert body["tier"] == "data"
    assert body["needs_human"] is False
    assert body["submission_channel"] == "browser"   # engine_fillable flip persisted

    async with session_factory() as s:
        refreshed = (await s.execute(select(OpportunityDB).where(OpportunityDB.id == job_id))).scalar_one()
        assert refreshed.resolved_url == "https://boards.greenhouse.io/a/jobs/9"
        assert refreshed.submission_channel is SubmissionChannel.browser


@pytest.mark.asyncio
async def test_resolve_endpoint_404_for_missing_job(client):
    resp = await client.post("/api/jobs/999999/resolve")
    assert resp.status_code == 404
