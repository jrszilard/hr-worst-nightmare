"""Tests for the writing style single-source-of-truth (backend.ai.writing.style)."""

from backend.ai.writing import style


def test_forbidden_chars_include_dashes_and_arrows():
    assert "—" in style.FORBIDDEN_CHARS  # em dash
    assert "–" in style.FORBIDDEN_CHARS  # en dash
    assert "→" in style.FORBIDDEN_CHARS  # right arrow


def test_banned_cliches_are_lowercase_and_nonempty():
    assert style.BANNED_CLICHES, "cliché list must not be empty"
    assert all(c == c.lower() for c in style.BANNED_CLICHES)
    assert "leverage" in style.BANNED_CLICHES
    assert "delve" in style.BANNED_CLICHES


def test_style_rules_text_mentions_key_constraints():
    text = style.style_rules_text()
    lowered = text.lower()
    assert "em-dash" in lowered or "em dash" in lowered
    assert "conversational" in lowered


def test_style_rules_inject_profile_location_and_framing():
    from backend.ai.writing.style import style_rules_text
    from backend.core.models import LoadedProfile

    p = LoadedProfile(
        name="A", studio="Acme Studio", positioning="", location="Vermont",
        voice="", framing="", hourly_rate_range=[1, 2], tone="", selling_points=[],
        key_differentiators={}, core_skills=[], adjacent_skills=[], all_skills=[],
    )
    text = style_rules_text(p)
    assert "Vermont" in text
    assert "Acme Studio" in text
    assert "New Hampshire" not in text
    assert "Lakeshore" not in text


def test_style_rules_neutral_without_profile():
    from backend.ai.writing.style import style_rules_text

    text = style_rules_text()
    assert "New Hampshire" not in text
    assert "Lakeshore" not in text
    assert "em-dash" in text  # mechanical rules still present
