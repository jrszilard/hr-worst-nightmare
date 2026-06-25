"""Regression: the conjunction "or" must not read as Oregon (OR).

Instacart posts "Canada - Remote (ON, AB, BC, or NS Only)" — all Canadian
provinces. The ", or " matched the ambiguous Oregon abbreviation, so a
Canada-only role was ingested and displayed as US-eligible.
"""

from backend.core.board_scan import is_us_location


def test_lowercase_or_conjunction_is_not_oregon():
    assert is_us_location("Canada - Remote (ON, AB, BC, or NS Only)") is False
    assert is_us_location("Toronto, or somewhere") is False


def test_real_oregon_abbreviation_still_detected():
    assert is_us_location("Portland, OR") is True
    assert is_us_location("Remote - US (CA, OR, WA)") is True


def test_uppercase_or_conjunction_between_cities_not_oregon():
    # Space-delimited "OR" is not an address token even in upper case.
    assert is_us_location("Dublin OR London") is False
