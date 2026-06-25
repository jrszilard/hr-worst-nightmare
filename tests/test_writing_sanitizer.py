"""Tests for the deterministic sanitizer (backend.ai.writing.sanitizer)."""

from backend.ai.writing.sanitizer import sanitize, SanitizerReport


def test_em_dash_replaced_with_comma():
    clean, report = sanitize("I build dashboards — fast and clean.")
    assert "—" not in clean
    assert clean == "I build dashboards, fast and clean."
    assert report.changed


def test_arrow_replaced_with_to():
    clean, report = sanitize("Raw data → insight.")
    assert "→" not in clean
    assert "to" in clean
    assert report.changed


def test_plus_conjunction_replaced_with_and():
    clean, _ = sanitize("Python + SQL skills")
    assert "+" not in clean
    assert "Python and SQL skills" == clean


def test_smart_quotes_normalised():
    clean, _ = sanitize("“Hello” ‘world’…")
    assert clean == '"Hello" \'world\'...'


def test_cliches_are_flagged_not_removed():
    clean, report = sanitize("I will leverage my robust skills.")
    assert "leverage" in clean  # prose is preserved
    assert "leverage" in report.cliches_found
    assert "robust" in report.cliches_found


def test_clean_text_is_idempotent():
    clean1, report1 = sanitize("A plain, clean sentence about data work.")
    clean2, report2 = sanitize(clean1)
    assert clean1 == clean2
    assert not report2.punctuation_fixes


def test_empty_input_is_safe():
    clean, report = sanitize("")
    assert clean == ""
    assert not report.changed
