"""Deterministic apply orchestration over a BrowserEngine.

Drives a hosted ATS form: snapshot the fields, decide values via form_fill.plan_fill,
emit engine ops, then hand off to the human. Never clicks a final submit — the terminal
op on a successful fill is engine.await_human(...); on error the engine is closed and no
submit is ever clicked.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from backend.core.models import ApplicantInfo
from backend.core.platform import SubmitResult
from backend.ai.fill_planner import plan_dropdown_fields
from backend.platforms.browser.engine import BrowserEngine
from backend.platforms.form_fill import (
    FormField, extract_screening_questions, is_planner_eligible, plan_fill,
)

if TYPE_CHECKING:
    import anthropic

logger = logging.getLogger(__name__)


def _fuzzy_match_option(intended: str, options: list[str]) -> str | None:
    """Deterministically map an intended value onto one of the live options, else None.

    Mirrors form_fill._match_option: exact (case-insensitive), then a leading yes/no word
    ("No" -> "No, I don't"), then substring containment. Used once to reconcile a select
    no_match before escalating the field to the human."""
    want = " ".join((intended or "").lower().split())
    if not want:
        return None
    norm = [(o, " ".join((o or "").lower().split())) for o in options]
    for o, no in norm:                       # exact
        if no == want:
            return o
    parts = want.split()
    first = parts[0].strip(",.;:!?") if parts else ""   # "yes," (planner essay prefix) -> "yes"
    if first in ("yes", "no"):               # leading yes/no word
        for o, no in norm:
            if no == first or no.startswith(first + ","):
                return o
    for o, no in norm:                       # substring
        if want in no:
            return o
    return None


def _to_apply_form_url(url: str) -> str:
    """Resolve a job URL to its fillable application form.

    Ashby's bare job URL is a description page; the form lives at ``/application``.

    Some Greenhouse boards (e.g. Coinbase #2605) render the listing page with an "Apply for
    this job" button that lazy-loads the application; the driver would snapshot an empty page.
    The ``/embed/job_app`` endpoint is the canonical standalone form, so a
    ``<host>/<company>/jobs/<id>`` listing URL is rewritten to it. Boards that already render
    the form inline (e.g. Affirm) still load fine via the embed form, so the rewrite is uniform.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host.endswith("ashbyhq.com"):
        trimmed = url.split("?", 1)[0].rstrip("/")
        if not trimmed.endswith("/application"):
            return trimmed + "/application"
        return url
    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io"):
        if parsed.path.startswith("/embed/"):
            return url  # already the embed form
        m = re.match(r"^/([^/]+)/jobs/(\d+)", parsed.path)
        if m:
            company, jid = m.group(1), m.group(2)
            return (f"https://{host}/embed/job_app"
                    f"?token={jid}&for={company}&gh_jid={jid}")
    return url


async def discover_questions(engine: BrowserEngine, *, url: str) -> list[str]:
    """Read the hosted form and return safe role-specific questions for generation.

    Consumes the engine: it is always closed before returning.
    """
    try:
        await engine.goto(_to_apply_form_url(url))
        snap = await engine.snapshot()
        return extract_screening_questions(snap.fields)
    finally:
        await engine.close()


async def fill_application(engine: BrowserEngine, *, url: str, artifact: dict,
                           applicant: ApplicantInfo,
                           client: "anthropic.AsyncAnthropic | None" = None) -> SubmitResult:
    """Fill the form via engine ops, then hand off to the human. Never submits.

    Consumes the engine: on error it is closed; on success it is left to the engine's
    await_human (which decides whether to keep the browser open for the human). On
    success the terminal op is engine.await_human(...); a final submit is never clicked.
    """
    try:
        await engine.goto(_to_apply_form_url(url))
        snap = await engine.snapshot()
        plan, unfilled = plan_fill(snap.fields, artifact, applicant)

        # B2: hybrid LLM planner — reason-ground the residual, non-hard-blocked dropdowns.
        planner_notes: list[tuple[FormField, dict]] = []   # (FormField, note dict) for fields the planner set
        eligible = [f for f in unfilled if is_planner_eligible(f)]
        if eligible:
            planned = await plan_dropdown_fields(eligible, applicant, artifact, client=client)
            by_eligible = {f.key: f for f in eligible}
            for pf in planned:
                if not pf.grounded:
                    continue
                field = by_eligible.get(pf.key)
                if field is None:
                    continue
                plan.selects[field.key] = pf.value
                if field in unfilled:
                    unfilled.remove(field)
                planner_notes.append((field, {
                    "field": field.label, "value": pf.value,
                    "reasoning": pf.reasoning, "confidence": pf.confidence}))

        for key, value in plan.values.items():
            await engine.fill(key, value)
        by_key = {f.key: f for f in snap.fields}
        for key, option in plan.selects.items():
            outcome = await engine.select(key, option)
            if outcome.ok:
                continue
            match = _fuzzy_match_option(option, outcome.available_options)
            if match is not None:
                outcome = await engine.select(key, match)
                if outcome.ok:
                    continue
            field = by_key.get(key)
            if field is not None and field not in unfilled:
                unfilled.append(field)
        unconfirmed: list[str] = []
        for key, path in plan.files.items():
            if not await engine.upload(key, path):
                unconfirmed.append(key)

        reasons: list[str] = []
        if unfilled:
            reasons.append("manual fields: " + ", ".join(f.label or f.id for f in unfilled))
        if unconfirmed:
            reasons.append("resume upload unconfirmed: " + ", ".join(unconfirmed))
        if await engine.has_visible_captcha():
            reasons.append("captcha challenge")

        detail = ("filled; awaiting human submit"
                  + (f" ({'; '.join(reasons)})" if reasons else ""))
        fill_notes = [note for f, note in planner_notes if f not in unfilled]
    except Exception as exc:  # noqa: BLE001 — never blind-submit on error
        logger.exception("apply fill failed for %s", url)
        try:
            await engine.close()
        except Exception:  # noqa: BLE001
            logger.warning("engine close failed after fill error")
        return SubmitResult(filled=False, submitted=False, detail=f"error: {exc}")

    # Fills succeeded — hand off to the human (best-effort; the form is filled either way).
    # Teardown is the engine's own decision: await_human() is where each engine applies its
    # keep-open policy (Playwright leaves a launched browser open for the human; AiInBrowser
    # releases its MCP control bridge). fill_application MUST NOT close here — an engine-
    # agnostic close would slam shut a kept-open assisted review window before the human submits.
    try:
        await engine.await_human(detail)
    except Exception:  # noqa: BLE001
        logger.warning("await_human handoff failed after a successful fill")
    return SubmitResult(filled=True, submitted=False, detail=detail, fill_notes=fill_notes)
