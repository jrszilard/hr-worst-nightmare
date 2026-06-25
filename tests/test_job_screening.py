import pytest
from sqlalchemy import select

from backend.core.job_screening import screen_and_store
from backend.core.enums import ContractStatus, OpportunityKind, SubmissionChannel
from backend.db.models import OpportunityDB
from backend.portfolio.profile_loader import load_profile


@pytest.mark.asyncio
async def test_screens_candidate_and_skip(db_session):
    profile = load_profile()
    specs = [
        {"platform": "greenhouse", "external_id": "acme:1", "title": "AI Engineer",
         "url": "u", "description": "Python Claude API work", "skills_required": ["Python"],
         "client_questions": None, "submission_channel": "auto",
         "platform_meta": {"company": "acme"}, "description_fit": 0.9},
        {"platform": "greenhouse", "external_id": "acme:2", "title": "Plumber",
         "url": "u", "description": "pipes", "skills_required": [],
         "client_questions": None, "submission_channel": "auto",
         "platform_meta": {"company": "acme"}, "description_fit": 0.0},
    ]
    summary = await screen_and_store(db_session, specs, profile, threshold=0.15)
    await db_session.commit()

    rows = (await db_session.execute(
        select(OpportunityDB).order_by(OpportunityDB.external_id))).scalars().all()
    assert len(rows) == 2
    by_id = {r.external_id: r for r in rows}
    assert by_id["acme:1"].kind == OpportunityKind.job
    assert by_id["acme:1"].submission_channel == SubmissionChannel.auto
    assert by_id["acme:1"].status == ContractStatus.reviewed   # candidate
    assert by_id["acme:2"].status == ContractStatus.skipped
    assert summary["candidates"] == 1 and summary["skipped"] == 1


@pytest.mark.asyncio
async def test_idempotent_upsert(db_session):
    profile = load_profile()
    spec = {"platform": "lever", "external_id": "co:9", "title": "Data Eng", "url": "u",
            "description": "Python SQL", "skills_required": ["Python", "SQL"],
            "client_questions": None, "submission_channel": "auto",
            "platform_meta": {"company": "co"}, "description_fit": 0.8}
    await screen_and_store(db_session, [spec], profile, threshold=0.15)
    await screen_and_store(db_session, [spec], profile, threshold=0.15)
    await db_session.commit()
    rows = (await db_session.execute(
        select(OpportunityDB).where(OpportunityDB.external_id == "co:9"))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_remote_only_skips_onsite_keeps_remote_and_nationwide(db_session):
    """remote_only is enforced locally (not just trusting the JSearch flag): explicit
    on-site roles are skipped 'not_remote'; remote-flagged and 'Nationwide' roles are kept
    even when the feed marks them non-remote (e.g. the Maguire job we applied to)."""
    profile = load_profile()
    base = {"url": "u", "skills_required": ["Python", "SQL"], "client_questions": None,
            "submission_channel": "external", "description_fit": 0.9}
    specs = [
        {**base, "platform": "x", "external_id": "onsite:1", "title": "Analytics Engineer",
         "description": "Must live within a commutable distance to the Atlanta office.",
         "platform_meta": {"company": "Cox", "location": "Norcross, GA", "remote": False}},
        {**base, "platform": "x", "external_id": "nationwide:1", "title": "Reporting Analyst II",
         "description": "We are looking for a Reporting Analyst, Nationwide!",
         "platform_meta": {"company": "Maguire", "location": "Bala Cynwyd, PA", "remote": False}},
        {**base, "platform": "x", "external_id": "remote:1", "title": "Data Engineer",
         "description": "Build data pipelines in Python and SQL.",
         "platform_meta": {"company": "Acme", "location": "Remote - US", "remote": True}},
        {**base, "platform": "x", "external_id": "city:1", "title": "Data Analyst",
         "description": "Support reporting for the team in our Green Bay location.",
         "platform_meta": {"company": "USV", "location": "Green Bay, WI", "remote": False}},
    ]
    summary = await screen_and_store(db_session, specs, profile, threshold=0.15, remote_only=True)
    await db_session.commit()
    rows = {r.external_id: r for r in
            (await db_session.execute(select(OpportunityDB))).scalars().all()}
    assert rows["onsite:1"].status == ContractStatus.skipped
    assert rows["onsite:1"].skip_reason == "not_remote"
    assert rows["city:1"].status == ContractStatus.skipped
    assert rows["city:1"].skip_reason == "not_remote"
    assert rows["nationwide:1"].status == ContractStatus.reviewed   # kept (Nationwide)
    assert rows["remote:1"].status == ContractStatus.reviewed       # kept (flagged remote)
    assert summary["candidates"] == 2 and summary["skipped"] == 2


@pytest.mark.asyncio
async def test_remote_only_off_does_not_skip_onsite_for_location(db_session):
    """With remote_only off (the default), on-site roles are NOT skipped for location."""
    profile = load_profile()
    spec = {"platform": "x", "external_id": "onsite:2", "title": "Analytics Engineer",
            "url": "u", "description": "Must live within a commutable distance to the office.",
            "skills_required": ["Python", "SQL"], "client_questions": None,
            "submission_channel": "external",
            "platform_meta": {"company": "Cox", "location": "Norcross, GA", "remote": False},
            "description_fit": 0.9}
    await screen_and_store(db_session, [spec], profile, threshold=0.15)  # default remote_only=False
    await db_session.commit()
    row = (await db_session.execute(
        select(OpportunityDB).where(OpportunityDB.external_id == "onsite:2"))).scalar_one()
    assert row.status == ContractStatus.reviewed   # candidate by fit; not location-skipped


@pytest.mark.asyncio
async def test_disliked_skill_can_push_new_job_below_threshold(db_session):
    """A strongly-penalized skill drops a high-match job into 'skipped' on scan."""
    from backend.portfolio.profile_loader import load_profile
    from backend.db.models import SkillPreferenceDB

    profile = load_profile()  # "Python" is a core skill → match ~1.0
    db_session.add(SkillPreferenceDB(skill="python", weight=-1.0))
    await db_session.commit()

    spec = {"platform": "seed", "external_id": "scan-1", "title": "Python job",
            "url": "u", "description": "py", "skills_required": ["Python"],
            "client_questions": None, "submission_channel": "auto",
            "platform_meta": None, "description_fit": None}
    # base priority = match (~1.0); biased = 1.0 + 0.3*(-1.0) = 0.7.
    # threshold 0.8 → unbiased 1.0 would be a candidate; biased 0.7 is skipped.
    summary = await screen_and_store(db_session, [spec], profile, threshold=0.8)

    row = (await db_session.execute(
        select(OpportunityDB).where(OpportunityDB.external_id == "scan-1")
    )).scalar_one()
    assert summary["skipped"] == 1
    assert row.status == ContractStatus.skipped


def _rescan_spec(**over):
    spec = {"platform": "jsearch", "external_id": "co:42", "title": "Data Engineer",
            "url": "u", "description": "Python SQL remote", "skills_required": ["Python", "SQL"],
            "client_questions": None, "submission_channel": "external",
            "platform_meta": {"company": "co"}, "description_fit": 0.9}
    spec.update(over)
    return spec


async def _seed_row(db_session, profile, **over):
    spec = _rescan_spec(**over)
    await screen_and_store(db_session, [spec], profile, threshold=0.15)
    await db_session.flush()
    return (await db_session.execute(select(OpportunityDB).where(
        OpportunityDB.external_id == spec["external_id"]))).scalar_one()


@pytest.mark.asyncio
async def test_rescan_leaves_applied_row_untouched(db_session):
    """A job with a submitted application is terminal: re-scans must not re-screen
    the row or delete the applied record (the #1934 live-submit record was wiped
    twice by re-scans before this guard)."""
    from backend.db.models import JobApplicationDB
    profile = load_profile()
    row = await _seed_row(db_session, profile)
    db_session.add(JobApplicationDB(opportunity_id=row.id, cover_letter="sent",
                                    screening_answers=[], applied=True))
    await db_session.flush()

    await screen_and_store(db_session, [_rescan_spec(title="Renamed Role")],
                           profile, threshold=0.15)
    await db_session.commit()

    app = (await db_session.execute(select(JobApplicationDB).where(
        JobApplicationDB.opportunity_id == row.id))).scalar_one_or_none()
    assert app is not None and app.applied is True
    refreshed = (await db_session.execute(select(OpportunityDB).where(
        OpportunityDB.id == row.id))).scalar_one()
    assert refreshed.title == "Data Engineer"


@pytest.mark.asyncio
async def test_rescan_preserves_manual_skip(db_session):
    """A human-set skip_reason (anything other than the auto reasons) survives
    re-scans even when the job re-screens as a strong candidate."""
    profile = load_profile()
    row = await _seed_row(db_session, profile)
    row.skip_reason = "user skip: posting closed"
    row.status = ContractStatus.skipped
    await db_session.flush()

    await screen_and_store(db_session, [_rescan_spec()], profile, threshold=0.15)
    await db_session.commit()

    refreshed = (await db_session.execute(select(OpportunityDB).where(
        OpportunityDB.id == row.id))).scalar_one()
    assert refreshed.skip_reason == "user skip: posting closed"
    assert refreshed.status == ContractStatus.skipped


@pytest.mark.asyncio
async def test_rescan_clears_auto_skip_when_fit_improves(db_session):
    """Auto skips (low_fit / not_remote) still re-screen normally — only manual
    skips are sticky."""
    profile = load_profile()
    row = await _seed_row(db_session, profile, title="Plumber", description="pipes",
                          skills_required=[], description_fit=0.0)
    assert row.skip_reason == "low_fit"

    await screen_and_store(db_session, [_rescan_spec(description_fit=0.9)],
                           profile, threshold=0.15)
    await db_session.commit()

    refreshed = (await db_session.execute(select(OpportunityDB).where(
        OpportunityDB.id == row.id))).scalar_one()
    assert refreshed.skip_reason is None
    assert refreshed.status == ContractStatus.reviewed


@pytest.mark.asyncio
async def test_rescan_keeps_generated_cover_letter(db_session):
    """Generated (paid-for) application content survives re-scans; only empty
    shell applications are cleared."""
    from backend.db.models import JobApplicationDB
    profile = load_profile()
    row = await _seed_row(db_session, profile)
    db_session.add(JobApplicationDB(opportunity_id=row.id, cover_letter="Paid letter",
                                    screening_answers=[], applied=False))
    await db_session.flush()

    await screen_and_store(db_session, [_rescan_spec()], profile, threshold=0.15)
    await db_session.commit()

    from backend.db.models import JobApplicationDB as App
    app = (await db_session.execute(select(App).where(
        App.opportunity_id == row.id))).scalar_one_or_none()
    assert app is not None and app.cover_letter == "Paid letter"
