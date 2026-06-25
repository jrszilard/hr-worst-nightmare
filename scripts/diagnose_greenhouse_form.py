#!/usr/bin/env python3
"""Diagnose a real Greenhouse form: read fields, show plan, identify gaps."""

import asyncio
import sys

sys.path.insert(0, ".")

from backend.core.models import ApplicantInfo
from backend.platforms.browser.apply_driver import discover_questions
from backend.platforms.browser.playwright_engine import PlaywrightEngine
from backend.platforms.form_fill import plan_fill

URL = "https://job-boards.greenhouse.io/gitlab/jobs/8548545002"


def pretty_plan(fields, plan, unfilled):
    print(f"\n{'='*60}")
    print(f"FIELDS FOUND: {len(fields)}")
    print(f"{'='*60}")
    for f in fields:
        star = "*" if f.required else " "
        print(f"  [{star}] {f.kind:10} | {f.label!r} | id={f.id!r}")
        if f.kind == "combobox" and f.options:
            print(f"       options: {f.options[:5]}{'...' if len(f.options) > 5 else ''}")

    print(f"\n{'='*60}")
    print(f"PLAN: {len(plan.values)} values, {len(plan.files)} files, {len(plan.selects)} selects")
    print(f"{'='*60}")
    for k, v in plan.values.items():
        preview = v[:80].replace("\n", " ") + ("..." if len(v) > 80 else "")
        print(f"  [value] {k!r} -> {preview!r}")
    for k, v in plan.files.items():
        print(f"  [file]  {k!r} -> {v!r}")
    for k, v in plan.selects.items():
        print(f"  [select] {k!r} -> {v!r}")

    if unfilled:
        print(f"\n{'='*60}")
        print(f"UNFILLED REQUIRED ({len(unfilled)}):")
        print(f"{'='*60}")
        for f in unfilled:
            print(f"  [*] {f.kind:10} | {f.label!r} | id={f.id!r}")
    else:
        print("\n  (no unfilled required fields)")


async def main():
    # Screening questions (discover_questions owns and closes its engine).
    questions = await discover_questions(
        PlaywrightEngine(mode="launch", headless=True), url=URL)
    print(f"Reading form: {URL}")
    print(f"Screening questions extracted: {len(questions)}")
    for q in questions:
        print(f"  - {q}")

    # Full field read: snapshot() returns FormFields with combobox options populated.
    engine = PlaywrightEngine(mode="launch", headless=True)
    try:
        await engine.goto(URL)
        snap = await engine.snapshot()
        parsed_fields = snap.fields
    finally:
        await engine.close()

    artifact = {
        "cover_letter": "This is a test cover letter. It discusses AI engineering experience and passion for building production ML systems. It references specific projects and demonstrates strong communication skills.",
        "screening_answers": [
            {"question": "What's the name you'd prefer us to use throughout the interview process?", "answer": "Pat"},
            {"question": "It is important to us to create an accessible and inclusive interview experience. Please let us know if there are any adjustments we can make to assist you during the hiring and interview process.", "answer": "No adjustments needed."},
            {"question": "What is your GitLab username?", "answer": "pat-sample"},
        ],
        "review_flags": [],
        "job_title": "Senior AI Engineer",
        "company": "gitlab",
    }

    from backend.portfolio.profile_loader import load_profile
    profile = load_profile()
    applicant = profile.applicant or ApplicantInfo()

    plan, unfilled = plan_fill(parsed_fields, artifact, applicant)
    pretty_plan(parsed_fields, plan, unfilled)


if __name__ == "__main__":
    asyncio.run(main())
