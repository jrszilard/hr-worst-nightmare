"""Single source of truth for human-sounding writing rules.

These rules are enforced two ways: injected into LLM prompts (advisory) and
applied deterministically by the sanitizer (guaranteed). Keep this module
dependency-free so every other writing module can import it.
"""

from __future__ import annotations

# Punctuation that reads as AI-generated or violates the house style.
FORBIDDEN_CHARS: set[str] = {
    "—",  # — em dash
    "–",  # – en dash
    "→",  # → rightwards arrow
    "➔",  # ➔ heavy wide-headed arrow
    "➜",  # ➜ arrow
    "⇒",  # ⇒ double arrow
}

# Smart-quote / typographic normalisations (map -> ASCII).
SMART_QUOTE_MAP: dict[str, str] = {
    "“": '"', "”": '"',   # " "
    "‘": "'", "’": "'",   # ' '
    "…": "...",                # …
}

# Phrases that flag text as AI-written. Lowercase; matched case-insensitively.
BANNED_CLICHES: list[str] = [
    "delve", "leverage", "in today's fast-paced", "i'm excited to",
    "i am excited to", "robust", "tapestry", "elevate", "seamless",
    "navigate the landscape", "unlock", "game-changer", "synergy",
    "cutting-edge", "in conclusion", "furthermore", "moreover",
    "it is worth noting", "rest assured", "look no further",
    "dive deep", "supercharge", "world-class", "best-in-class",
]

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.models import LoadedProfile


def style_rules_text(profile: "LoadedProfile | None" = None) -> str:
    """Return the advisory style block, with voice/framing drawn from *profile*.

    When *profile* is None (e.g. the deterministic critic), the mechanical rules
    are returned with a neutral voice and no author-specific location/studio.
    """
    location = profile.location if profile and profile.location else ""
    studio = profile.studio if profile and profile.studio else ""
    framing = profile.framing if profile and profile.framing else ""
    voice = profile.voice if profile and profile.voice else ""

    loc = f" from {location}" if location else ""
    voice_line = voice or f"like a real person{loc} writing a quick, confident note"
    if framing:
        framing_clause = framing
    elif studio:
        framing_clause = f"a {studio} partnership"
    else:
        framing_clause = "a direct partnership with you"

    return (
        "WRITING STYLE (follow strictly):\n"
        "- Do NOT use em-dashes, en-dashes, or arrow characters. Use commas, "
        "periods, or the word 'to' instead.\n"
        "- Do NOT use '+' as a stand-in for 'and'.\n"
        f"- Write conversationally and plainly, {voice_line}. No corporate filler.\n"
        f"- Frame work as {framing_clause}, not a faceless vendor.\n"
        "- Avoid these clichés entirely: " + ", ".join(BANNED_CLICHES) + ".\n"
        "- Be confident, not arrogant. Let concrete results carry the message.\n"
    )


# Backwards-compatible neutral export (no author PII).
STYLE_RULES: str = style_rules_text()
