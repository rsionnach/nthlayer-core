"""Core HTTP server.

Starlette ASGI app exposing the core's unified store via HTTP API.
Workers and bench access the store exclusively through these endpoints.

Verdicts are immutable after creation — there is no PUT/PATCH on /verdicts.
Outcome resolution writes a NEW verdict referencing the original as parent.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import structlog
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
import uvicorn

from nthlayer_common.overrides import (
    OverrideEvent,
    OverridePrivacyConfig,
    apply_override_to_verdict,
)
from nthlayer_core.catalogue import ManifestCatalogue, manifest_to_dict
from nthlayer_core.store import Store

logger = structlog.get_logger()


def _store_error_response(handler: str, exc: Exception, **context) -> JSONResponse:
    """Log a store-layer exception server-side and return a generic 500.

    Raw exception strings (sqlite3 error messages, constraint names) must
    not leak to clients (opensrm-9uow.1). Operators read the structured
    log line; clients receive only ``error="internal_error"``.
    """
    logger.error(
        "core_store_error",
        handler=handler,
        exc_type=type(exc).__name__,
        exc=str(exc),
        **context,
    )
    return JSONResponse(
        {"error": "internal_error", "detail": {"message": "store operation failed"}},
        status_code=500,
    )

# Module-level store instance, initialised on first request or at startup
_store: Store | None = None

# Module-level manifest catalogue
_catalogue: ManifestCatalogue | None = None


def _get_store() -> Store:
    global _store
    if _store is None:
        path = os.environ.get("NTHLAYER_STORE_PATH", "nthlayer.db")
        _store = Store(path)
    return _store


def set_store(store: Store) -> None:
    """Inject a store instance (for testing)."""
    global _store
    _store = store


def _get_catalogue() -> ManifestCatalogue:
    global _catalogue
    if _catalogue is None:
        manifests_dir = os.environ.get("NTHLAYER_MANIFESTS_DIR")
        _catalogue = ManifestCatalogue(manifests_dir)
        _catalogue.load()
    return _catalogue


def set_catalogue(catalogue: ManifestCatalogue) -> None:
    """Inject a catalogue instance (for testing)."""
    global _catalogue
    _catalogue = catalogue


# -- Helpers --

async def _parse_json_body(request: Request) -> tuple[dict | None, JSONResponse | None]:
    """Parse request body as JSON. Returns (body, None) on success or (None, error_response) on failure."""
    try:
        body = await request.json()
        if not isinstance(body, dict):
            return None, JSONResponse(
                {"error": "invalid_json", "detail": {"message": "Request body must be a JSON object"}},
                status_code=422,
            )
        return body, None
    except Exception:
        return None, JSONResponse(
            {"error": "invalid_json", "detail": {"message": "Request body must be valid JSON"}},
            status_code=422,
        )


# CloudEvents auto-detect on POST /verdicts and /assessments.
# Body with top-level ``specversion`` -> unwrap envelope before validation;
# without -> treat as raw record (v1.5 back-compat). 400=envelope_invalid,
# 422=record_invalid; envelope_version null|"1.0" lets callers distinguish
# transport from domain errors.
# See docs/superpowers/decisions/envelope-contract-auto-detect-to-mandatory.md

_ENVELOPE_REQUIRED_ATTRS = ("specversion", "type", "source", "id")


def _looks_like_envelope(body: dict) -> bool:
    """A body with top-level ``specversion`` is treated as a CloudEvents envelope."""
    return "specversion" in body


def _unwrap_envelope(body: dict) -> tuple[dict | None, JSONResponse | None]:
    """Validate envelope attributes and return the inner ``data`` payload.

    Returns (inner_data, None) on success or (None, 400_response) when the
    envelope is malformed. ``data`` must itself be a dict — non-dict data
    is an envelope-level error since it can never produce a valid record.
    """
    missing = [attr for attr in _ENVELOPE_REQUIRED_ATTRS if attr not in body]
    if missing:
        return None, JSONResponse(
            {
                "error": "envelope_invalid",
                "detail": f"missing required CloudEvents attribute(s): {missing}",
                "envelope_version": None,
            },
            status_code=400,
        )
    if body.get("specversion") != "1.0":
        return None, JSONResponse(
            {
                "error": "envelope_invalid",
                "detail": f"unsupported CloudEvents specversion: {body['specversion']}",
                "envelope_version": None,
            },
            status_code=400,
        )
    data = body.get("data")
    if not isinstance(data, dict):
        return None, JSONResponse(
            {
                "error": "envelope_invalid",
                "detail": "envelope 'data' must be a JSON object",
                "envelope_version": None,
            },
            status_code=400,
        )
    return data, None


def _validate_required(
    record: dict,
    required: tuple[str, ...],
    *,
    error_code: str,
    envelope_version: str | None,
) -> JSONResponse | None:
    """Check required fields on the inner record. Returns 422 on miss."""
    missing = [f for f in required if f not in record]
    if missing:
        return JSONResponse(
            {
                "error": error_code,
                "detail": {"fields": missing},
                "envelope_version": envelope_version,
            },
            status_code=422,
        )
    return None


def _parse_int_param(params, name: str, default: int) -> tuple[int, JSONResponse | None]:
    """Parse an integer query parameter. Returns (value, None) or (0, error_response)."""
    raw = params.get(name)
    if raw is None:
        return default, None
    try:
        value = int(raw)
        if value < 0:
            return 0, JSONResponse(
                {"error": "invalid_parameter", "detail": {"param": name, "message": "must be non-negative"}},
                status_code=422,
            )
        return value, None
    except ValueError:
        return 0, JSONResponse(
            {"error": "invalid_parameter", "detail": {"param": name, "message": "must be an integer"}},
            status_code=422,
        )


# -- Health --

async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def openapi_json(request: Request) -> JSONResponse:
    """Serve the OpenAPI 3.1 spec.

    Source of truth lives in nthlayer_core.openapi_spec.OPENAPI; the
    checked-in artefact at docs/api/openapi.json is regenerated by
    scripts/regen_openapi.py.
    """
    from nthlayer_core.openapi_spec import OPENAPI
    return JSONResponse(OPENAPI)


# -- Verdicts --

async def post_verdict(request: Request) -> JSONResponse:
    """Create a verdict. Immutable after creation.

    Accepts either a CloudEvents v1.0 envelope (auto-detected by
    ``specversion``) or a raw verdict dict. Envelopes are unwrapped before
    validation. See ``_unwrap_envelope`` for the error contract.
    """
    body, err = await _parse_json_body(request)
    if err:
        return err

    if _looks_like_envelope(body):
        record, env_err = _unwrap_envelope(body)
        if env_err:
            return env_err
        envelope_version: str | None = "1.0"
    else:
        record = body
        envelope_version = None

    err = _validate_required(
        record, ("id", "type", "created_at"),
        error_code="verdict_invalid",
        envelope_version=envelope_version,
    )
    if err:
        return err

    try:
        store = _get_store()
        vid = store.put_verdict(record)
        return JSONResponse({"id": vid}, status_code=201)
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            return JSONResponse(
                {"error": "duplicate", "detail": {"id": record.get("id")}},
                status_code=409,
            )
        return _store_error_response("post_verdict", e, verdict_id=record.get("id"))


async def get_verdicts(request: Request) -> JSONResponse:
    """Query verdicts with optional filters."""
    store = _get_store()
    params = request.query_params
    limit, err = _parse_int_param(params, "limit", 100)
    if err:
        return err
    results = store.query_verdicts(
        service=params.get("service"),
        verdict_type=params.get("type"),
        created_after=params.get("created_after"),
        created_before=params.get("created_before"),
        limit=limit,
    )
    return JSONResponse(results)


async def get_verdict(request: Request) -> JSONResponse:
    """Get a single verdict by ID."""
    vid = request.path_params["verdict_id"]
    store = _get_store()
    result = store.get_verdict(vid)
    if result is None:
        return JSONResponse(
            {"error": "not_found", "detail": {"id": vid}},
            status_code=404,
        )
    return JSONResponse(result)


async def get_verdict_ancestors(request: Request) -> JSONResponse:
    """Get ancestors of a verdict via the lineage index."""
    vid = request.path_params["verdict_id"]
    store = _get_store()
    raw_hops = request.query_params.get("max_hops")
    if raw_hops is not None:
        hops, err = _parse_int_param(request.query_params, "max_hops", 0)
        if err:
            return err
        ancestors = store.ancestors_of(vid, max_hops=hops)
    else:
        ancestors = store.ancestors_of(vid)
    return JSONResponse(ancestors)


async def get_verdict_descendants(request: Request) -> JSONResponse:
    """Get descendants of a verdict via the lineage index."""
    vid = request.path_params["verdict_id"]
    store = _get_store()
    descendants = store.descendants_of(vid)
    return JSONResponse(descendants)


async def post_verdict_outcome(request: Request) -> JSONResponse:
    """Resolve a verdict's outcome by creating a NEW outcome_resolution verdict.

    The original verdict is NEVER mutated. This endpoint creates a new verdict
    with type='outcome_resolution' and parent_ids=[original_id].
    """
    original_id = request.path_params["verdict_id"]
    store = _get_store()

    original = store.get_verdict(original_id)
    if original is None:
        return JSONResponse(
            {"error": "not_found", "detail": {"id": original_id}},
            status_code=404,
        )

    body, err = await _parse_json_body(request)
    if err:
        return err

    now = datetime.now(timezone.utc).isoformat()

    outcome_verdict = {
        "id": body.get("id", f"out-{original_id}"),
        "type": "outcome_resolution",
        "service": original.get("service"),
        "created_at": now,
        "parent_ids": [original_id],
        "chain_depth": (original.get("chain_depth", 0) or 0) + 1,
        "pipeline_latency_ms": body.get("pipeline_latency_ms"),
        "outcome_status": body.get("outcome_status", "confirmed"),
        "resolution": body.get("resolution"),
        "reasoning": body.get("reasoning"),
    }

    try:
        vid = store.put_verdict(outcome_verdict)
        return JSONResponse({"id": vid}, status_code=201)
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            return JSONResponse(
                {"error": "duplicate", "detail": {"id": outcome_verdict["id"]}},
                status_code=409,
            )
        return _store_error_response(
            "post_verdict_outcome", e, verdict_id=outcome_verdict["id"]
        )


async def post_verdict_override(request: Request) -> JSONResponse:
    """Apply an operator override to a verdict (mutation-style, opensrm-jmy.18).

    Calls apply_override_to_verdict on the verdict store, mutating the
    original verdict's outcome in place. Distinct from POST /outcome
    which creates an outcome_resolution child verdict (lineage-style).
    """
    verdict_id = request.path_params["verdict_id"]
    body, err = await _parse_json_body(request)
    if err:
        return err

    # Coerce ISO timestamp string to datetime so OverrideEvent.__post_init__
    # can validate tzinfo. JSON wire format sends strings; OverrideEvent
    # expects a tz-aware datetime object.
    parsed_body = dict(body)
    if isinstance(parsed_body.get("timestamp"), str):
        try:
            parsed_body["timestamp"] = datetime.fromisoformat(parsed_body["timestamp"])
        except ValueError as exc:
            return JSONResponse(
                {"error": "validation_error", "detail": str(exc)},
                status_code=422,
            )

    try:
        event = OverrideEvent(**parsed_body)
    except (TypeError, ValueError) as exc:
        return JSONResponse(
            {"error": "validation_error", "detail": str(exc)},
            status_code=422,
        )

    if event.decision_id != verdict_id:
        return JSONResponse(
            {"error": "decision_id_mismatch",
             "detail": {"path": verdict_id, "body": event.decision_id}},
            status_code=400,
        )

    store = _get_store()
    privacy = OverridePrivacyConfig(pre_redacted=True, exclude_reason=False)
    result = apply_override_to_verdict(store, event, privacy=privacy)

    if result is not None:
        return JSONResponse(
            {"id": verdict_id, "status": "overridden"},
            status_code=200,
        )

    # None-path: read the verdict back to map cause -> HTTP status.
    verdict = store.get(verdict_id)
    if verdict is None:
        return JSONResponse({"error": "verdict_not_found"}, status_code=404)

    current = (getattr(verdict.outcome, "status", None) or "").lower()
    if current == "overridden":
        return JSONResponse({"error": "conflict"}, status_code=409)
    return JSONResponse({"error": "validation_error"}, status_code=422)


# -- Assessments --

async def post_assessment(request: Request) -> JSONResponse:
    """Create an assessment.

    Accepts either a CloudEvents v1.0 envelope (auto-detected by
    ``specversion``) or a raw assessment dict. See ``_unwrap_envelope``
    for the error contract.
    """
    body, err = await _parse_json_body(request)
    if err:
        return err

    if _looks_like_envelope(body):
        record, env_err = _unwrap_envelope(body)
        if env_err:
            return env_err
        envelope_version: str | None = "1.0"
    else:
        record = body
        envelope_version = None

    err = _validate_required(
        record, ("id", "service", "kind", "created_at"),
        error_code="assessment_invalid",
        envelope_version=envelope_version,
    )
    if err:
        return err

    try:
        store = _get_store()
        aid = store.put_assessment(record)
        return JSONResponse({"id": aid}, status_code=201)
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            return JSONResponse(
                {"error": "duplicate", "detail": {"id": record.get("id")}},
                status_code=409,
            )
        return _store_error_response("post_assessment", e, assessment_id=record.get("id"))


async def get_assessments(request: Request) -> JSONResponse:
    """Query assessments with optional filters."""
    store = _get_store()
    params = request.query_params
    limit, err = _parse_int_param(params, "limit", 100)
    if err:
        return err
    results = store.query_assessments(
        service=params.get("service"),
        kind=params.get("kind"),
        limit=limit,
    )
    return JSONResponse(results)


# -- Cases --

# Priority derivation: blast_radius × incident context.
# Production with active incident = P0 (immediate human action, real user impact).
# Production without incident = P1 (routine approval, not urgent).
# Staging caps at P1 even during incidents (blast radius bounded to internal testers).
# Dev, ephemeral, or unspecified = P3.
_PRIORITY_MAP = {
    ("production", True): "P0",
    ("production", False): "P1",
    ("staging", True): "P1",
    ("staging", False): "P2",
}
_DEFAULT_PRIORITY = "P3"  # dev, ephemeral, or unspecified


def _derive_priority(blast_radius: str | None, has_active_incident: bool) -> str:
    """Derive case priority from blast_radius and incident context."""
    if blast_radius is None:
        return _DEFAULT_PRIORITY
    return _PRIORITY_MAP.get((blast_radius, has_active_incident), _DEFAULT_PRIORITY)


async def post_case(request: Request) -> JSONResponse:
    """Create a case from an underlying verdict."""
    body, err = await _parse_json_body(request)
    if err:
        return err

    required = ("id", "kind", "created_at", "underlying_verdict")
    missing = [f for f in required if f not in body]
    if missing:
        return JSONResponse(
            {"error": "missing_fields", "detail": {"fields": missing}},
            status_code=422,
        )

    # Derive priority if not explicitly provided
    if "priority" not in body:
        body["priority"] = _derive_priority(
            body.get("blast_radius"),
            body.get("has_active_incident", False),
        )

    try:
        store = _get_store()
        cid = store.put_case(body)
        return JSONResponse({"id": cid, "priority": body["priority"]}, status_code=201)
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            return JSONResponse(
                {"error": "duplicate", "detail": {"id": body.get("id")}},
                status_code=409,
            )
        return _store_error_response("post_case", e, case_id=body.get("id"))


async def get_cases(request: Request) -> JSONResponse:
    """Query cases with optional filters."""
    store = _get_store()
    params = request.query_params
    limit, err = _parse_int_param(params, "limit", 100)
    if err:
        return err
    results = store.query_cases(
        state=params.get("state"),
        priority=params.get("priority"),
        service=params.get("service"),
        limit=limit,
    )
    return JSONResponse(results)


async def get_case(request: Request) -> JSONResponse:
    """Get a single case by ID."""
    cid = request.path_params["case_id"]
    store = _get_store()
    result = store.get_case(cid)
    if result is None:
        return JSONResponse(
            {"error": "not_found", "detail": {"id": cid}},
            status_code=404,
        )
    return JSONResponse(result)


async def put_case_lease(request: Request) -> JSONResponse:
    """Acquire a lease on a case. Atomic — exactly one concurrent request succeeds."""
    cid = request.path_params["case_id"]
    body, err = await _parse_json_body(request)
    if err:
        return err

    holder = body.get("holder")
    expires_at = body.get("expires_at")
    if not holder or not expires_at:
        return JSONResponse(
            {"error": "missing_fields", "detail": {"fields": [f for f in ("holder", "expires_at") if not body.get(f)]}},
            status_code=422,
        )

    # Validate expires_at is in the future
    try:
        lease_expiry = datetime.fromisoformat(expires_at)
        if lease_expiry.tzinfo is None:
            lease_expiry = lease_expiry.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return JSONResponse(
            {"error": "invalid_parameter", "detail": {"param": "expires_at", "message": "must be a valid ISO timestamp"}},
            status_code=422,
        )
    if lease_expiry <= datetime.now(timezone.utc):
        return JSONResponse(
            {"error": "invalid_parameter", "detail": {"param": "expires_at", "message": "must be in the future"}},
            status_code=422,
        )

    store = _get_store()

    # Verify case exists
    case = store.get_case(cid)
    if case is None:
        return JSONResponse(
            {"error": "not_found", "detail": {"id": cid}},
            status_code=404,
        )

    acquired = store.acquire_lease(cid, holder, expires_at)
    if acquired:
        return JSONResponse({"leased": True, "holder": holder}, status_code=200)
    return JSONResponse(
        {"error": "lease_conflict", "detail": {"id": cid, "message": "Case already leased by another operator"}},
        status_code=409,
    )


async def delete_case_lease(request: Request) -> JSONResponse:
    """Release a lease on a case. Any caller can release — admin-level operation."""
    cid = request.path_params["case_id"]
    store = _get_store()
    case = store.get_case(cid)
    if case is None:
        return JSONResponse(
            {"error": "not_found", "detail": {"id": cid}},
            status_code=404,
        )
    store.release_lease(cid)
    return JSONResponse({"released": True}, status_code=200)


async def put_case_resolve(request: Request) -> JSONResponse:
    """Resolve a case with a resolution verdict."""
    cid = request.path_params["case_id"]
    body, err = await _parse_json_body(request)
    if err:
        return err

    resolution_id = body.get("resolution_id")
    if not resolution_id:
        return JSONResponse(
            {"error": "missing_fields", "detail": {"fields": ["resolution_id"]}},
            status_code=422,
        )

    store = _get_store()
    case = store.get_case(cid)
    if case is None:
        return JSONResponse(
            {"error": "not_found", "detail": {"id": cid}},
            status_code=404,
        )

    # Atomic resolve with state guard — prevents race condition and double-resolve
    resolved = store.resolve_case(cid, resolution_id)
    if not resolved:
        return JSONResponse(
            {"error": "already_resolved", "detail": {"id": cid, "resolution_id": case.get("resolution_id")}},
            status_code=409,
        )
    return JSONResponse({"resolved": True, "resolution_id": resolution_id}, status_code=200)


# -- Change Freezes --

async def post_change_freeze(request: Request) -> JSONResponse:
    """Declare a change freeze."""
    body, err = await _parse_json_body(request)
    if err:
        return err

    required = ("name", "declared_by", "declared_at", "active_from", "active_until")
    missing = [f for f in required if f not in body]
    if missing:
        return JSONResponse(
            {"error": "missing_fields", "detail": {"fields": missing}},
            status_code=422,
        )

    # Validate temporal ordering
    try:
        from_dt = datetime.fromisoformat(body["active_from"])
        until_dt = datetime.fromisoformat(body["active_until"])
    except (ValueError, TypeError):
        return JSONResponse(
            {"error": "invalid_parameter", "detail": {"message": "active_from and active_until must be valid ISO timestamps"}},
            status_code=422,
        )
    if until_dt <= from_dt:
        return JSONResponse(
            {"error": "invalid_parameter", "detail": {"message": "active_until must be after active_from"}},
            status_code=422,
        )

    try:
        store = _get_store()
        name = store.put_change_freeze(body)
        return JSONResponse({"name": name}, status_code=201)
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            return JSONResponse(
                {"error": "duplicate", "detail": {"name": body.get("name")}},
                status_code=409,
            )
        return _store_error_response("post_change_freeze", e, freeze_name=body.get("name"))


async def get_change_freezes(request: Request) -> JSONResponse:
    """Get active change freezes."""
    store = _get_store()
    freezes = store.get_active_freezes()
    return JSONResponse(freezes)


async def put_change_freeze_lift(request: Request) -> JSONResponse:
    """Lift a change freeze early."""
    name = request.path_params["freeze_name"]
    body, err = await _parse_json_body(request)
    if err:
        return err

    lifted_by = body.get("lifted_by")
    if not lifted_by:
        return JSONResponse(
            {"error": "missing_fields", "detail": {"fields": ["lifted_by"]}},
            status_code=422,
        )

    store = _get_store()
    lifted = store.lift_change_freeze(name, lifted_by)
    if not lifted:
        return JSONResponse(
            {"error": "not_found", "detail": {"name": name}},
            status_code=404,
        )
    return JSONResponse({"lifted": True, "name": name}, status_code=200)


# -- Heartbeats --

async def post_heartbeat(request: Request) -> JSONResponse:
    """Record a heartbeat from a component."""
    body, err = await _parse_json_body(request)
    if err:
        return err

    component = body.get("component")
    instance_id = body.get("instance_id")
    if not component or not instance_id:
        return JSONResponse(
            {"error": "missing_fields", "detail": {"fields": [f for f in ("component", "instance_id") if not body.get(f)]}},
            status_code=422,
        )

    store = _get_store()
    store.put_heartbeat(component, instance_id, body.get("state"))
    return JSONResponse({"ok": True}, status_code=200)


async def get_heartbeats(request: Request) -> JSONResponse:
    """Get all heartbeats with computed health status.

    Components with no heartbeat for 30s are marked degraded.
    """
    store = _get_store()
    params = request.query_params
    threshold, err = _parse_int_param(params, "threshold", 30)
    if err:
        return err
    heartbeats = store.get_heartbeats_with_health(degraded_threshold_seconds=threshold)
    return JSONResponse(heartbeats)


async def get_manifests(request: Request) -> JSONResponse:
    """List all loaded manifests."""
    catalogue = _get_catalogue()
    return JSONResponse(catalogue.to_dict_list())


async def get_manifest(request: Request) -> JSONResponse:
    """Get a single manifest by service name."""
    service = request.path_params["service"]
    catalogue = _get_catalogue()
    manifest = catalogue.get(service)
    if manifest is None:
        return JSONResponse(
            {"error": "not_found", "detail": {"service": service}},
            status_code=404,
        )
    return JSONResponse(manifest_to_dict(manifest))


async def post_manifests_reload(request: Request) -> JSONResponse:
    """Trigger a catalogue reload. Returns list of changed service names."""
    catalogue = _get_catalogue()
    changed = catalogue.poll()
    return JSONResponse({"changed": changed, "total": len(catalogue.list_all())})


async def post_suppression(request: Request) -> JSONResponse:
    """Record a suppressed verdict with reason.

    Workers report suppressed verdicts (active_incident, dedup, hysteresis)
    so the suppression audit trail is visible to operators.
    """
    body, err = await _parse_json_body(request)
    if err:
        return err

    required = ("component", "reason", "suppressed_verdict_id")
    missing = [f for f in required if not body.get(f)]
    if missing:
        return JSONResponse(
            {"error": "missing_fields", "detail": {"fields": missing}},
            status_code=422,
        )

    store = _get_store()
    row_id = store.put_suppression(
        component=body["component"],
        reason=body["reason"],
        suppressed_verdict_id=body["suppressed_verdict_id"],
        related_verdict_id=body.get("related_verdict_id"),
        suppressed_at=body.get("suppressed_at"),
    )
    return JSONResponse({"id": row_id}, status_code=201)


async def get_suppressions(request: Request) -> JSONResponse:
    """Query suppressions with optional filters."""
    store = _get_store()
    params = request.query_params
    limit, err = _parse_int_param(params, "limit", 100)
    if err:
        return err
    results = store.query_suppressions(
        component=params.get("component"),
        created_after=params.get("created_after"),
        created_before=params.get("created_before"),
        limit=limit,
    )
    return JSONResponse(results)


async def put_component_state(request: Request) -> JSONResponse:
    """Save component processing state (cursor, hysteresis, dedup cache).

    Workers persist state after each cycle for crash recovery.
    """
    component = request.path_params["component"]
    body, err = await _parse_json_body(request)
    if err:
        return err

    store = _get_store()
    store.put_component_state(component, body)
    return JSONResponse({"ok": True, "component": component}, status_code=200)


async def get_component_state(request: Request) -> JSONResponse:
    """Retrieve component processing state.

    Workers restore state on startup to resume from last checkpoint.
    """
    component = request.path_params["component"]
    store = _get_store()
    state = store.get_component_state(component)
    if state is None:
        return JSONResponse(
            {"error": "not_found", "detail": {"component": component}},
            status_code=404,
        )
    return JSONResponse(state)


async def get_stuck_action_requests(request: Request) -> JSONResponse:
    """Get action_request verdicts that have no corresponding case.

    These indicate a failure in the case-creation pipeline.
    Exposed as a monitoring endpoint — check this to detect silent failures.
    """
    store = _get_store()
    params = request.query_params
    threshold, err = _parse_int_param(params, "threshold", 60)
    if err:
        return err
    stuck = store.get_stuck_action_requests(threshold_seconds=threshold)
    return JSONResponse({"count": len(stuck), "stuck": stuck})


# -- Route table --

routes = [
    Route("/health", health, methods=["GET"]),
    Route("/openapi.json", openapi_json, methods=["GET"]),
    # Verdicts (immutable — no PUT/PATCH)
    Route("/verdicts", post_verdict, methods=["POST"]),
    Route("/verdicts", get_verdicts, methods=["GET"]),
    Route("/verdicts/{verdict_id}", get_verdict, methods=["GET"]),
    Route("/verdicts/{verdict_id}/ancestors", get_verdict_ancestors, methods=["GET"]),
    Route("/verdicts/{verdict_id}/descendants", get_verdict_descendants, methods=["GET"]),
    Route("/verdicts/{verdict_id}/outcome", post_verdict_outcome, methods=["POST"]),
    Route("/verdicts/{verdict_id}/override", post_verdict_override, methods=["POST"]),
    # Assessments
    Route("/assessments", post_assessment, methods=["POST"]),
    Route("/assessments", get_assessments, methods=["GET"]),
    # Cases
    Route("/cases", post_case, methods=["POST"]),
    Route("/cases", get_cases, methods=["GET"]),
    Route("/cases/{case_id}", get_case, methods=["GET"]),
    Route("/cases/{case_id}/lease", put_case_lease, methods=["PUT"]),
    Route("/cases/{case_id}/lease", delete_case_lease, methods=["DELETE"]),
    Route("/cases/{case_id}/resolve", put_case_resolve, methods=["PUT"]),
    # Change Freezes
    Route("/change-freezes", post_change_freeze, methods=["POST"]),
    Route("/change-freezes", get_change_freezes, methods=["GET"]),
    Route("/change-freezes/{freeze_name}/lift", put_change_freeze_lift, methods=["PUT"]),
    # Heartbeats
    Route("/heartbeats", post_heartbeat, methods=["POST"]),
    Route("/heartbeats", get_heartbeats, methods=["GET"]),
    # Manifests (literal routes before parameterized)
    Route("/manifests", get_manifests, methods=["GET"]),
    Route("/manifests/-/reload", post_manifests_reload, methods=["POST"]),
    Route("/manifests/{service}", get_manifest, methods=["GET"]),
    # Suppressions
    Route("/suppressions", post_suppression, methods=["POST"]),
    Route("/suppressions", get_suppressions, methods=["GET"]),
    # Component State
    Route("/component-state/{component}", put_component_state, methods=["PUT"]),
    Route("/component-state/{component}", get_component_state, methods=["GET"]),
    # Monitoring
    Route("/monitoring/stuck-action-requests", get_stuck_action_requests, methods=["GET"]),
]

app = Starlette(routes=routes)


def run_server(host: str = "0.0.0.0", port: int = 8000):
    uvicorn.run(app, host=host, port=port)
