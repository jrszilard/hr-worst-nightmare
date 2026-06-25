"""Load detailed case study descriptions from markdown files.

Reads from data/case-studies/*.md and provides rich context for proposal
generation — much more detailed than the CMS cache summaries.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from backend.core.profile_context import get_profile_context

logger = logging.getLogger(__name__)


@dataclass
class DetailedCaseStudy:
    """A case study with full markdown content for proposal context."""

    slug: str
    title: str
    client: str
    category: str
    lead: str
    content: str  # Full markdown content
    tools: list[str]
    metrics: list[str]

    @property
    def is_complete(self) -> bool:
        """Check if this case study has real content (not TODO placeholders)."""
        return "TODO" not in self.content


def _parse_frontmatter(content: str) -> dict[str, str]:
    """Extract key: value pairs from the markdown header."""
    meta: dict[str, str] = {}
    for line in content.split("\n"):
        if line.startswith("**") and ":**" in line:
            # Parse "**Key:** Value" format
            key_part, _, value = line.partition(":**")
            key = key_part.strip("* ").lower()
            meta[key] = value.strip()
    return meta


def _extract_section(content: str, header: str) -> str:
    """Extract text under a ## header until the next ## header."""
    lines = content.split("\n")
    capturing = False
    result: list[str] = []
    for line in lines:
        if line.strip().lower() == f"## {header.lower()}":
            capturing = True
            continue
        if capturing and line.startswith("## "):
            break
        if capturing:
            result.append(line)
    return "\n".join(result).strip()


def _extract_list_items(section_text: str) -> list[str]:
    """Extract bullet/dash list items from a section."""
    items = []
    for line in section_text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            items.append(stripped[2:].strip())
    return items


def load_case_study(filepath: Path) -> DetailedCaseStudy:
    """Load a single case study from a markdown file."""
    content = filepath.read_text(encoding="utf-8")
    meta = _parse_frontmatter(content)

    # Extract title from first # heading
    title = ""
    for line in content.split("\n"):
        if line.startswith("# ") and not line.startswith("## "):
            title = line[2:].strip()
            break

    # Extract tools and metrics sections
    tools_section = _extract_section(content, "Tools")
    metrics_section = _extract_section(content, "Key Metrics")

    tools = _extract_list_items(tools_section)
    metrics = _extract_list_items(metrics_section)

    slug = filepath.stem

    return DetailedCaseStudy(
        slug=slug,
        title=title or filepath.stem.replace("-", " ").title(),
        client=meta.get("client", "Unknown"),
        category=meta.get("category", "Unknown"),
        lead=meta.get("lead", "Unknown"),
        content=content,
        tools=tools,
        metrics=metrics,
    )


def load_all_case_studies() -> list[DetailedCaseStudy]:
    """Load all case studies from <PROFILE_DIR>/case-studies/*.md.

    Only returns case studies that are complete (no TODO placeholders).
    """
    case_dir = get_profile_context().case_studies_dir
    if not case_dir.exists():
        logger.warning("Case studies directory not found: %s", case_dir)
        return []

    studies = []
    for filepath in sorted(case_dir.glob("*.md")):
        try:
            study = load_case_study(filepath)
            if study.is_complete:
                studies.append(study)
            else:
                logger.debug("Skipping incomplete case study: %s", filepath.name)
        except Exception:
            logger.exception("Failed to load case study: %s", filepath.name)

    logger.info("Loaded %d complete case studies from %s", len(studies), case_dir)
    return studies


def format_case_studies_for_prompt(studies: list[DetailedCaseStudy]) -> str:
    """Format case studies as rich context for the proposal generation prompt."""
    if not studies:
        return "No case studies available."

    parts: list[str] = []
    for cs in studies:
        metrics_str = "\n".join(f"  - {m}" for m in cs.metrics) if cs.metrics else "  No quantified outcomes"
        tools_str = ", ".join(cs.tools) if cs.tools else "No tools listed"

        # Include the full solution/approach sections for rich context
        challenge = _extract_section(cs.content, "Challenge")
        solution = _extract_section(cs.content, "Solution")
        approach = _extract_section(cs.content, "Approach")

        parts.append(
            f"### {cs.title}\n"
            f"**Client:** {cs.client} | **Category:** {cs.category} | **Lead:** {cs.lead}\n"
            f"**Tools:** {tools_str}\n\n"
            f"**Challenge:** {challenge[:300]}{'...' if len(challenge) > 300 else ''}\n\n"
            f"**Solution:** {solution[:500]}{'...' if len(solution) > 500 else ''}\n\n"
            f"{'**Approach:** ' + approach[:300] + '...' if approach and len(approach) > 300 else '**Approach:** ' + approach if approach else ''}\n\n"
            f"**Key Metrics:**\n{metrics_str}\n"
        )
    return "\n---\n".join(parts)
