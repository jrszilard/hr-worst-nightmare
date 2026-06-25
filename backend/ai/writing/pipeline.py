"""Orchestrate the writing-quality layer.

Order: scan untrusted posting for traps -> sanitize draft -> (optional) LLM
critic rewrite -> final deterministic sanitize. The final sanitize guarantees
no forbidden punctuation survives even if the critic reintroduced it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import anthropic

from backend.ai.writing.critic import critique_and_rewrite
from backend.ai.writing.injection import TrapFlag, scan_for_traps
from backend.ai.writing.sanitizer import SanitizerReport, sanitize


@dataclass
class WritingReport:
    sanitizer: SanitizerReport = field(default_factory=SanitizerReport)
    traps: list[TrapFlag] = field(default_factory=list)
    critic_available: bool = False
    critic_rewrote: bool = False


async def run_writing_pipeline(
    draft: str,
    *,
    posting_context: str = "",
    client: anthropic.AsyncAnthropic | None = None,
    use_critic: bool = True,
) -> tuple[str, WritingReport]:
    """Clean *draft*, optionally rewrite via the critic, and report findings."""
    traps = scan_for_traps(posting_context)

    clean1, rep1 = sanitize(draft)

    critic_available = False
    critic_rewrote = False
    text = clean1
    if use_critic:
        text, crep = await critique_and_rewrite(clean1, client=client)
        critic_available = crep.available
        critic_rewrote = crep.rewritten

    clean2, rep2 = sanitize(text)

    merged = SanitizerReport(
        punctuation_fixes=rep1.punctuation_fixes + rep2.punctuation_fixes,
        cliches_found=sorted(set(rep1.cliches_found) | set(rep2.cliches_found)),
    )
    return clean2, WritingReport(
        sanitizer=merged,
        traps=traps,
        critic_available=critic_available,
        critic_rewrote=critic_rewrote,
    )
