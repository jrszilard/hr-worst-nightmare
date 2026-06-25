"""Tests for the generalised Opportunity ORM model."""

from sqlalchemy import select

from backend.core.enums import OpportunityKind, SubmissionChannel
from backend.db.models import OpportunityDB, ContractDB


def test_contractdb_is_alias_of_opportunitydb():
    assert ContractDB is OpportunityDB


def test_table_name_unchanged():
    assert OpportunityDB.__tablename__ == "contracts"


async def test_new_columns_persist(db_session):
    row = OpportunityDB(
        platform="linkedin",
        external_id="job-1",
        title="AI Engineer",
        kind=OpportunityKind.job,
        submission_channel=SubmissionChannel.browser,
        platform_meta={"location": "Remote", "ats_vendor": "greenhouse"},
        review_flags=[{"type": "trap", "category": "identity_probe"}],
    )
    db_session.add(row)
    await db_session.commit()

    fetched = (await db_session.execute(
        select(OpportunityDB).where(OpportunityDB.external_id == "job-1")
    )).scalar_one()
    assert fetched.kind == OpportunityKind.job
    assert fetched.submission_channel == SubmissionChannel.browser
    assert fetched.platform_meta["ats_vendor"] == "greenhouse"
    assert fetched.review_flags[0]["category"] == "identity_probe"


async def test_kind_and_channel_default(db_session):
    from sqlalchemy import select

    row = OpportunityDB(platform="upwork", external_id="c-1")
    db_session.add(row)
    await db_session.commit()
    db_session.expunge_all()  # drop cached instance so we read from the DB

    fetched = (await db_session.execute(
        select(OpportunityDB).where(OpportunityDB.external_id == "c-1")
    )).scalar_one()
    assert fetched.kind == OpportunityKind.contract
    assert fetched.submission_channel == SubmissionChannel.direct
