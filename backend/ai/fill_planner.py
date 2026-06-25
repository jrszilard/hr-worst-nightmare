"""Hybrid LLM fill-planner: decide values for residual screener dropdowns.

The deterministic ``form_fill.plan_fill`` handles identity/contact, country,
sponsorship/visa, and hard-escalates EEO/consent. This planner runs ONLY on the
residual, non-hard-blocked dropdowns (skill screeners, novel selects) it leaves
``unfilled``. It reasons over the full applicant profile and answers a screener when
the evidence reasonably supports it, attaching a one-line ``reasoning`` + ``confidence``;
unsupported -> ``grounded=False`` -> the field stays unfilled (the human answers it).
Every answer is human-reviewed before submit (never-auto-submit holds). Mirrors
``application_generator``: injectable AsyncAnthropic client + ``record_usage`` for budget.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path

import anthropic
from pydantic import BaseModel

from backend.ai.usage import record_usage
from backend.config import settings
from backend.core.models import ApplicantInfo
from backend.platforms.form_fill import FormField, _match_option

_PROMPTS = Path(__file__).parent / "prompts"
_MODEL = "claude-sonnet-4-6"


class PlannedField(BaseModel):
    """A planner decision for one dropdown field, carried into the apply for review."""

    key: str
    value: str
    reasoning: str = ""
    confidence: float = 0.0
    grounded: bool = False


_SUBMIT_FILL_PLAN_TOOL = {
    "name": "submit_fill_plan",
    "description": "Return the chosen value, reasoning, confidence, and grounded flag "
                   "for each dropdown field key.",
    "input_schema": {
        "type": "object",
        "properties": {
            "fills": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "value": {"type": "string"},
                        "reasoning": {"type": "string"},
                        "confidence": {"type": "number"},
                        "grounded": {"type": "boolean"},
                    },
                    "required": ["key", "value", "reasoning", "confidence", "grounded"],
                },
            },
        },
        "required": ["fills"],
    },
}


@functools.lru_cache(maxsize=4)
def _load_prompt(name: str) -> str:
    return (_PROMPTS / name).read_text(encoding="utf-8")


def _fields_payload(fields: list[FormField]) -> str:
    """JSON list the prompt shows the model: key, label, required, options (None if deferred)."""
    payload = [{"key": f.key, "label": f.label, "required": f.required,
                "options": list(f.options) or None} for f in fields]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _profile_block(applicant: ApplicantInfo) -> str:
    """Plain-text applicant facts the planner may ground on. Real facts only."""
    lines: list[str] = []
    if applicant.skills:
        lines.append("Skills: " + ", ".join(applicant.skills))
    for w in applicant.work_history:
        end = "present" if w.current else (w.end or "?")
        entry = f"Role: {w.title} at {w.company} ({w.start or '?'}–{end})."
        if w.description:
            entry += f" {w.description}"
        lines.append(entry.strip())
    for e in applicant.education:
        deg = " ".join(p for p in (e.degree, e.field) if p)
        lines.append(f"Education: {deg} from {e.school} "
                     f"({e.start or '?'}–{e.end or '?'})".strip())
    if applicant.work_authorization:
        lines.append(f"Work authorization: {applicant.work_authorization}")
    lines.append("Needs visa sponsorship: " + ("yes" if applicant.needs_sponsorship else "no"))
    if applicant.country:
        lines.append(f"Country: {applicant.country}")
    return "\n".join(lines) or "(no structured facts provided)"


def _screening_block(artifact: dict) -> str:
    """Pre-written screening Q&A the planner can reuse for a matching dropdown."""
    qas = artifact.get("screening_answers") or []
    if not qas:
        return "(none)"
    return "\n".join(f"Q: {qa.get('question', '')}\nA: {qa.get('answer', '')}" for qa in qas)


def _parse_plan(tool_input: dict, fields: list[FormField]) -> list[PlannedField]:
    """Validate the model's submit_fill_plan input into PlannedFields (anti-fabrication).

    Drops entries whose key was not asked about (invented field) or whose value is empty.
    When a field has KNOWN options, snaps the value to the matching on-page option (so the
    engine's native select gets the exact label) or, if nothing matches, forces
    ``grounded=False`` so the field escalates rather than fills a non-existent option."""
    by_key = {f.key: f for f in fields}
    out: list[PlannedField] = []
    for raw in (tool_input or {}).get("fills", []):
        if not isinstance(raw, dict):
            continue
        field = by_key.get(raw.get("key"))
        if field is None:
            continue
        value = raw.get("value")
        if not isinstance(value, str) or not value.strip():
            continue
        grounded = bool(raw.get("grounded", False))
        if grounded and field.options:               # known options -> snap or escalate
            match = _match_option(value, field.options)
            if match is None:
                grounded = False
            else:
                value = match
        try:
            confidence = float(raw.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        out.append(PlannedField(key=field.key, value=value,
                                reasoning=str(raw.get("reasoning", "")),
                                confidence=confidence, grounded=grounded))
    return out


async def plan_dropdown_fields(
    fields: list[FormField],
    applicant: ApplicantInfo,
    artifact: dict,
    *,
    client: anthropic.AsyncAnthropic | None = None,
) -> list[PlannedField]:
    """Reason-ground a value for each residual dropdown. One LLM call; ``[]`` if no fields.

    Caller (apply_driver) passes ONLY the non-hard-blocked dropdowns (EEO/consent/identity
    are filtered out via form_fill.is_planner_eligible before this is called). Uses only the
    ``grounded`` entries; everything else stays unfilled for the human. Mirrors
    application_generator: injectable client, record_usage for budget."""
    if not fields:
        return []
    if client is None:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    prompt = _load_prompt("fill_planner.txt").format(
        name=applicant.full_name or "the applicant",
        profile_block=_profile_block(applicant),
        job_title=artifact.get("job_title") or "(unspecified)",
        company=artifact.get("company") or "(unspecified)",
        screening_answers=_screening_block(artifact),
        fields_json=_fields_payload(fields),
    )
    response = await client.messages.create(
        model=_MODEL, max_tokens=1200,
        tools=[_SUBMIT_FILL_PLAN_TOOL],
        tool_choice={"type": "tool", "name": "submit_fill_plan"},
        messages=[{"role": "user", "content": prompt}],
    )
    record_usage(_MODEL, response)

    block = next((b for b in (response.content or [])
                  if getattr(b, "type", None) == "tool_use"), None)
    tool_input = getattr(block, "input", {}) if block is not None else {}
    return _parse_plan(tool_input, fields)
