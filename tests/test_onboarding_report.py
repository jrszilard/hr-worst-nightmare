"""Tests for backend.onboarding.report — writes a loadable profile bundle."""

from backend.core.profile_context import ProfileContext
from backend.onboarding.extractor import ExtractionResult
from backend.onboarding.ingest import IngestResult
from backend.onboarding.report import write_outputs
from backend.portfolio.profile_loader import load_profile


def test_write_outputs_produces_loadable_profile(tmp_path):
    ctx = ProfileContext(root=tmp_path)
    extraction = ExtractionResult(
        profile={
            "name": "Pat", "studio": "Sample Studio", "positioning": "Consultant.",
            "location": "Vermont", "framing": "a Sample Studio partnership", "tone": "Plain.",
            "selling_points": ["dashboards"],
            "key_differentiators": {"reporting": {"description": "BI", "skills": ["Power BI"]}},
            "applicant": {"first_name": "Pat", "last_name": "Sample", "email": "pat@example.com"},
        },
        case_studies=[{
            "slug": "demo", "title": "Demo", "client": "Example Co", "category": "Data",
            "lead": "Cut reporting time", "challenge": "Slow", "solution": "Pipeline",
            "tools": ["Python"], "metrics": ["90% faster"],
        }],
        needs_review=["LinkedIn returned a login wall"],
    )
    write_outputs(ctx, extraction, IngestResult(blocked_urls=["https://example.com/in/pat"]))

    profile = load_profile(ctx.profile_yaml)
    assert profile.name == "Pat"
    assert profile.location == "Vermont"
    assert (ctx.case_studies_dir / "demo.md").exists()
    report = ctx.onboarding_report.read_text(encoding="utf-8")
    assert "LinkedIn returned a login wall" in report


def test_case_study_markdown_round_trips_through_loader(tmp_path):
    ctx = ProfileContext(root=tmp_path)
    extraction = ExtractionResult(
        profile={
            "name": "Pat", "studio": "Sample Studio", "positioning": "Consultant.",
            "location": "Vermont", "framing": "a Sample Studio partnership", "tone": "Plain.",
            "selling_points": ["dashboards"],
            "key_differentiators": {"reporting": {"description": "BI", "skills": ["Power BI"]}},
            "applicant": {"first_name": "Pat", "last_name": "Sample", "email": "pat@example.com"},
        },
        case_studies=[{
            "slug": "demo", "title": "Demo", "client": "Example Co", "category": "Data",
            "lead": "Cut reporting time", "challenge": "Slow", "solution": "Pipeline",
            "tools": ["Python"], "metrics": ["90% faster"],
        }],
        needs_review=[],
    )
    write_outputs(ctx, extraction, IngestResult(blocked_urls=[]))

    from backend.portfolio.case_study_loader import load_case_study
    loaded = load_case_study(ctx.case_studies_dir / "demo.md")
    assert loaded.client == "Example Co"
    assert loaded.category == "Data"
    assert loaded.tools == ["Python"]
    assert loaded.metrics == ["90% faster"]
