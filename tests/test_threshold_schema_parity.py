"""Pin nthlayer-common's threshold closure tables to core's OpenAPI item schemas.

/manifests serves each threshold as nthlayer-common's threshold_to_v2_entry
emits it, and the OpenAPI JudgmentThreshold* components are closed. A common
5.x minor that adds an emitted key, a segments metric or a threshold type would
then serve items core's published schema refuses -- and fixtures alone only
notice if someone writes a fixture using the new field. These tests compare the
tables common enforces against the schema core publishes, in both directions,
so such a release turns core CI red on its own.

Importing the package-internal nthlayer_common.manifest.thresholds module is
deliberate: this is a parity pin against the exact tables common's parser and
emitter enforce, not a use of them as API [opensrm-7zpz].
"""

from __future__ import annotations

import pytest
from nthlayer_common.manifest.thresholds import (
    SEGMENTS_METRICS,
    SEGMENTS_SOURCES,
    THRESHOLD_BOUNDS,
    THRESHOLD_TYPE_FIELDS,
)

from nthlayer_core.openapi_spec import OPENAPI

_REF_PREFIX = "#/components/schemas/"


def _schemas() -> dict:
    return OPENAPI["components"]["schemas"]


def _item_components() -> dict[str, dict]:
    """threshold type -> its component schema, read from JudgmentThreshold."""
    union = _schemas()["JudgmentThreshold"]
    by_type: dict[str, dict] = {}
    for branch in union["oneOf"]:
        component = _schemas()[branch["$ref"].removeprefix(_REF_PREFIX)]
        by_type[component["properties"]["type"]["const"]] = component
    return by_type


def test_threshold_types_match():
    union = _schemas()["JudgmentThreshold"]
    assert set(_item_components()) == set(THRESHOLD_TYPE_FIELDS)
    # The discriminator must point each type at the branch whose const it is.
    mapping = {
        type_name: _schemas()[ref.removeprefix(_REF_PREFIX)]["properties"]["type"]["const"]
        for type_name, ref in union["discriminator"]["mapping"].items()
    }
    assert mapping == {t: t for t in THRESHOLD_TYPE_FIELDS}


@pytest.mark.parametrize("type_name", sorted(THRESHOLD_TYPE_FIELDS))
def test_entry_keys_match(type_name):
    component = _item_components()[type_name]
    assert component["additionalProperties"] is False
    schema_keys = set(component["properties"]) - {"type", "bounds"}
    assert schema_keys == set(THRESHOLD_TYPE_FIELDS[type_name])


@pytest.mark.parametrize(
    ("type_name", "key"),
    [
        (type_name, key)
        for type_name, fields in sorted(THRESHOLD_TYPE_FIELDS.items())
        for key, nested in sorted(fields.items())
        if nested is not None
    ],
)
def test_nested_object_keys_match(type_name, key):
    nested = _item_components()[type_name]["properties"][key]
    assert nested["additionalProperties"] is False
    assert set(nested["properties"]) == set(THRESHOLD_TYPE_FIELDS[type_name][key])


def test_non_object_keys_are_not_closed_objects_in_the_schema():
    """A key common treats as a scalar/list must not be an object in the schema."""
    for type_name, fields in THRESHOLD_TYPE_FIELDS.items():
        for key, nested in fields.items():
            if nested is None:
                prop = _item_components()[type_name]["properties"][key]
                assert prop.get("type") != "object", (type_name, key)


def test_bounds_table_covers_every_type():
    # Floor for the parametrisation below: an empty THRESHOLD_BOUNDS would
    # collect zero cases and pass silently.
    assert set(THRESHOLD_BOUNDS) == set(_item_components())
    assert len(THRESHOLD_BOUNDS) == 5


@pytest.mark.parametrize("type_name", sorted(THRESHOLD_BOUNDS))
def test_bound_names_match(type_name):
    assert THRESHOLD_BOUNDS[type_name]
    bounds = _item_components()[type_name]["properties"]["bounds"]
    assert bounds["additionalProperties"] is False
    assert set(bounds["properties"]) == set(THRESHOLD_BOUNDS[type_name])


def test_segments_metric_enum_matches():
    segments = _item_components()["segments"]["properties"]
    assert set(segments["metric"]["enum"]) == set(SEGMENTS_METRICS)


def test_segments_source_enum_matches():
    measurement = _item_components()["segments"]["properties"]["measurement"]
    assert set(measurement["properties"]["source"]["enum"]) == set(SEGMENTS_SOURCES)
