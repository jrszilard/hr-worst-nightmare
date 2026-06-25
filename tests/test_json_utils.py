"""Tests for robust LLM JSON extraction (backend.ai.json_utils)."""

import pytest

from backend.ai.json_utils import extract_json_object


def test_plain_json():
    assert extract_json_object('{"a": 1}') == {"a": 1}


def test_fenced_json_with_lang():
    assert extract_json_object('```json\n{"a": 1, "b": "x"}\n```') == {"a": 1, "b": "x"}


def test_fenced_json_no_lang():
    assert extract_json_object('```\n{"a": 1}\n```') == {"a": 1}


def test_preamble_then_json():
    assert extract_json_object('Here is the JSON:\n{"a": 1}') == {"a": 1}


def test_trailing_text_after_json():
    assert extract_json_object('{"a": 1}\nLet me know if you need more.') == {"a": 1}


def test_broken_raises_valueerror():
    with pytest.raises(ValueError):
        extract_json_object("not json at all {broken")
