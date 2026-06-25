"""Tests for the generalised Opportunity Pydantic schemas."""

from backend.core.enums import OpportunityKind, SubmissionChannel
from backend.core.models import Opportunity, OpportunityCreate, Contract, ContractCreate


def test_contract_aliases_point_to_opportunity():
    assert Contract is Opportunity
    assert ContractCreate is OpportunityCreate


def test_defaults_are_contract_and_direct():
    opp = OpportunityCreate(platform="upwork", external_id="x1")
    assert opp.kind == OpportunityKind.contract
    assert opp.submission_channel == SubmissionChannel.direct


def test_comp_properties_mirror_budget():
    opp = Opportunity(id=1, platform="linkedin", external_id="j1",
                      budget_min=120000.0, budget_max=160000.0)
    assert opp.comp_min == 120000.0
    assert opp.comp_max == 160000.0


def test_job_fields_round_trip():
    opp = OpportunityCreate(
        platform="greenhouse", external_id="g1", kind=OpportunityKind.job,
        submission_channel=SubmissionChannel.browser,
        platform_meta={"seniority": "senior"},
    )
    assert opp.kind == OpportunityKind.job
    assert opp.platform_meta["seniority"] == "senior"


def test_existing_contract_construction_still_works():
    c = ContractCreate(platform="upwork", external_id="abc", budget_min=2000.0,
                       budget_max=5000.0)
    assert c.budget_min == 2000.0
