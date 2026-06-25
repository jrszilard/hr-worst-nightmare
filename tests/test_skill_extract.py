from backend.core.skill_extract import extract_skills


VOCAB = ["Python", "SQL", "Power BI", "Claude API", "Pandas", "C++"]


def test_matches_vocab_case_insensitive():
    text = "We need strong python and sql skills, plus pandas."
    assert extract_skills(text, VOCAB) == ["Python", "SQL", "Pandas"]


def test_multiword_skill_matches():
    assert extract_skills("Experience with Power BI dashboards", VOCAB) == ["Power BI"]


def test_word_boundary_no_partial():
    # "scripting" must not match "C++"? (C++ has special chars) and "pythonic" not Python
    assert extract_skills("pythonic scripting", VOCAB) == []


def test_empty_text_returns_empty():
    assert extract_skills("", VOCAB) == []
    assert extract_skills(None, VOCAB) == []


def test_dedup_preserves_vocab_order():
    text = "SQL SQL python"
    assert extract_skills(text, VOCAB) == ["Python", "SQL"]
