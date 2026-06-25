"""Pure mapping between ai-in-browser's MCP Observation and the engine-neutral
PageSnapshot/FormField contract. No I/O — unit-testable without a browser.

The MCP adapter's formatObservation emits each element as {ref, role, name, options?}
(no DOM id / fieldHints). So a field's stable key is its accessible name (FormField.key
with no id == the label), and a requested key resolves to a ref by matching that name.
"""

from __future__ import annotations

import json

from backend.platforms.form_fill import FormField

# Interactive roles that represent a fillable field (buttons/links are excluded).
_FIELD_ROLES = {"textbox", "searchbox", "spinbutton", "combobox", "listbox"}


def parse_observation(text: str) -> dict:
    """Parse a browser_observe tool result (formatObservation JSON)."""
    return json.loads(text)


def _kind(el: dict, options: list[str]) -> str:
    """Field kind from slice-2b's `widget` flag, with an options-presence fallback.

    Custom comboboxes AND React-Select typeaheads surface NO options at observe time
    (they're discovered at select-time) and are filled live by the slice-2b executor, so
    both map to a fillable `combobox` kind. Native `<select>` is also `combobox` (it
    carries options). Fall back to the old rule only when `widget` is absent (pre-slice-2b
    adapter or a plain textbox/searchbox)."""
    widget = el.get("widget")
    if widget in ("native_select", "combobox", "typeahead"):
        return "combobox"
    return "combobox" if options else "text"


def observation_to_fields(obs: dict) -> list[FormField]:
    """Map an Observation's elements to fillable FormFields (buttons/links excluded)."""
    fields: list[FormField] = []
    for el in obs.get("elements", []):
        if el.get("role", "") not in _FIELD_ROLES:
            continue
        options = list(el.get("options", []) or [])
        # custom widget OR React-Select typeahead: options deferred to select-time
        dynamic = el.get("widget") in ("combobox", "typeahead")
        fields.append(FormField(label=el.get("name", ""), kind=_kind(el, options),
                                options=options, dynamic_options=dynamic,
                                required=bool(el.get("required"))))
    return fields


def resolve_ref(obs: dict, key: str) -> tuple[str, str]:
    """Resolve a FormField.key to (ref, observationId) within this observation.

    The engine produces label-based keys (no DOM id is surfaced over MCP), so a key
    matches the element whose accessible name equals it; first match wins. Raises
    LookupError when nothing matches — the caller (apply_driver) treats that as a fill
    failure and never submits.
    """
    for el in obs.get("elements", []):
        if el.get("name", "") == key:
            return el["ref"], obs["observationId"]
    raise LookupError(f"no element matching key {key!r} in observation {obs.get('observationId')!r}")
