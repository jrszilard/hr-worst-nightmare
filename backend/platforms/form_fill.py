"""Pure form-fill planning for ATS application forms.

Given the fields a page exposes plus the generated artifact and applicant identity,
decide each field's value. Two entry points:

- ``plan_fill`` — best-effort: returns a FillPlan plus the list of *required* fields it
  could not fill (custom dropdowns, unmapped questions). The assisted submitter fills
  what it can and escalates the rest (and the CAPTCHA) to the human.
- ``build_fill_plan`` — strict: aborts (FillAbort) if any required field can't be filled.
  Used where a fully-unattended fill is required.

Plan entries are keyed by a stable *selector*: ``#<id>`` when the control has an id,
else the (label) text. The live submitter locates controls by that key.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field as dc_field


from backend.core.models import ApplicantInfo


@dataclass
class FormField:
    label: str
    required: bool = False
    kind: str = "text"  # text | textarea | file | select | combobox | typeahead
    id: str = ""
    name: str = ""
    options: list[str] = dc_field(default_factory=list)
    dynamic_options: bool = False  # combobox whose options are read at select-time
                                    # (ai-in-browser custom widget); plan_fill decides a value by label

    @property
    def key(self) -> str:
        """Stable locator key: '#id' when there's an id, else the label text."""
        return f"#{self.id}" if self.id else self.label


@dataclass
class FillPlan:
    values: dict[str, str] = dc_field(default_factory=dict)    # key -> text value
    files: dict[str, str] = dc_field(default_factory=dict)     # key -> file path
    selects: dict[str, str] = dc_field(default_factory=dict)   # key -> chosen option


@dataclass
class FillAbort:
    reason: str


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def _identity_value(label: str, applicant: ApplicantInfo) -> str | None:
    n = _norm(label)
    if "first name" in n:
        return applicant.first_name
    if "last name" in n:
        return applicant.last_name
    if "preferred name" in n or "maiden name" in n:
        return None  # optional/ambiguous — escalate rather than guess
    if "legal name" in n or "full name" in n or n in ("name", "your name"):
        return applicant.full_name
    if "email" in n:
        return applicant.email
    if "phone" in n:
        return applicant.phone
    if "linkedin" in n:
        return applicant.linkedin or None
    if "github" in n:
        return applicant.github or None
    if "website" in n or "portfolio" in n or "personal site" in n:
        return applicant.website or None
    return None


def _screening_answer(label: str, artifact: dict) -> str | None:
    target = _norm(label)
    if not target:
        return None
    for qa in artifact.get("screening_answers") or []:
        q = _norm(qa.get("question", ""))
        if not q:
            continue
        if q == target:
            return qa.get("answer")
        # Fuzzy substring match only for multi-word phrases, so a short field label
        # ("country", "gender") can't spuriously match inside an unrelated long question.
        shorter = q if len(q) <= len(target) else target
        if len(shorter.split()) >= 4 and (q in target or target in q):
            return qa.get("answer")
    return None


def _is_resume(f: FormField) -> bool:
    n = _norm(f.label + " " + f.id + " " + f.name)
    return "resume" in n or "cv" in n.split()


def _is_cover_letter_file(f: FormField) -> bool:
    n = _norm(f.label + " " + f.id + " " + f.name)
    return "cover_letter" in n or "cover letter" in n


def _extract_company_from_url(url: str | None) -> str:
    """Parse company name from Greenhouse/Lever/Ashby job URLs."""
    if not url:
        return ""
    from urllib.parse import urlparse
    path = urlparse(url).path.strip("/").split("/")
    if len(path) >= 1 and path[0]:
        return path[0]
    return ""


def _sanitize_filename_component(s: str) -> str:
    """Replace spaces and special characters with underscores for safe filenames."""
    return re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_")


def _build_document_filename(applicant: ApplicantInfo, artifact: dict, doc_type: str) -> str:
    """Build a descriptive PDF filename: FirstLast_<company>_<role>_<DocType>.pdf.

    Company leads (after the name) so staged files group by company in the growing
    apply_artifacts folder; the role + doc type keep it descriptive for the hiring manager.
    """
    first = _sanitize_filename_component(applicant.first_name)
    last = _sanitize_filename_component(applicant.last_name)
    title = _sanitize_filename_component(artifact.get("job_title", ""))
    company = _sanitize_filename_component(artifact.get("company", ""))

    parts = [first, last]
    if company:
        parts.append(company)
    if title:
        parts.append(title)
    parts.append(doc_type)
    return "_".join(parts) + ".pdf"


def _generate_cover_letter_pdf(text: str, filename: str | None = None) -> str:
    """Generate a PDF from cover-letter text for file-upload fields."""
    from reportlab.lib.pagesizes import letter as LETTER
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph

    if filename is None:
        filename = "Cover_Letter.pdf"

    tmp_dir = tempfile.mkdtemp()
    path = os.path.join(tmp_dir, filename)

    doc = SimpleDocTemplate(path, pagesize=LETTER)
    styles = getSampleStyleSheet()
    story = [Paragraph(text.replace("\n", "<br/>"), styles["Normal"])]
    doc.build(story)
    return path


def _copy_resume_with_descriptive_name(source_path: str, filename: str) -> str:
    """Copy the pre-built resume to a temp location with a descriptive filename."""
    tmp_dir = tempfile.mkdtemp()
    dest = os.path.join(tmp_dir, filename)
    shutil.copy2(source_path, dest)
    return dest


def _match_option(answer: str, options: list[str]) -> str | None:
    """Pick the option best matching a free-text/yes-no answer, else None."""
    a = _norm(answer)
    if not a:
        return None
    # Exact match
    for o in options:
        if _norm(o) == a:
            return o
    # For Yes/No answers that include explanations, extract the leading word
    first = a.split()[0] if a.split() else ""
    if first in ("yes", "no"):
        for o in options:
            if _norm(o) == first:
                return o
    # Substring match
    for o in options:
        no = _norm(o)
        if no and a in no:
            return o
    return None


_EEO_RE = re.compile(
    r"\b(?:gender|sex|race|ethnic|hispanic|latino|veteran|disability|age|"
    r"transgender|sexual orientation|pronouns?|lgbtq\w*|"
    # Self-identification phrasings carry no demographic noun ("I identify as:",
    # "How do you self-identify?"), so the noun list above missed them and the prompt
    # leaked to the generator (Chime #2708). `identif\w*` after the as/self- anchors so
    # the trailing \b doesn't reject identify/identification. The false-drop direction
    # (a stray "identify as" question merely escalates to manual) is the safe one.
    r"identify as|self.?identif\w*)\b",
    re.I,
)
_DECLINE_RE = re.compile(
    r"decline|prefer not|do not wish|don['’]?t wish|not wish to|not want|"
    r"not.*self.?identif|not to (?:answer|disclose|say)",
    re.I,
)


def _is_eeo(label: str) -> bool:
    return bool(_EEO_RE.search(_norm(label)))


_CONSENT_RE = re.compile(
    r"\b(?:acknowledg\w*|consent|certify|i agree|agree to|"
    r"terms and conditions|terms of (?:service|use)|privacy policy|"
    r"i (?:have )?read|electronic communication|"
    r"authoriz\w* to (?:share|use|contact))\b",
    re.I,
)


def is_planner_eligible(field: FormField) -> bool:
    """True for a residual dropdown the LLM fill-planner may attempt.

    Only dropdown-kind fields reach the planner, and EEO/consent/legal acknowledgements are
    HARD-BLOCKED here so a demographic or a consent question is never sent to the model — the
    human answers those. Skill screeners and novel selects are eligible; the planner's own
    grounding requirement then escalates anything it cannot support from real applicant facts."""
    if field.kind not in ("combobox", "typeahead", "select"):
        return False
    label = field.label
    if _is_eeo(label):
        return False
    if _CONSENT_RE.search(_norm(label)):
        return False
    return True


_ADMIN_FIELD_RE = re.compile(
    r"\b(?:first name|last name|full name|email|phone|resume|cv|cover letter|"
    r"additional information|linkedin|github|website|portfolio|country|address|city|state|"
    r"zip|postal|how did you hear|source|referral|current company)\b",
    re.I,
)
# Always-manual facts: identity / legal / logistics / work-arrangement we answer from structured
# profile data or never auto-answer. These stay manual regardless of phrasing — a question-shape
# exception is unsafe here because shape can't tell a groundable experience prompt ("Describe
# your experience with remote teams") from an ungroundable preference one ("Are you comfortable
# working remote?"), and leaking the latter makes the generator confabulate a work-location /
# work-auth answer on the real form (the PR #13/#16 bug class). The false-drop direction (a
# legit experience question merely escalates to manual) is the safe one, so we keep it.
# `relocat\w*` (not `relocat`) so the group's trailing \b doesn't reject relocate/relocation.
_MANUAL_FACT_RE = re.compile(
    r"\b(?:visa|sponsor|sponsorship|authorized|authorization|work authori[sz]ation|"
    r"relocat\w*|in-person|in office|office|hybrid|remote|interviewed|applied|"
    r"previously|policy|acknowledge|certify|consent|terms|personal preferences|"
    r"salary|compensation|desired pay|pay expectation|expected pay|"
    r"earliest|start date|start working|deadline|timeline)\b",
    re.I,
)
# A "How did you hear about us?" question is rendered by some ATSs (e.g. Greenhouse) as a
# cluster of per-channel inputs, so each channel name becomes a standalone field label.
# These are referral-source attributions, not open-ended questions — the human picks their
# source — so they must never be auto-answered (Twilio #2248 leaked 7 as bogus questions).
_SOURCE_CHANNEL_RE = re.compile(
    r"\b(?:twitter|glassdoor|indeed|ziprecruiter|facebook|instagram|tiktok|youtube|"
    r"reddit|hacker news|built ?in|angellist|wellfound|monster|career fair|job fair|"
    r"job board|word of mouth|trade show|conference|webinar|podcast|newsletter|"
    r"blogs?|social media|employee referral|billboard|outdoor advert|news article|"
    r"media coverage|friend|family|former colleague|someone i know)\b"
    r"|^other$|content \(",
    re.I,
)
# A genuine screening question reads as a question or instruction ("Have you spoken at a
# conference?", "Describe your social-media experience"); a referral-source channel cell is a
# bare noun phrase ("Conference or Event", "Word of mouth from a friend"). Use that shape, not
# label length, to tell them apart — otherwise a long channel label leaks through as a
# fabricated answer (Twilio #2248) or a short real question gets dropped.
_QUESTION_SHAPE_RE = re.compile(
    r"\?$"
    r"|^(?:do|does|did|are|is|was|were|have|has|had|can|could|would|will|should|may|"
    r"why|what|which|how|when|where|who|whom|describe|tell|explain|share|list|provide|"
    r"give|walk|please|select|choose|rate|estimate)\b",
    re.I,
)


def _is_source_channel(label_norm: str) -> bool:
    """True when the label is a referral-source attribution cell (a 'How did you hear about
    us?' channel), which must never be auto-answered. A channel cell names a source and is not
    phrased as a question; a real screener that merely mentions a channel word is kept."""
    if not _SOURCE_CHANNEL_RE.search(label_norm):
        return False
    return not _QUESTION_SHAPE_RE.search(label_norm)


def is_generated_screening_question(field: FormField) -> bool:
    """Return True when a form field should become a Claude screening question.

    Keep this intentionally conservative: only open-ended role/application prompts are
    safe to generate. Identity, resume/cover file uploads, EEO, work-auth, relocation,
    URLs, prior application history, and compliance acknowledgements stay manual unless
    we add explicit structured profile facts for them later.

    Comboboxes (dropdowns) are now allowed if they look like skill/experience
    questions — simple Yes/No options can be matched deterministically after
    generation. Country, visa, and factual/legal dropdowns are still blocked by
    the admin/manual regexes below.
    """
    label = field.label.strip()
    if not label or field.kind in {"file", "select", "typeahead"}:
        return False
    if _is_eeo(label):
        return False
    # Drop the trailing required-marker ("*") before matching so anchored source-channel
    # patterns ("^other$", "content (", "?$") see the real label, not "other *".
    n = _norm(label).rstrip("* ").strip()
    if _ADMIN_FIELD_RE.search(n) or _MANUAL_FACT_RE.search(n) or _is_source_channel(n):
        return False
    return True


def extract_screening_questions(fields: list[FormField]) -> list[str]:
    """Extract de-duplicated, safe-to-generate screening questions from form fields."""
    questions: list[str] = []
    seen: set[str] = set()
    for field in fields:
        if not is_generated_screening_question(field):
            continue
        label = " ".join(field.label.split()).rstrip("*").strip()
        key = _norm(label)
        if key and key not in seen:
            seen.add(key)
            questions.append(label)
    return questions


def _combobox_choice(f: FormField, artifact: dict) -> str | None:
    """Choose a dropdown option for a combobox field, or None if no confident match (caller escalates)."""
    if _is_eeo(f.label):
        for o in f.options:
            if _DECLINE_RE.search(o):
                return o
        return None  # no decline option present -> escalate to human
    ans = _screening_answer(f.label, artifact)
    if ans is None:
        return None
    return _match_option(ans, f.options)


def _dynamic_combobox_value(f: FormField, artifact: dict, applicant: ApplicantInfo) -> str | None:
    """Value for an OPTION-LESS custom combobox (ai-in-browser slice 2a). The executor
    matches it against the live options at select-time, so we return a raw value, not an
    option. EEO -> None (never guess a demographic; without options we can't even see the
    'decline' choice). Mirrors _combobox_choice/_combobox_fallback intent without options."""
    if _is_eeo(f.label):
        return None
    ans = _screening_answer(f.label, artifact)
    # Only a SHORT, option-like answer ("Yes", "No", "5+") can be a dropdown value.
    # A prose answer (written for open-text questions) would never match the live option
    # list -- and jamming it in types a paragraph into the dropdown -- so defer it to the
    # LLM planner (which derives the short option from the same prose). Threshold is small;
    # erring toward deferring is safe (the planner backstops).
    if ans is not None and len(ans.split()) <= 4:
        return ans
    n = _norm(f.label)
    if "country" in n:
        return applicant.country or None
    if "sponsor" in n or "visa" in n:
        return "No"
    if "previously" in n or "worked at" in n or "consulted for" in n:
        return "No"
    if "employment agreement" in n or "post-employment" in n or "restriction" in n:
        return "No"
    return None


def _combobox_fallback(f: FormField, applicant: ApplicantInfo) -> str | None:
    """Deterministic fallback for common combobox patterns not caught by screening answers."""
    n = _norm(f.label)
    opts = f.options

    # Country / location of residence
    if "country" in n:
        country = _norm(applicant.country)
        if country:
            for o in opts:
                no = _norm(o)
                if no == country or country in no:
                    return o
        # If no country match, try "No" for "Located Elsewhere" style questions
        if "located" in n:
            for o in opts:
                if _norm(o) == "no":
                    return o
        return None

    # Visa / sponsorship — default to No for US-based applicants
    if "sponsor" in n or "visa" in n:
        for o in opts:
            if _norm(o) == "no":
                return o
        return None

    # Previously worked at / consulted for — default No
    if "previously" in n or "worked at" in n or "consulted for" in n:
        for o in opts:
            if _norm(o) == "no":
                return o
        return None

    # Employment agreements / post-employment restrictions — default No
    if "employment agreement" in n or "post-employment" in n or "restriction" in n:
        for o in opts:
            if _norm(o) == "no":
                return o
        return None

    return None


def plan_fill(fields: list[FormField], artifact: dict,
              applicant: ApplicantInfo) -> tuple[FillPlan, list[FormField]]:
    """Best-effort fill. Returns (plan, unfilled_required).

    Never raises/aborts. ``unfilled_required`` lists required fields we could not map
    (custom widgets, unknown questions, missing resume) — the caller escalates those.
    """
    plan = FillPlan()
    unfilled: list[FormField] = []
    cover = artifact.get("cover_letter") or ""

    for f in fields:
        n = _norm(f.label)

        if f.kind == "combobox" and f.options:
            choice = _combobox_choice(f, artifact)
            if choice is not None:
                plan.selects[f.key] = choice
            else:
                fallback = _combobox_fallback(f, applicant)
                if fallback is not None:
                    plan.selects[f.key] = fallback
                elif f.required:
                    unfilled.append(f)
            continue

        if f.kind == "combobox" and f.dynamic_options:  # ai-in-browser custom: value matched live
            value = _dynamic_combobox_value(f, artifact, applicant)
            if value is not None:
                plan.selects[f.key] = value
            elif f.required:
                unfilled.append(f)
            continue

        if f.kind == "combobox":  # empty-options, non-dynamic (e.g. unreadable Playwright dropdown):
            if f.required:                              # preserve master behavior — escalate to the human
                unfilled.append(f)
            continue

        if f.kind == "typeahead":  # async type-ahead: never auto-filled — hand off to the human
            if f.required:
                unfilled.append(f)
            continue

        if f.kind == "file":
            if _is_resume(f):
                # Prefer a path the caller already staged (the assisted-apply endpoint stages the
                # full résumé into apply_artifacts/), so the upload escalation names that exact
                # file; otherwise copy the configured résumé to a descriptive temp path.
                staged = artifact.get("resume_path")
                if staged:
                    plan.files[f.key] = staged
                elif applicant.resume_path:
                    filename = _build_document_filename(applicant, artifact, "Resume")
                    plan.files[f.key] = _copy_resume_with_descriptive_name(
                        applicant.resume_path, filename
                    )
                elif f.required:
                    unfilled.append(f)
            elif _is_cover_letter_file(f):
                staged = artifact.get("cover_letter_pdf_path")
                if staged:
                    plan.files[f.key] = staged
                elif cover:
                    filename = _build_document_filename(applicant, artifact, "Cover_Letter")
                    plan.files[f.key] = _generate_cover_letter_pdf(cover, filename)
                elif f.required:
                    unfilled.append(f)
            elif f.required:
                unfilled.append(f)
            continue

        ident = _identity_value(f.label, applicant)
        if ident:
            plan.values[f.key] = ident
            continue

        if "cover letter" in n or "additional information" in n:
            if cover:
                plan.values[f.key] = cover
            elif f.required:
                unfilled.append(f)
            continue

        # Defense in depth behind the generation-time gate: a free-text EEO/self-ID field must
        # never receive a stored or generated answer (the combobox path auto-declines; a
        # free-text demographic prompt has no decline option, so it escalates to the human).
        # Guards against any self-ID phrasing that slips past _EEO_RE at generation time.
        if _is_eeo(f.label):
            if f.required:
                unfilled.append(f)
            continue

        ans = _screening_answer(f.label, artifact)
        if ans:
            plan.values[f.key] = ans
            continue

        if f.required:
            unfilled.append(f)
        # optional unmapped -> skip silently

    return plan, unfilled


def build_fill_plan(fields: list[FormField], artifact: dict,
                    applicant: ApplicantInfo) -> FillPlan | FillAbort:
    """Strict fill: abort if any required field can't be filled."""
    plan, unfilled = plan_fill(fields, artifact, applicant)
    if unfilled:
        f = unfilled[0]
        if f.kind == "file" and _is_resume(f):
            return FillAbort(reason=f"resume required but no resume_path: {f.label}")
        return FillAbort(reason=f"unmapped required field: {f.label}")
    return plan
