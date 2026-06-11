"""Tests for the OpenAPI 3.1 spec.

Four invariants:
  1. Routes and spec are in sync (parity). XFAIL until tu04.1.2/3/4 land.
  2. The spec is a valid OpenAPI 3.1 document.
  3. The checked-in docs/api/openapi.json matches the OPENAPI dict.
  4. GET /openapi.json serves the dict.

Bead: opensrm-tu04.1.1.
"""
from __future__ import annotations

import json
import pathlib

import pytest
from openapi_spec_validator import validate
from starlette.testclient import TestClient

from nthlayer_core.openapi_spec import (
    OPENAPI,
    _route_spec_pairs,
    _spec_path_method_pairs,
)
from nthlayer_core.server import app

ARTEFACT_PATH = (
    pathlib.Path(__file__).resolve().parent.parent / "docs" / "api" / "openapi.json"
)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Phase 1 (tu04.1.1) documents only /health. Routes for verdicts, "
        "assessments, cases, change-freezes, heartbeats, manifests, monitoring, "
        "suppressions, component-state remain undocumented until tu04.1.2/3/4 "
        "close. This xfail flips to xpass — and the test becomes load-bearing — "
        "when tu04.1 closes."
    ),
)
def test_route_parity() -> None:
    spec = _spec_path_method_pairs()
    routes = _route_spec_pairs()
    assert spec == routes, (
        f"In routes but not spec: {sorted(routes - spec)}\n"
        f"In spec but not routes: {sorted(spec - routes)}"
    )


def test_spec_is_valid_openapi_31() -> None:
    """Run openapi-spec-validator against the in-memory OPENAPI dict."""
    # validate() raises on invalid spec; passes through on valid.
    validate(OPENAPI)


def test_checked_in_artefact_matches() -> None:
    """docs/api/openapi.json must match what the dict produces.

    If this fails: `uv run python scripts/regen_openapi.py` and commit.
    """
    assert ARTEFACT_PATH.exists(), (
        f"Missing {ARTEFACT_PATH.relative_to(ARTEFACT_PATH.parent.parent.parent)}. "
        "Run scripts/regen_openapi.py."
    )
    on_disk = json.loads(ARTEFACT_PATH.read_text())
    assert on_disk == OPENAPI, (
        "docs/api/openapi.json is stale. "
        "Run scripts/regen_openapi.py and commit the result."
    )


def test_openapi_endpoint_served() -> None:
    """GET /openapi.json returns the OPENAPI dict."""
    with TestClient(app) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json() == OPENAPI
