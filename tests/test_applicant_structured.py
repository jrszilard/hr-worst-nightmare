from backend.core.models import ApplicantInfo, WorkExperience, Education
from backend.portfolio.profile_loader import load_profile


def test_applicant_accepts_structured_arrays():
    a = ApplicantInfo(
        first_name="Pat", last_name="Sample",
        work_history=[{"title": "Analyst", "company": "Acme", "start": "2019-01",
                       "end": "2021-06", "current": False, "description": "BI"}],
        education=[{"school": "State U", "degree": "BS", "field": "Econ",
                    "start": "2010", "end": "2014"}],
        skills=["Power BI", "SQL"],
    )
    assert isinstance(a.work_history[0], WorkExperience)
    assert a.work_history[0].company == "Acme"
    assert isinstance(a.education[0], Education)
    assert a.skills == ["Power BI", "SQL"]


def test_applicant_defaults_empty_arrays():
    a = ApplicantInfo(first_name="J")
    assert a.work_history == [] and a.education == [] and a.skills == []


def test_loader_parses_structured_profile(tmp_path):
    yaml_text = (
        "name: J\nstudio: S\npositioning: p\nhourly_rate_range: [75, 150]\n"
        "tone: t\nselling_points: []\nkey_differentiators: {}\n"
        "applicant:\n  first_name: Pat\n  last_name: Sample\n"
        "  skills: [Power BI, SQL]\n"
        "  work_history:\n    - title: Analyst\n      company: Acme\n"
        "      start: '2019-01'\n      end: '2021-06'\n      current: false\n"
        "      description: BI work\n"
        "  education:\n    - school: State U\n      degree: BS\n      field: Econ\n"
        "      start: '2010'\n      end: '2014'\n"
    )
    p = tmp_path / "profile.yaml"
    p.write_text(yaml_text)
    profile = load_profile(p)
    assert profile.applicant.work_history[0].company == "Acme"
    assert profile.applicant.education[0].degree == "BS"
    assert profile.applicant.skills == ["Power BI", "SQL"]
