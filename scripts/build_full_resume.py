"""Render the canonical full resume (data/resume/resume.md — REAL employment history,
user-maintained) to a clean PDF via reportlab.

This is distinct from scripts/build_resume.py, which produces the capability-only
data/resume.pdf (no employment history). Use this when a posting needs a resume that
matches the work_history we enter on a Workday "My Experience" page.

Usage:
    python scripts/build_full_resume.py [out.pdf]   # default: data/resume_full.pdf
"""
import re
import sys
from pathlib import Path

from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter as LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from backend.portfolio.profile_loader import get_profile
from backend.core.profile_context import get_profile_context

ROOT = Path(__file__).resolve().parents[1]


def _inline(text: str) -> str:
    """Escape XML metacharacters, then convert **bold** -> <b>bold</b> for reportlab."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)


def build(src: Path | None = None, out_path: Path | None = None) -> Path:
    ctx = get_profile_context()
    src = src or (ctx.root / "resume" / "resume.md")
    out_path = out_path or ctx.resume_full_path
    base = getSampleStyleSheet()
    title = ParagraphStyle("title", parent=base["Title"], fontSize=20, spaceAfter=2, alignment=TA_LEFT)
    subtitle = ParagraphStyle("subtitle", parent=base["Normal"], fontSize=11, textColor="#333333", spaceAfter=2)
    contact = ParagraphStyle("contact", parent=base["Normal"], fontSize=8.5, textColor="#555555", spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=base["Heading2"], fontSize=12, spaceBefore=9, spaceAfter=2, textColor="#1a1a1a")
    h3 = ParagraphStyle("h3", parent=base["Heading3"], fontSize=10.5, spaceBefore=6, spaceAfter=1)
    body = ParagraphStyle("body", parent=base["Normal"], fontSize=9.5, leading=12.5, spaceAfter=3)
    bullet = ParagraphStyle("bullet", parent=body, spaceAfter=1)

    lines = src.read_text().splitlines()
    story: list = []
    pending_bullets: list = []
    seen_title = False

    def flush_bullets() -> None:
        if pending_bullets:
            story.append(
                ListFlowable(
                    [ListItem(Paragraph(_inline(b), bullet), leftIndent=10) for b in pending_bullets],
                    bulletType="bullet",
                    start="•",
                    leftIndent=12,
                )
            )
            pending_bullets.clear()

    for raw in lines:
        line = raw.rstrip()
        if line.strip() == "---":
            flush_bullets()
            continue
        if not line.strip():
            flush_bullets()
            continue
        if line.startswith("# "):
            flush_bullets()
            story.append(Paragraph(_inline(line[2:].strip()), title))
            seen_title = True
            continue
        if line.startswith("## "):
            flush_bullets()
            story.append(Spacer(1, 2))
            story.append(Paragraph(_inline(line[3:].strip()), h2))
            story.append(HRFlowable(width="100%", thickness=0.5, color="#cccccc", spaceBefore=1, spaceAfter=3))
            continue
        if line.startswith("### "):
            flush_bullets()
            story.append(Paragraph(_inline(line[4:].strip()), h3))
            continue
        if line.lstrip().startswith("- "):
            pending_bullets.append(line.lstrip()[2:].strip())
            continue
        # plain paragraph (incl. the **subtitle** and the contact line right after the title)
        flush_bullets()
        is_subtitle = line.startswith("**Forward")
        is_contact = "@" in line and ("·" in line or "|" in line)
        if is_subtitle:
            story.append(Paragraph(_inline(line), subtitle))
        elif is_contact:
            story.append(Paragraph(_inline(line), contact))
        else:
            story.append(Paragraph(_inline(line), body))

    flush_bullets()

    _prof = get_profile()
    _author = (_prof.applicant.full_name if _prof.applicant and _prof.applicant.full_name else _prof.name) or "Resume"
    doc = SimpleDocTemplate(
        str(out_path), pagesize=LETTER,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        title=f"{_author} - Resume", author=_author,
    )
    doc.build(story)
    return out_path


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else get_profile_context().resume_full_path
    print("wrote", build(out_path=out))
