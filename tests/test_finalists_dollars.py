from backend.api.finalists import _caps_from
from backend.api.finalists import RunBody


class _Settings:
    connects_per_period = 60
    generation_apps_per_period = 20
    generation_dollars_per_period = 5.0
    per_run_max_apps = 5


def test_caps_from_includes_dollar_cap():
    connects, gen, per_run, dollars = _caps_from(_Settings(), RunBody())
    assert connects == 60
    assert gen == 20
    assert per_run == 5
    assert dollars == 5.0
