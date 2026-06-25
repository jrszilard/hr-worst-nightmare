"""The publish guard derives the identity it scans for from the gitignored
profile.yaml, so the guard file itself ships with NO literal PII, and it reports a
clean shipped surface.

Regression: the previous guard hardcoded the author's surname, phone, domain, and
LinkedIn handle as scan patterns and excluded ITSELF from the scan, so it could not
catch its own leak. The fix derives those patterns at runtime from profile.yaml.

These tests target the *real* author profile at ``data/profile.yaml`` — the thing
that must never leak — not the synthetic ``tests/fixtures/profile`` that conftest
points PROFILE_DIR at (its placeholder values intentionally pepper the shipped tree).
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts" / "check_no_pii.py"
REAL_PROFILE = ROOT / "data" / "profile.yaml"


def _identity_values() -> list[str]:
    """The literal identity strings from the real profile that must NOT ship."""
    profile = yaml.safe_load(REAL_PROFILE.read_text()) or {}
    applicant = profile.get("applicant") or {}
    values: list[str] = []

    if applicant.get("last_name"):
        values.append(str(applicant["last_name"]))
    if applicant.get("email"):
        values.append(str(applicant["email"]))
    if applicant.get("phone"):
        phone = str(applicant["phone"])
        digits = "".join(ch for ch in phone if ch.isdigit())
        values.append(phone)
        if digits:
            values.append(digits)

    website = str(applicant.get("website") or "")
    domain = re.sub(r"^https?://(www\.)?", "", website).strip("/").split("/")[0]
    if domain:
        values.append(domain)

    linkedin = str(applicant.get("linkedin") or "")
    m = re.search(r"linkedin\.com/(?:in|pub)/([^/?\s]+)", linkedin, re.IGNORECASE)
    if m:
        values.append(m.group(1))

    return [v for v in values if v]


requires_real_profile = pytest.mark.skipif(
    not REAL_PROFILE.exists(),
    reason="no data/profile.yaml; author identity scan not applicable in a fresh clone",
)


@requires_real_profile
def test_guard_source_contains_no_literal_pii():
    source = GUARD.read_text()
    leaked = [v for v in _identity_values() if v in source]
    assert not leaked, f"guard source embeds literal PII (derive it from profile.yaml): {leaked}"


@requires_real_profile
def test_no_pii_guard_passes_on_clean_tree():
    # Force the guard at the real profile; conftest overrides PROFILE_DIR to the fixture.
    env = {**os.environ, "PROFILE_DIR": "data"}
    result = subprocess.run(
        [sys.executable, "scripts/check_no_pii.py"],
        cwd=ROOT, capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
