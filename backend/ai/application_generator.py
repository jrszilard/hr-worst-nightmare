"""Generalised application generator.

Wraps proposal generation (contracts) and routes the produced text through the
writing-quality pipeline so AI tells are removed and embedded traps are flagged.
Job-kind generation (cover letter + screening answers) is implemented here.
"""

from __future__ import annotations

import functools
from pathlib import Path

import anthropic
from pydantic import BaseModel

from backend.ai.proposal_generator import generate_proposal
from backend.ai.usage import record_usage
from backend.ai.writing.injection import scan_for_traps
from backend.ai.writing.pipeline import WritingReport, run_writing_pipeline
from backend.ai.writing.style import style_rules_text
from backend.config import settings
from backend.core.enums import OpportunityKind
from backend.core.models import (
    ApplicantInfo, AvailabilityConfig, LoadedProfile, Opportunity, ProposalSection,
)
from backend.platforms.form_fill import FormField, _is_eeo, is_generated_screening_question
from backend.portfolio.case_study_loader import (
    DetailedCaseStudy,
    format_case_studies_for_prompt,
    load_all_case_studies,
)

_PROMPTS = Path(__file__).parent / "prompts"
_MODEL = "claude-sonnet-4-6"

# Placeholder left in place of an auto-generated answer when a screening question
# is itself a trap (identity probe / injected instruction). The human answers it.
_SCREENING_TRAP_NOTICE = "[Flagged as a possible AI-detection trap. Answer this yourself.]"

# Placeholder left in place of an auto-generated answer when a screening question asks
# for a demographic identity / EEO fact (gender, race, veteran, disability, transgender,
# orientation, pronouns, LGBTQ). Never auto-answered — the human answers it.
_EEO_NOTICE = "[Demographic / EEO / identity question. Answer this yourself.]"


@functools.lru_cache(maxsize=8)
def _load_prompt(name: str) -> str:
    return (_PROMPTS / name).read_text(encoding="utf-8")


def _case_studies_block(detailed_case_studies: list[DetailedCaseStudy] | None) -> str:
    """Format the file-based detailed case studies for the prompt."""
    return format_case_studies_for_prompt(detailed_case_studies or [])


_NO_APPLICANT_FACTS = "(no verified education or work-history facts provided)"


def _applicant_facts_block(applicant: ApplicantInfo | None) -> str:
    """Real biographical facts (location + employment + education) a screening answer may
    ground on.

    Screening questions like "School" / "Degree" / "Have you worked at X?" / "Where are you
    based?" ask for biographical facts that are NOT in the case studies; without them in the
    prompt the model confabulates (it invented "University of Michigan" / "no formal degree"
    for a real applicant who holds two degrees, and "Chicago" for a New-Hampshire applicant).
    Mirrors fill_planner's grounded facts block.
    """
    if applicant is None:
        return _NO_APPLICANT_FACTS
    lines: list[str] = []
    residence = applicant.location or applicant.country
    if residence:
        lines.append(f"Location: based in {residence}.")
    for w in applicant.work_history:
        end = "present" if w.current else (w.end or "?")
        entry = f"Employment: {w.title} at {w.company} ({w.start or '?'}-{end})."
        if w.description:
            entry += f" {w.description}"
        lines.append(entry.strip())
    for e in applicant.education:
        deg = " ".join(p for p in (e.degree, e.field) if p)
        lines.append(f"Education: {deg} from {e.school} "
                     f"({e.start or '?'}-{e.end or '?'})".strip())
    return "\n".join(lines) or _NO_APPLICANT_FACTS


class ScreeningAnswer(BaseModel):
    question: str
    answer: str


class GeneratedApplication(BaseModel):
    kind: OpportunityKind
    sections: list[ProposalSection] | None = None
    cover_letter: str | None = None
    bid_amount: float | None = None
    estimated_duration: str | None = None
    review_flags: list[dict] = []
    screening_answers: list[ScreeningAnswer] | None = None


def _posting_context(opportunity: Opportunity) -> str:
    parts = [opportunity.description or ""]
    if opportunity.client_questions:
        parts.extend(opportunity.client_questions)
    return "\n".join(parts)


def _dedup_flags(flags: list[dict]) -> list[dict]:
    """Drop duplicate review flags while preserving first-seen order."""
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for f in flags:
        key = tuple(sorted(f.items()))
        if key not in seen:
            seen.add(key)
            deduped.append(f)
    return deduped


def _flags_from_report(report: WritingReport) -> list[dict]:
    flags: list[dict] = []
    for trap in report.traps:
        flags.append({
            "type": "trap", "category": trap.category,
            "severity": trap.severity, "snippet": trap.snippet,
        })
    for cliche in report.sanitizer.cliches_found:
        flags.append({"type": "ai_tell", "detail": f"cliché: {cliche}"})
    if not report.critic_available:
        flags.append({"type": "critic_unavailable"})
    return flags


async def _generate_text(
    prompt_name: str, client: anthropic.AsyncAnthropic,
    profile: LoadedProfile, **fields: str
) -> str:
    message = _load_prompt(prompt_name).format(
        style_rules=style_rules_text(profile), **fields
    )
    response = await client.messages.create(
        model=_MODEL, max_tokens=900,
        messages=[{"role": "user", "content": message}],
    )
    record_usage(_MODEL, response)
    if not response.content:
        raise ValueError(f"Claude returned empty content for prompt '{prompt_name}'")
    return response.content[0].text


async def _generate_job_application(
    opportunity: Opportunity,
    profile: LoadedProfile,
    availability: AvailabilityConfig,
    client: anthropic.AsyncAnthropic,
    detailed_case_studies: list[DetailedCaseStudy] | None,
) -> GeneratedApplication:
    # Load the file-based detailed studies if the caller passed None.
    if detailed_case_studies is None:
        detailed_case_studies = load_all_case_studies()
    case_studies_text = _case_studies_block(detailed_case_studies)

    context = _posting_context(opportunity)
    common = {
        "name": profile.name,
        "studio": profile.studio,
        "positioning": profile.positioning,
        "selling_points": ", ".join(profile.selling_points),
        "applicant_facts": _applicant_facts_block(profile.applicant),
        "case_studies": case_studies_text,
        "contract_title": opportunity.title or "Untitled role",
        "contract_description": opportunity.description or "No description provided",
        "contract_skills": ", ".join(opportunity.skills_required or []) or "None listed",
    }
    all_flags: list[dict] = []

    cover_draft = await _generate_text("cover_letter.txt", client, profile, **common)
    cover_clean, cover_report = await run_writing_pipeline(
        cover_draft, posting_context=context, client=client, use_critic=True,
    )
    all_flags.extend(_flags_from_report(cover_report))

    answers: list[ScreeningAnswer] = []
    for question in (opportunity.client_questions or []):
        q_traps = scan_for_traps(question)
        if q_traps:
            # Identity probe or injected instruction. Do NOT auto-answer it;
            # leave a placeholder for the human and flag why.
            answers.append(
                ScreeningAnswer(question=question, answer=_SCREENING_TRAP_NOTICE)
            )
            all_flags.append({
                "type": "trap_question",
                "categories": ", ".join(sorted({t.category for t in q_traps})),
                "detail": "screening question flagged as a trap; left for manual answer",
            })
            continue
        if _is_eeo(question):
            # Demographic identity / EEO question (gender, race, veteran, disability,
            # transgender, orientation, pronouns, LGBTQ). Never auto-answer it — the human
            # does. Shares form_fill._EEO_RE with the fill-planner hard-block (one boundary).
            answers.append(ScreeningAnswer(question=question, answer=_EEO_NOTICE))
            all_flags.append({
                "type": "eeo_question",
                "question": question,
                "detail": "demographic/EEO/identity question; left for manual answer",
            })
            continue
        if not is_generated_screening_question(FormField(label=question)):
            # Referral-source channel cell, compensation, work-auth, or another manual fact.
            # Never auto-answer it — answering confabulates (a made-up referral, an invented
            # salary). Apply the same gate discovery uses so questions stored before a filter
            # improvement are dropped here too (the client_questions merge is additive-only).
            # No answer is appended, so nothing gets typed into the field; it escalates to the
            # human at fill time.
            all_flags.append({
                "type": "manual_question",
                "question": question,
                "detail": "referral-source / compensation / factual question; left for manual answer",
            })
            continue
        draft = await _generate_text(
            "screening_answer.txt", client, profile, question=question, **common
        )
        clean, report = await run_writing_pipeline(
            draft, posting_context=context, client=client, use_critic=True,
        )
        answers.append(ScreeningAnswer(question=question, answer=clean))
        all_flags.extend(_flags_from_report(report))

    deduped = _dedup_flags(all_flags)

    return GeneratedApplication(
        kind=OpportunityKind.job,
        cover_letter=cover_clean,
        screening_answers=answers or None,
        review_flags=deduped,
    )


async def generate_application(
    opportunity: Opportunity,
    profile: LoadedProfile,
    availability: AvailabilityConfig,
    client: anthropic.AsyncAnthropic | None = None,
    detailed_case_studies: list[DetailedCaseStudy] | None = None,
) -> GeneratedApplication:
    """Generate a human-sounding, trap-aware application for *opportunity*."""
    if client is None:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    if opportunity.kind == OpportunityKind.job:
        return await _generate_job_application(
            opportunity, profile, availability, client,
            detailed_case_studies,
        )

    proposal = await generate_proposal(
        contract=opportunity, profile=profile,
        availability=availability, client=client,
        detailed_case_studies=detailed_case_studies,
    )

    context = _posting_context(opportunity)
    all_flags: list[dict] = []
    clean_sections: list[ProposalSection] = []
    for section in proposal.sections:
        clean_text, report = await run_writing_pipeline(
            section.content, posting_context=context, client=client, use_critic=True,
        )
        clean_sections.append(ProposalSection(
            type=section.type, content=clean_text,
            annotation=section.annotation, case_study_ids=section.case_study_ids,
        ))
        all_flags.extend(_flags_from_report(report))

    # De-duplicate flags while preserving order.
    deduped = _dedup_flags(all_flags)

    return GeneratedApplication(
        kind=OpportunityKind.contract,
        sections=clean_sections,
        bid_amount=proposal.bid_amount,
        estimated_duration=proposal.estimated_duration,
        review_flags=deduped,
    )
