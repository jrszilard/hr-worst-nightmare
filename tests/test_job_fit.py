"""Tests for deterministic job-fit scoring (de-saturates the job ranking).

Board-scanned jobs never got a description_fit, so job_priority collapsed to the
self-referential match_score (~1.0 for almost everything). job_fit_score gives a
spread-out, no-LLM fit signal from title relevance, skill depth, and seniority.
"""

import pytest

from backend.core.job_fit import job_fit_score
from backend.portfolio.profile_loader import load_profile


@pytest.fixture(scope="module")
def profile():
    return load_profile()


def _fit(profile, title, skills, description=""):
    return job_fit_score(title, description, skills, profile)


def test_strong_title_with_deep_core_skills_scores_high(profile):
    score = _fit(profile, "Senior Data Analyst",
                 ["Power BI", "SQL", "Python", "Tableau"],
                 "Build dashboards and reporting with Power BI, SQL, Python, Tableau.")
    assert score >= 0.85


def test_anti_fit_titles_score_low(profile):
    for title in [
        "Software Engineer, New Grad (AI)",
        "Customer Success Strategy & Operations Manager",
        "People Analytics & Operations, University Hire",
        "Enterprise Technical Premium Support Specialist",
        "Senior Recruiter",
    ]:
        score = _fit(profile, title, ["Python", "SQL"])
        assert score <= 0.3, f"{title!r} scored {score}"


def test_ranking_separates_strong_medium_weak(profile):
    strong = _fit(profile, "AI Solutions Architect",
                  ["Python", "LangChain", "RAG pipelines", "AI agents"])
    medium = _fit(profile, "Software Engineer, User Operations", ["Python", "SQL"])
    weak = _fit(profile, "Engineering Manager", ["Python"])
    assert strong > medium > weak


def test_seniority_penalty_for_exec_roles(profile):
    ic = _fit(profile, "Data Scientist", ["Python", "SQL", "Pandas"])
    director = _fit(profile, "Director of Data Science", ["Python", "SQL", "Pandas"])
    assert director < ic


def test_score_is_bounded(profile):
    for title in ["", "Forward Deployed Engineer", "VP Engineering"]:
        s = _fit(profile, title, ["Python", "SQL", "Power BI", "ETL", "DAX"])
        assert 0.0 <= s <= 1.0
