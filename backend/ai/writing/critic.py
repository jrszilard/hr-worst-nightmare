"""Second-pass LLM critic that rewrites AI-sounding text into human prose.

Honesty-bound: the prompt forbids adding any new facts, names, numbers, or
claims. On any failure the original text is returned unchanged with
``available=False`` so the pipeline never blocks and never emits raw text.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import anthropic

from backend.ai.json_utils import extract_json_object
from backend.ai.usage import record_usage
from backend.ai.writing.style import style_rules_text
from backend.config import settings

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-6"

_PROMPT = (
    "You rewrite a draft so it reads as written by a real person, not an AI. "
    "Do NOT add, invent, or embellish any facts, names, numbers, companies, or "
    "claims. Only adjust wording, rhythm, and punctuation. Preserve meaning.\n\n"
    "{style_rules}\n"
    "DRAFT:\n{draft}\n\n"
    "Respond with ONLY a JSON object: "
    '{{"rewritten_text": "<text>", "changed": <true|false>, "notes": "<short>"}}'
)


@dataclass
class CriticReport:
    available: bool   # False -> LLM failed, original text returned
    rewritten: bool   # True -> critic changed the text
    notes: str | None = None


async def critique_and_rewrite(
    text: str,
    client: anthropic.AsyncAnthropic | None = None,
) -> tuple[str, CriticReport]:
    """Rewrite *text* to remove AI tells. Returns (text, report). Never raises."""
    if not text.strip():
        return text, CriticReport(available=True, rewritten=False, notes="empty")

    if client is None:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    message = _PROMPT.format(style_rules=style_rules_text(), draft=text)
    try:
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": message}],
        )
        record_usage(_MODEL, response)
        raw = response.content[0].text
        data = extract_json_object(raw)
        rewritten = data["rewritten_text"]
        if not isinstance(rewritten, str) or not rewritten.strip():
            raise ValueError("empty rewritten_text")
        return rewritten, CriticReport(
            available=True,
            rewritten=bool(data.get("changed", True)),
            notes=data.get("notes"),
        )
    except Exception as exc:  # noqa: BLE001 - fail safe, never block the pipeline
        logger.warning("Critic pass unavailable, using original text: %s", exc)
        return text, CriticReport(available=False, rewritten=False, notes=str(exc))
