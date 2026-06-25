"""Robust extraction of a JSON object from an LLM response.

LLMs often wrap JSON in markdown code fences or add a short preamble even when
asked for "JSON only". This tolerates those cases so callers don't silently
fall back. Raises ``json.JSONDecodeError`` (a ``ValueError`` subclass) if no
JSON object can be recovered.
"""

from __future__ import annotations

import json
import re

_FENCE_OPEN = re.compile(r"^```[a-zA-Z0-9]*\s*\n")
_FENCE_CLOSE = re.compile(r"\n```\s*$")


def extract_json_object(raw: str) -> dict:
    """Parse a JSON object from *raw*, tolerating code fences and surrounding prose."""
    s = (raw or "").strip()

    # Strip a leading/trailing markdown code fence if present.
    if s.startswith("```"):
        s = _FENCE_OPEN.sub("", s)
        s = _FENCE_CLOSE.sub("", s).strip()

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # Fall back to the first '{' ... last '}' span (handles preamble/trailing prose).
        start = s.find("{")
        end = s.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(s[start:end + 1])
        raise
