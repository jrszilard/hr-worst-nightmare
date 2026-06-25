from backend.portfolio.profile_loader import load_profile


def test_profile_exposes_applicant():
    profile = load_profile()
    assert profile.applicant is not None
    assert profile.applicant.first_name == "Pat"
    assert profile.applicant.email == "pat@example.com"
    assert profile.applicant.resume_path == "resume.pdf"
    assert profile.applicant.linkedin == "https://example.com/in/pat"
    assert profile.applicant.website == "https://example.com"
