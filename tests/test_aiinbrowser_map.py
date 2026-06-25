import json

import pytest

from backend.platforms.browser.aiinbrowser_map import (
    observation_to_fields,
    parse_observation,
    resolve_ref,
)

_OBS = {
    "observationId": "o1",
    "url": "http://127.0.0.1/form",
    "title": "Form",
    "captchaPresent": False,
    "elements": [
        {"ref": "e1", "role": "textbox", "name": "First Name"},
        {"ref": "e2", "role": "combobox", "name": "Country", "options": ["United States", "Germany"]},
        {"ref": "e3", "role": "button", "name": "Submit Application"},
    ],
    "textDigest": "a form",
}


def test_parse_observation_round_trips_json():
    assert parse_observation(json.dumps(_OBS))["observationId"] == "o1"


def test_observation_to_fields_maps_fields_and_excludes_buttons():
    fields = observation_to_fields(_OBS)
    assert [(f.label, f.kind, f.options) for f in fields] == [
        ("First Name", "text", []),
        ("Country", "combobox", ["United States", "Germany"]),
    ]
    assert [f.key for f in fields] == ["First Name", "Country"]


def test_combobox_field_carries_options_for_plan_fill():
    country = observation_to_fields(_OBS)[1]
    assert country.kind == "combobox"
    assert country.options == ["United States", "Germany"]


def test_resolve_ref_matches_by_accessible_name():
    assert resolve_ref(_OBS, "First Name") == ("e1", "o1")
    assert resolve_ref(_OBS, "Country") == ("e2", "o1")


def test_resolve_ref_raises_when_no_match():
    with pytest.raises(LookupError):
        resolve_ref(_OBS, "#nonexistent")


def test_widget_native_select_is_combobox_with_options():
    obs = {"observationId": "o1", "elements": [
        {"ref": "e1", "role": "combobox", "name": "Country",
         "widget": "native_select", "options": ["United States", "Germany"]}]}
    f = observation_to_fields(obs)[0]
    assert f.kind == "combobox"
    assert f.options == ["United States", "Germany"]


def test_widget_custom_combobox_has_no_options():
    obs = {"observationId": "o1", "elements": [
        {"ref": "e1", "role": "combobox", "name": "Country", "widget": "combobox"}]}
    f = observation_to_fields(obs)[0]
    assert f.kind == "combobox"
    assert f.options == []


def test_no_widget_falls_back_to_options_presence():
    obs = {"observationId": "o1", "elements": [
        {"ref": "e1", "role": "textbox", "name": "First Name"},
        {"ref": "e2", "role": "combobox", "name": "Country", "options": ["United States"]}]}
    fields = observation_to_fields(obs)
    assert (fields[0].kind, fields[0].options) == ("text", [])
    assert (fields[1].kind, fields[1].options) == ("combobox", ["United States"])


def test_widget_custom_combobox_sets_dynamic_options():
    obs = {"observationId": "o1", "elements": [
        {"ref": "e1", "role": "combobox", "name": "Country", "widget": "combobox"}]}
    f = observation_to_fields(obs)[0]
    assert f.kind == "combobox"
    assert f.dynamic_options is True


def test_widget_native_select_not_dynamic():
    obs = {"observationId": "o1", "elements": [
        {"ref": "e1", "role": "combobox", "name": "C", "widget": "native_select", "options": ["A"]}]}
    assert observation_to_fields(obs)[0].dynamic_options is False


def test_required_propagates_from_observation():
    obs = {"observationId": "o1", "elements": [
        {"ref": "e1", "role": "textbox", "name": "First Name", "required": True},
        {"ref": "e2", "role": "textbox", "name": "Middle Name"}]}
    fields = observation_to_fields(obs)
    assert fields[0].required is True
    assert fields[1].required is False


def test_widget_typeahead_maps_to_fillable_combobox():
    # SP-A React-Selects arrive as widget=typeahead; the slice-2b executor fills them,
    # so the mapper must route them to a fillable combobox kind with deferred options,
    # NOT the skip-everything typeahead kind.
    obs = {"observationId": "o1", "elements": [
        {"ref": "e1", "role": "combobox", "name": "Years of Python", "widget": "typeahead",
         "required": True}]}
    f = observation_to_fields(obs)[0]
    assert f.kind == "combobox"
    assert f.dynamic_options is True
    assert f.options == []
    assert f.required is True
