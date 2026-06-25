"""Generate data/resume.pdf from data/profile.yaml — capability/skills-based, no
fabricated employment history."""
from pathlib import Path
import yaml
from reportlab.lib.pagesizes import letter as LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem

from backend.core.profile_context import get_profile_context

ROOT = Path(__file__).resolve().parents[1]


def build(profile_path: Path | None = None, out_path: Path | None = None) -> Path:
    ctx = get_profile_context()
    profile_path = profile_path or ctx.profile_yaml
    out_path = out_path or ctx.resume_path
    p = yaml.safe_load(profile_path.read_text())
    a = p.get("applicant", {})
    styles = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=styles["Title"], fontSize=20, spaceAfter=2)
    sub = ParagraphStyle("sub", parent=styles["Normal"], fontSize=10, textColor="#555555")
    sec = ParagraphStyle("sec", parent=styles["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4)
    doc = SimpleDocTemplate(str(out_path), pagesize=LETTER,
                            leftMargin=0.8 * inch, rightMargin=0.8 * inch,
                            topMargin=0.7 * inch, bottomMargin=0.7 * inch)
    story = [
        Paragraph(f"{a.get('first_name','')} {a.get('last_name','')}".strip(), h),
        Paragraph(f"{p.get('studio','')} &nbsp;|&nbsp; {a.get('email','')} "
                  f"&nbsp;|&nbsp; {a.get('phone','')}", sub),
        Spacer(1, 8),
        Paragraph("Summary", sec),
        Paragraph(p.get("positioning", ""), styles["Normal"]),
    ]
    sp = p.get("selling_points", [])
    if sp:
        story += [Paragraph("Highlights", sec),
                  ListFlowable([ListItem(Paragraph(s, styles["Normal"])) for s in sp],
                               bulletType="bullet")]
    story.append(Paragraph("Core Competencies", sec))
    for area in (p.get("key_differentiators") or {}).values():
        story.append(Paragraph(f"<b>{area.get('description','')}</b>", styles["Normal"]))
        skills = ", ".join(area.get("skills", []))
        story.append(Paragraph(skills, styles["Normal"]))
        story.append(Spacer(1, 4))
    doc.build(story)
    return out_path


if __name__ == "__main__":
    print("wrote", build())
