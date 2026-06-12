"""Tests for the OpenAPI 3.1 spec.

Four primary invariants:
  1. Routes and spec are in sync (parity). XFAIL until tu04.1.2/3/4 land.
  2. The spec is a valid OpenAPI 3.1 document.
  3. The checked-in docs/api/openapi.json matches the OPENAPI dict.
  4. GET /openapi.json serves the dict.

Three safety-invariant guards (added by R5 P3 review): the duplicate-key
guards in _build_paths/_build_schemas and the assert_parity error
message format are the module's primary defences against fragment
authors silently shadowing existing paths/schemas or against drift
going undiagnosed.

Bead: opensrm-tu04.1.1.
"""
from __future__ import annotations

import json
import pathlib
import types

import pytest
from openapi_spec_validator import validate
from starlette.testclient import TestClient

from nthlayer_core import openapi_spec as openapi_spec_module
from nthlayer_core.openapi_spec import (
    OPENAPI,
    _route_spec_pairs,
    _spec_path_method_pairs,
    assert_parity,
)
from nthlayer_core.server import app

ARTEFACT_PATH = (
    pathlib.Path(__file__).resolve().parent.parent / "docs" / "api" / "openapi.json"
)


def test_route_parity() -> None:
    """Every Starlette route must appear in OPENAPI['paths'] and vice versa.

    Load-bearing as of tu04.1.4 close — Phases 1-4 of tu04.1 have all
    landed, so the parity gap is now empty. Future routes added to
    server.py without a matching paths_*.py fragment fail this test in
    CI.
    """
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


# -- Safety invariants (R5 P3 — added 2026-06-12) -----------------------------


def test_build_paths_raises_on_duplicate_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """_build_paths must refuse two fragments declaring the same path.

    Without this guard, the second fragment would silently shadow the
    first — a real risk when Phases 2-4 fan-out implementers each add
    a paths_*.py module independently.
    """
    frag_a = types.SimpleNamespace(PATHS={"/dup": {"get": {}}}, SCHEMAS={})
    frag_b = types.SimpleNamespace(PATHS={"/dup": {"post": {}}}, SCHEMAS={})
    monkeypatch.setattr(openapi_spec_module, "_FRAGMENTS", [frag_a, frag_b])
    with pytest.raises(ValueError, match="Duplicate OpenAPI path entry"):
        openapi_spec_module._build_paths()


def test_build_schemas_raises_on_duplicate_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_build_schemas must refuse two fragments declaring the same schema name.

    Symmetric to the path guard. The reserved name ``ErrorEnvelope`` is
    also rejected because _build_schemas seeds it before merging.
    """
    frag_a = types.SimpleNamespace(PATHS={}, SCHEMAS={"Dup": {"type": "object"}})
    frag_b = types.SimpleNamespace(PATHS={}, SCHEMAS={"Dup": {"type": "string"}})
    monkeypatch.setattr(openapi_spec_module, "_FRAGMENTS", [frag_a, frag_b])
    with pytest.raises(ValueError, match="Duplicate OpenAPI schema component"):
        openapi_spec_module._build_schemas()


def test_assert_parity_failure_message_lists_both_diff_sides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """assert_parity must surface BOTH 'in routes' and 'in spec' diffs.

    The message has to be self-contained for the CI log reader — if
    either half is missing, the fix instruction is ambiguous.
    """
    monkeypatch.setattr(
        openapi_spec_module,
        "_spec_path_method_pairs",
        lambda: {("/spec_only", "GET")},
    )
    monkeypatch.setattr(
        openapi_spec_module,
        "_route_spec_pairs",
        lambda: {("/route_only", "POST")},
    )
    with pytest.raises(AssertionError) as exc_info:
        assert_parity()
    msg = str(exc_info.value)
    assert "In routes but not spec: [('/route_only', 'POST')]" in msg
    assert "In spec but not routes: [('/spec_only', 'GET')]" in msg
    assert "src/nthlayer_core/_openapi/paths_*.py" in msg
