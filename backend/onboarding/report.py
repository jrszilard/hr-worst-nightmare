"""Write the draft profile bundle (profile.yaml + case-studies/*.md + report)."""

from __future__ import annotations

import yaml

from backend.core.profile_context import ProfileContext
from backend.onboarding.extractor import ExtractionResult
from backend.onboarding.ingest import IngestResult


def _case_study_markdown(cs: dict) -> str:
    tools = "\n".join(f"- {t}" for t in (cs.get("tools", []) or [])) or "- (none)"
    metrics = "\n".join(f"- {m}" for m in (cs.get("metrics", []) or [])) or "- (none)"
    return (
        f"# {cs.get('title', 'Untitled')}\n\n"
        f"**Client:** {cs.get('client', 'Unknown')}\n"
        f"**Category:** {cs.get('category', 'Unknown')}\n"
        f"**Lead:** {cs.get('lead', '')}\n\n"
        f"## Challenge\n{cs.get('challenge', '')}\n\n"
        f"## Solution\n{cs.get('solution', '')}\n\n"
        f"## Tools\n{tools}\n\n"
        f"## Key Metrics\n{metrics}\n"
    )


def write_outputs(ctx: ProfileContext, extraction: ExtractionResult, ingest: IngestResult) -> None:
    ctx.root.mkdir(parents=True, exist_ok=True)
    ctx.case_studies_dir.mkdir(parents=True, exist_ok=True)

    ctx.profile_yaml.write_text(
        yaml.safe_dump(extraction.profile, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    for cs in extraction.case_studies:
        slug = cs.get("slug") or "untitled"
        (ctx.case_studies_dir / f"{slug}.md").write_text(
            _case_study_markdown(cs), encoding="utf-8"
        )

    lines = ["# Onboarding Report", ""]
    lines.append(f"- Profile fields written: {', '.join(sorted(extraction.profile.keys())) or '(none)'}")
    lines.append(f"- Case studies generated: {len(extraction.case_studies)}")
    if ingest.blocked_urls:
        lines.append(f"- URLs that returned nothing (blocked/login wall): {', '.join(ingest.blocked_urls)}")
    lines.append("")
    lines.append("## Needs review")
    if extraction.needs_review:
        lines.extend(f"- {n}" for n in extraction.needs_review)
    else:
        lines.append("- (nothing flagged)")
    lines.append("")
    lines.append("Review and edit `profile.yaml` and `case-studies/` before your first run.")
    ctx.onboarding_report.write_text("\n".join(lines) + "\n", encoding="utf-8")
