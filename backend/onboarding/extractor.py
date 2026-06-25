"""Turn ingested text into a structured profile draft via one Claude call.

Anti-fabrication: the prompt forbids inventing employers/titles/dates/metrics and
requires uncertain or missing facts to be listed under ``needs_review`` instead of
guessed. Reuses the token/dollar metering via record_usage.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import anthropic

from backend.ai.json_utils import extract_json_object
from backend.ai.usage import record_usage
from backend.config import settings
from backend.onboarding.ingest import IngestResult

_MODEL = "claude-sonnet-4-6"

_PROMPT = """You build a freelancer profile from real source material.

HONESTY (critical): Use ONLY facts present in the SOURCES below. Do NOT invent
employers, titles, dates, metrics, or skills. If something is missing or unclear
(e.g. a web page was blocked), leave that field blank/empty and add a short note
to "needs_review" instead of guessing.

Return ONLY a JSON object with this exact shape:
{{
  "profile": {{
    "name": "first name", "studio": "", "positioning": "one sentence",
    "location": "", "framing": "", "tone": "", "selling_points": [],
    "key_differentiators": {{"<category>": {{"description": "", "skills": []}}}},
    "applicant": {{
      "first_name": "", "last_name": "", "email": "", "phone": "",
      "linkedin": "", "website": "", "country": "", "work_authorization": "",
      "work_history": [{{"title":"","company":"","location":"","start":"","end":null,"description":""}}],
      "education": [{{"school":"","degree":"","field":"","start":"","end":""}}]
    }}
  }},
  "case_studies": [{{"slug":"kebab-case","title":"","client":"","category":"","lead":"","challenge":"","solution":"","tools":[],"metrics":[]}}],
  "needs_review": ["short notes about gaps or low-confidence fields"]
}}

SOURCES:
=== RESUME ===
{resume}

=== WEB PAGES ===
{pages}

=== WORK SAMPLES ===
{samples}
"""


@dataclass
class ExtractionResult:
    profile: dict = field(default_factory=dict)
    case_studies: list[dict] = field(default_factory=list)
    needs_review: list[str] = field(default_factory=list)


def _render_pages(ingest: IngestResult) -> str:
    if not ingest.pages:
        return "(none)"
    blocks = []
    for url, text in ingest.pages.items():
        blocks.append(f"[{url}]\n{text[:4000] if text else '(blocked / no content)'}")
    return "\n\n".join(blocks)


def _render_samples(ingest: IngestResult) -> str:
    if not ingest.samples:
        return "(none)"
    return "\n\n".join(f"[{name}]\n{text[:4000]}" for name, text in ingest.samples)


async def extract_profile(
    ingest: IngestResult, *, client: anthropic.AsyncAnthropic | None = None
) -> ExtractionResult:
    if client is None:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    message = _PROMPT.format(
        resume=ingest.resume_text or "(none)",
        pages=_render_pages(ingest),
        samples=_render_samples(ingest),
    )
    response = await client.messages.create(
        model=_MODEL, max_tokens=4000,
        messages=[{"role": "user", "content": message}],
    )
    record_usage(_MODEL, response)
    if not response.content:
        raise ValueError("Claude returned empty content for onboarding extraction")
    data = extract_json_object(response.content[0].text)
    return ExtractionResult(
        profile=data.get("profile", {}) or {},
        case_studies=data.get("case_studies", []) or [],
        needs_review=data.get("needs_review", []) or [],
    )
