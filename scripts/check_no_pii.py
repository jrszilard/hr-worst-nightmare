"""Fail if the configured user's PII leaks into files that ship.

The public repo is the *shipped surface* — code, tests, profile.example, README,
config. It EXCLUDES internal/author-specific files curated out at publish time
(``docs/`` specs+plans, ``CLAUDE.md`` workspace config) and gitignored files
(``data/``, ``.env``).

The identity to scan for is DERIVED AT RUNTIME from the gitignored ``profile.yaml``
(``PROFILE_DIR``, default ``data``), so this guard file holds no literal PII and
adapts to whoever self-hosts. It scans itself too — re-hardcoding an identifier here
would now be caught instead of silently shipped. If ``profile.yaml`` is absent we
cannot know what to protect, so we FAIL CLOSED rather than report a false "clean".

Two tiers:
  * High-sensitivity identifiers (last name, email, phone, LinkedIn handle, website
    domain) -> fail anywhere in the scanned surface.
  * Brand framing (the distinctive words of the studio name) -> fail in source dirs
    only (backend/scripts/frontend); it belongs in profile data now. Not scanned in
    tests/ (a style test may assert the brand's ABSENCE and must name it).

Run before seeding the public repo (which also drops docs/ and CLAUDE.md).
Exit 0 = clean; 1 = PII found (path:line listed); 2 = no profile.yaml (fail closed).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ("backend/", "scripts/", "frontend/")
# Curated out of the public repo, so not scanned. Keep in sync with the publish step.
EXCLUDE_PREFIXES = ("docs/", "CLAUDE.md")
# Studio-name words too generic to fingerprint a person/brand.
_GENERIC_BRAND_WORDS = {
    "studio", "labs", "lab", "llc", "inc", "co", "group", "agency",
    "consulting", "consultancy", "solutions", "the", "and",
}


def _profile_path() -> Path:
    raw = os.environ.get("PROFILE_DIR", "data")
    p = Path(raw)
    return (p if p.is_absolute() else _REPO_ROOT / p) / "profile.yaml"


def _phone_pattern(phone: str) -> str | None:
    """Match a phone number tolerant of separators: 555-555-0100, 555.555.0100, 5555550100."""
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 7:
        return None
    return r"[-.\s]?".join(re.escape(d) for d in digits)


def _build_patterns(profile: dict) -> tuple[list[str], list[str]]:
    """Return (high_sensitivity_patterns, brand_patterns) derived from profile.yaml."""
    high: list[str] = []
    applicant = profile.get("applicant") or {}

    last = str(applicant.get("last_name") or "").strip()
    if last:
        high.append(re.escape(last))

    email = str(applicant.get("email") or "").strip()
    if email:
        high.append(re.escape(email))

    pp = _phone_pattern(str(applicant.get("phone") or ""))
    if pp:
        high.append(pp)

    linkedin = str(applicant.get("linkedin") or "")
    m = re.search(r"linkedin\.com/(?:in|pub)/([^/?\s]+)", linkedin, re.IGNORECASE)
    if m:
        high.append(r"linkedin\.com/(?:in|pub)/" + re.escape(m.group(1)))

    website = str(applicant.get("website") or "")
    domain = re.sub(r"^https?://(www\.)?", "", website).strip("/").split("/")[0]
    if domain:
        high.append(re.escape(domain))

    brand: list[str] = []
    studio = str(profile.get("studio") or "")
    for word in re.findall(r"[A-Za-z][A-Za-z0-9'&-]+", studio):
        if len(word) >= 4 and word.lower() not in _GENERIC_BRAND_WORDS:
            brand.append(re.escape(word))

    return high, brand


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    ).stdout
    return [f for f in out.splitlines() if f]


def main() -> int:
    profile_path = _profile_path()
    if not profile_path.exists():
        print(
            f"PII guard CANNOT VERIFY: no profile.yaml at {profile_path}. "
            "Set PROFILE_DIR or run onboarding. Failing closed.",
            file=sys.stderr,
        )
        return 2

    profile = yaml.safe_load(profile_path.read_text()) or {}
    high_patterns, brand_patterns = _build_patterns(profile)
    if not high_patterns:
        print(
            f"PII guard CANNOT VERIFY: {profile_path} has no identity fields "
            "(applicant.last_name/email/phone/linkedin/website). Failing closed.",
            file=sys.stderr,
        )
        return 2

    high = re.compile("|".join(high_patterns), re.IGNORECASE)
    brand = re.compile("|".join(brand_patterns), re.IGNORECASE) if brand_patterns else None

    failures: list[str] = []
    for path in _tracked_files():
        if path.startswith(EXCLUDE_PREFIXES):
            continue
        # Scan the working tree (what is about to be committed/published), not the
        # index, so edits are reflected without staging. Skip unreadable/binary files.
        try:
            text = (_REPO_ROOT / path).read_text(encoding="utf-8", errors="ignore")
        except (OSError, ValueError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if high.search(line):
                failures.append(f"{path}:{n}: high-sensitivity PII")
            if brand and path.startswith(SOURCE_DIRS) and brand.search(line):
                failures.append(f"{path}:{n}: brand/location in source")

    if failures:
        print("PII guard FAILED:")
        for f in failures:
            print("  " + f)
        return 1
    print("PII guard passed: shipped surface is clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
