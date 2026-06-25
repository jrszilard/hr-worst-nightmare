from backend.api.jobs import _company_nudge, _biased_job_priority
from backend.db.models import OpportunityDB, OpportunityKind


def _job(company, match=0.9, fit=0.9):
    return OpportunityDB(
        platform="external", external_id=f"jsearch:{company}", kind=OpportunityKind.job,
        title="Data Analyst", match_score=match, description_fit=fit,
        platform_meta={"company": company}, skills_required=[],
    )


def test_listed_company_gets_negative_nudge():
    # 'OpenAI' is in data/job_search.yaml deprioritize_companies.
    assert _company_nudge(_job("OpenAI")) < 0


def test_unlisted_company_gets_no_nudge():
    assert _company_nudge(_job("Wire Belt Co")) == 0.0


def test_deprioritized_company_ranks_below_equal_fit_peer():
    weights: dict[str, float] = {}
    big = _biased_job_priority(_job("OpenAI"), weights)
    diverse = _biased_job_priority(_job("Wire Belt Co"), weights)
    assert diverse > big


def test_word_boundary_no_false_positive_for_metadata_solutions():
    """Regression: 'meta' in deprioritize list must NOT match 'Metadata Solutions'."""
    # 'meta' or 'Meta' is in data/job_search.yaml deprioritize_companies.
    assert _company_nudge(_job("Metadata Solutions")) == 0.0


def test_word_boundary_exact_meta_still_nudged():
    """'Meta' as a standalone company name (or part of a real Meta brand) must still get nudge."""
    # A company literally named 'Meta' should be deprioritized.
    assert _company_nudge(_job("Meta")) < 0


def test_word_boundary_meta_platforms_still_nudged():
    """'Meta Platforms' contains the word 'Meta' and should still be nudged."""
    assert _company_nudge(_job("Meta Platforms")) < 0
