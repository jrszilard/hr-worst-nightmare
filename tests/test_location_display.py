"""Regression tests for _display_location: no garbled location fragments.

Complex board location strings (pipe-separated offices, parenthetical
"(Travel-Required)"/"(US/Canada)" qualifiers) were being comma-split and
rejoined into fragments like "or NS Only)". The display should surface clean
US-eligible segments only, never a fragment.
"""

import pytest

from backend.api import jobs as jobs_api


class _FakeJob:
    def __init__(self, location, platform="greenhouse"):
        self.platform_meta = {"location": location}
        self.client_location = None
        self.platform = platform


def _disp(location):
    return jobs_api._display_location(_FakeJob(location))


def test_pipe_separated_offices_keep_clean_us_segments():
    out = _disp("Remote-Friendly (Travel-Required) | San Francisco, CA | Seattle, WA")
    assert out == "San Francisco, CA; Seattle, WA"


def test_no_garbled_fragments_or_stray_parens():
    out = _disp("New York, San Francisco, Seattle, or Remote (US/Canada)")
    assert ")" not in out
    assert "NS Only" not in out
    assert "Canada" not in out
    assert "New York" in out


def test_parenthetical_only_qualifier_does_not_leave_a_fragment():
    out = _disp("Remote (US Only or NS Only)")
    assert "NS Only" not in out
    assert ")" not in out
    assert out  # non-empty, US-eligible


def test_semicolon_separated_us_offices_preserved():
    out = _disp("San Francisco, CA; New York, NY; Remote - US")
    assert out == "San Francisco, CA; New York, NY; Remote - US"


def test_duplicate_segments_collapsed():
    out = _disp("San Francisco, CA | San Francisco, CA | New York, NY")
    assert out == "San Francisco, CA; New York, NY"


def test_comma_inside_parentheses_does_not_fragment():
    # The real Instacart case: a comma inside the parenthetical qualifier must not
    # be treated as a location-list separator.
    out = _disp("United States - Remote (US Only, or NS Only)")
    assert "NS Only" not in out
    assert "(" not in out and ")" not in out
    assert "United States" in out


def test_bare_remote_paren_comma_collapses_cleanly():
    out = _disp("Remote (US Only, or NS Only)")
    assert "NS Only" not in out
    assert ")" not in out
    assert out  # non-empty
