"""Read onboarding inputs into plain text. Every reader degrades gracefully:
a missing/blocked/unsupported source yields empty output, never an exception.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


def read_resume_text(path: Path) -> str:
    """Extract text from a résumé PDF; return '' if missing/unreadable."""
    if not Path(path).exists():
        return ""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception:
        logger.exception("Could not read résumé PDF: %s", path)
        return ""


def read_links(path: Path) -> list[str]:
    """Parse links.txt: one URL per line, blanks ignored."""
    if not Path(path).exists():
        return []
    return [ln.strip() for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]


def fetch_url(url: str, *, client: httpx.Client | None = None) -> str:
    """Best-effort GET; return visible text or '' on any failure/login wall."""
    own = client is None
    client = client or httpx.Client(timeout=10.0, follow_redirects=True)
    try:
        resp = client.get(url, headers={"User-Agent": "Mozilla/5.0 (onboarding)"})
        if resp.status_code != 200 or not resp.text:
            return ""
        text = _TAG_RE.sub(" ", resp.text)
        return re.sub(r"\s+", " ", text).strip()
    except Exception:
        logger.info("Could not fetch %s (continuing without it)", url)
        return ""
    finally:
        if own:
            client.close()


def read_work_samples(directory: Path) -> list[tuple[str, str]]:
    """Read *.md/*.txt/*.pdf work samples as (filename, text)."""
    directory = Path(directory)
    if not directory.exists():
        return []
    out: list[tuple[str, str]] = []
    for fp in sorted(directory.iterdir()):
        if fp.suffix.lower() in {".md", ".txt"}:
            out.append((fp.name, fp.read_text(encoding="utf-8", errors="ignore")))
        elif fp.suffix.lower() == ".pdf":
            out.append((fp.name, read_resume_text(fp)))
    return out


@dataclass
class IngestResult:
    resume_text: str = ""
    pages: dict[str, str] = field(default_factory=dict)   # url -> text ("" if blocked)
    samples: list[tuple[str, str]] = field(default_factory=list)
    blocked_urls: list[str] = field(default_factory=list)


def gather_inputs(ctx, *, client: httpx.Client | None = None) -> IngestResult:
    """Read every input under ctx.inputs_dir into an IngestResult."""
    result = IngestResult()
    result.resume_text = read_resume_text(ctx.inputs_dir / "resume.pdf")
    for url in read_links(ctx.inputs_dir / "links.txt"):
        text = fetch_url(url, client=client)
        result.pages[url] = text
        if not text:
            result.blocked_urls.append(url)
    result.samples = read_work_samples(ctx.inputs_dir / "work-samples")
    return result
