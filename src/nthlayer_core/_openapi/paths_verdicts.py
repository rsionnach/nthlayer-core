"""OpenAPI spec fragment for /verdicts* routes (opensrm-tu04.1.2).

Documents the seven verdict endpoints exposed by nthlayer-core:

- ``POST /verdicts`` — create an immutable verdict (raw or CloudEvents).
- ``GET /verdicts`` — query with optional filters.
- ``GET /verdicts/{verdict_id}`` — fetch one verdict.
- ``GET /verdicts/{verdict_id}/ancestors`` — lineage upward.
- ``GET /verdicts/{verdict_id}/descendants`` — lineage downward.
- ``POST /verdicts/{verdict_id}/outcome`` — lineage-style resolution
  (creates a NEW ``outcome_resolution`` verdict; original is never
  mutated).
- ``POST /verdicts/{verdict_id}/override`` — mutation-style override
  (opensrm-jmy.18); the one exception to immutability, invoked only
  by the override-adapter sidecar via CAS.

Contributes the ``Verdict`` and ``EventEnvelope`` component schemas.
All 4xx/5xx responses reference the shared ``ErrorEnvelope`` defined
by the orchestrator.
"""
from __future__ import annotations

PATHS: dict[str, dict] = {
    "/verdicts": {
        "post": {
            "summary": "Create a verdict",
            "description": (
                "Creates a new immutable verdict. The request body is "
                "either a raw verdict dict OR a CloudEvents v1.0 envelope "
                "(auto-detected by the presence of a top-level "
                "``specversion`` field); envelopes are unwrapped before "
                "validation. Returns 422 ``invalid_json`` for malformed JSON, "
                "400 ``envelope_invalid`` if an envelope cannot be unwrapped, "
                "and 422 ``verdict_invalid`` if the inner record fails "
                "required-field validation. Duplicate ids return 409 "
                "``duplicate``. Verdicts are write-once; subsequent "
                "resolution must use POST /verdicts/{id}/outcome or "
                "POST /verdicts/{id}/override."
            ),
            "operationId": "postVerdict",
            "tags": ["verdicts"],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "anyOf": [
                                {"$ref": "#/components/schemas/Verdict"},
                                {"$ref": "#/components/schemas/EventEnvelope"},
                            ],
                            "description": (
                                "anyOf rather than oneOf: the handler's "
                                "auto-detect uses a non-discriminator sniff "
                                "(presence of ``specversion``); an envelope "
                                "payload may also nominally validate against "
                                "Verdict due to ``additionalProperties: "
                                "true``, so requiring exactly-one would "
                                "produce false negatives."
                            ),
                        },
                    },
                },
            },
            "responses": {
                "201": {
                    "description": "Verdict created.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["id"],
                                "properties": {
                                    "id": {"type": "string"},
                                },
                            },
                        },
                    },
                },
                "400": {
                    "description": (
                        "``envelope_invalid`` — CloudEvents envelope could "
                        "not be unwrapped (missing specversion/type/source/"
                        "id, or ``data`` is not a dict)."
                    ),
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "409": {
                    "description": "``duplicate`` — verdict id already in the store.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "422": {
                    "description": (
                        "``invalid_json`` (malformed body / non-object) or "
                        "``verdict_invalid`` (inner record missing required "
                        "fields: id, type, created_at). The envelope path "
                        "carries an ``envelope_version`` field on the error "
                        "body to let callers distinguish raw vs unwrapped."
                    ),
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "500": {
                    "description": (
                        "``internal_error`` — opaque store failure. "
                        "Store/SQLite messages are never surfaced to the "
                        "client (opensrm-9uow.1)."
                    ),
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
            },
        },
        "get": {
            "summary": "Query verdicts",
            "description": (
                "Returns an array of verdict records matching the supplied "
                "filters. All filters are optional; with no filters the "
                "store returns the most recent ``limit`` verdicts. Time "
                "filters use ISO-8601 timestamps."
            ),
            "operationId": "getVerdicts",
            "tags": ["verdicts"],
            "parameters": [
                {
                    "name": "service",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "string"},
                    "description": "Filter by service name (exact match).",
                },
                {
                    "name": "type",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "string"},
                    "description": (
                        "Filter by verdict type (e.g. slo_status, "
                        "drift_signal, outcome_resolution)."
                    ),
                },
                {
                    "name": "created_after",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "string", "format": "date-time"},
                    "description": "Inclusive lower bound on created_at.",
                },
                {
                    "name": "created_before",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "string", "format": "date-time"},
                    "description": "Exclusive upper bound on created_at.",
                },
                {
                    "name": "limit",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "integer", "default": 100, "minimum": 0},
                    "description": (
                        "Maximum number of records to return. "
                        "``limit=0`` is accepted by the handler and "
                        "returns an empty array (the underlying store "
                        "passes the value to SQL ``LIMIT 0``). No "
                        "server-side maximum is enforced."
                    ),
                },
            ],
            "responses": {
                "200": {
                    "description": "Array of verdict records (possibly empty).",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "array",
                                "items": {"$ref": "#/components/schemas/Verdict"},
                            },
                        },
                    },
                },
                "422": {
                    "description": (
                        "``invalid_parameter`` — query parameter rejected "
                        "(e.g. non-integer or negative ``limit``)."
                    ),
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "500": {
                    "description": "``internal_error`` — opaque store failure.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
            },
        },
    },
    "/verdicts/{verdict_id}": {
        "get": {
            "summary": "Get a verdict by id",
            "description": (
                "Returns the single verdict record with the given id. "
                "Verdicts are immutable so the returned shape is stable "
                "across reads. Returns 404 if the id is unknown."
            ),
            "operationId": "getVerdictById",
            "tags": ["verdicts"],
            "parameters": [
                {
                    "name": "verdict_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                    "description": "Unique verdict id.",
                },
            ],
            "responses": {
                "200": {
                    "description": "The verdict record.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Verdict"},
                        },
                    },
                },
                "404": {
                    "description": "No verdict with the given id.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "500": {
                    "description": "Opaque internal_error from the store layer.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
            },
        },
    },
    "/verdicts/{verdict_id}/ancestors": {
        "get": {
            "summary": "Get verdict ancestors",
            "description": (
                "Returns the ancestors of a verdict by walking the "
                "``parent_ids`` chain upward via the lineage index. The "
                "optional ``max_hops`` query parameter caps traversal "
                "depth (0 = unlimited)."
            ),
            "operationId": "getVerdictAncestors",
            "tags": ["verdicts"],
            "parameters": [
                {
                    "name": "verdict_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                    "description": "Verdict id whose ancestors are wanted.",
                },
                {
                    "name": "max_hops",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "integer", "minimum": 0},
                    "description": (
                        "Maximum hops to traverse. Omit (or set to 0) for "
                        "unlimited."
                    ),
                },
            ],
            "responses": {
                "200": {
                    "description": (
                        "Array of ancestor verdict records (possibly empty)."
                    ),
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "array",
                                "items": {"$ref": "#/components/schemas/Verdict"},
                            },
                        },
                    },
                },
                "422": {
                    "description": (
                        "``invalid_parameter`` — ``max_hops`` query "
                        "parameter rejected (non-integer or negative)."
                    ),
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "500": {
                    "description": "Opaque internal_error from the store layer.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
            },
        },
    },
    "/verdicts/{verdict_id}/descendants": {
        "get": {
            "summary": "Get verdict descendants",
            "description": (
                "Returns the descendants of a verdict by walking the "
                "lineage index downward (verdicts whose ``parent_ids`` "
                "transitively include this id)."
            ),
            "operationId": "getVerdictDescendants",
            "tags": ["verdicts"],
            "parameters": [
                {
                    "name": "verdict_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                    "description": "Verdict id whose descendants are wanted.",
                },
            ],
            "responses": {
                "200": {
                    "description": (
                        "Array of descendant verdict records (possibly empty)."
                    ),
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "array",
                                "items": {"$ref": "#/components/schemas/Verdict"},
                            },
                        },
                    },
                },
                "500": {
                    "description": "Opaque internal_error from the store layer.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
            },
        },
    },
    "/verdicts/{verdict_id}/outcome": {
        "post": {
            "summary": "Resolve a verdict's outcome (lineage-style)",
            "description": (
                "Creates a NEW verdict with ``type='outcome_resolution'`` "
                "and ``parent_ids=[original_id]``. The original verdict is "
                "never mutated — this is the v1.5 canonical resolution "
                "path. The new verdict id defaults to ``out-<original_id>`` "
                "if not supplied. Returns 404 if the original verdict does "
                "not exist; 409 ``duplicate`` if the synthesized outcome "
                "id is already taken."
            ),
            "operationId": "postVerdictOutcome",
            "tags": ["verdicts"],
            "parameters": [
                {
                    "name": "verdict_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                    "description": "Id of the original verdict being resolved.",
                },
            ],
            "requestBody": {
                "required": False,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "string",
                                    "description": (
                                        "Optional explicit id for the new "
                                        "outcome_resolution verdict. "
                                        "Defaults to ``out-<original_id>``."
                                    ),
                                },
                                "outcome_status": {
                                    "type": "string",
                                    "description": (
                                        "Outcome status label. Defaults "
                                        "to 'confirmed'."
                                    ),
                                },
                                "resolution": {
                                    "type": "string",
                                    "description": "Free-text resolution summary.",
                                },
                                "reasoning": {
                                    "type": "string",
                                    "description": "Free-text reasoning trace.",
                                },
                                "pipeline_latency_ms": {
                                    "type": "number",
                                    "description": (
                                        "Optional end-to-end pipeline "
                                        "latency for telemetry."
                                    ),
                                },
                            },
                        },
                    },
                },
            },
            "responses": {
                "201": {
                    "description": "Outcome_resolution verdict created.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["id"],
                                "properties": {
                                    "id": {"type": "string"},
                                },
                            },
                        },
                    },
                },
                "404": {
                    "description": (
                        "``not_found`` — original verdict id is unknown."
                    ),
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "409": {
                    "description": (
                        "``duplicate`` — synthesized outcome verdict id is "
                        "already in the store."
                    ),
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "422": {
                    "description": (
                        "``invalid_json`` — request body is not a valid "
                        "JSON object."
                    ),
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "500": {
                    "description": "``internal_error`` — opaque store failure.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
            },
        },
    },
    "/verdicts/{verdict_id}/override": {
        "post": {
            "summary": "Apply an operator override (mutation-style)",
            "description": (
                "Mutation-style override path (opensrm-jmy.18): mutates "
                "the original verdict's ``outcome`` field in place via "
                "CAS in ``Store.update_outcome``. The single exception to "
                "verdict immutability and the ONLY endpoint that writes "
                "back to an existing verdict. Intended for invocation by "
                "the override-adapter sidecar exclusively — the sidecar "
                "is the privacy boundary, so core trusts the wire "
                "(``pre_redacted=True``). The body's ``decision_id`` MUST "
                "match the path's ``verdict_id``; mismatch returns 400 "
                "``decision_id_mismatch``. Returns 409 ``conflict`` if "
                "the verdict is already overridden."
            ),
            "operationId": "postVerdictOverride",
            "tags": ["verdicts"],
            "parameters": [
                {
                    "name": "verdict_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                    "description": (
                        "Id of the verdict to override. Must match the "
                        "body's decision_id."
                    ),
                },
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["decision_id", "timestamp"],
                            "properties": {
                                "decision_id": {
                                    "type": "string",
                                    "description": (
                                        "Verdict id being overridden. "
                                        "Must equal the path verdict_id."
                                    ),
                                },
                                "timestamp": {
                                    "type": "string",
                                    "format": "date-time",
                                    "description": (
                                        "tz-aware ISO-8601 timestamp of "
                                        "the override event."
                                    ),
                                },
                                "actor": {
                                    "type": "string",
                                    "description": (
                                        "Operator identifier (already "
                                        "redacted by the sidecar)."
                                    ),
                                },
                                "reason": {
                                    "type": "string",
                                    "description": (
                                        "Operator-supplied rationale "
                                        "(already redacted by the sidecar)."
                                    ),
                                },
                            },
                            "additionalProperties": True,
                        },
                    },
                },
            },
            "responses": {
                "200": {
                    "description": "Override applied successfully.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["id", "status"],
                                "properties": {
                                    "id": {"type": "string"},
                                    "status": {
                                        "type": "string",
                                        "enum": ["overridden"],
                                    },
                                },
                            },
                        },
                    },
                },
                "400": {
                    "description": (
                        "``decision_id_mismatch`` — path verdict_id != "
                        "body decision_id."
                    ),
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "404": {
                    "description": (
                        "``verdict_not_found`` — path verdict_id is "
                        "unknown."
                    ),
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "409": {
                    "description": (
                        "``conflict`` — CAS predicate rejected the write "
                        "(verdict already overridden)."
                    ),
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "422": {
                    "description": (
                        "``invalid_json`` (malformed body) or "
                        "``validation_error`` (override event failed "
                        "construction — bad timestamp, missing required "
                        "fields, or fallthrough from ``apply_override_to_"
                        "verdict``)."
                    ),
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "500": {
                    "description": "Opaque internal_error from the store layer.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
            },
        },
    },
}


SCHEMAS: dict[str, dict] = {
    "Verdict": {
        "type": "object",
        "description": (
            "Immutable verdict record. Additional implementation-specific "
            "fields are permitted (the store preserves the JSON blob "
            "verbatim)."
        ),
        "required": ["id", "type", "created_at"],
        "properties": {
            "id": {
                "type": "string",
                "description": "Globally unique verdict id.",
            },
            "type": {
                "type": "string",
                "description": (
                    "Verdict type discriminator. Common values include "
                    "``slo_status``, ``drift_signal``, ``outcome_resolution``."
                ),
                "examples": ["slo_status", "drift_signal", "outcome_resolution"],
            },
            "created_at": {
                "type": "string",
                "format": "date-time",
                "description": "ISO-8601 creation timestamp (tz-aware).",
            },
            "service": {
                "type": "string",
                "description": "Service name this verdict pertains to.",
            },
            "parent_ids": {
                "type": ["array", "null"],
                "items": {"type": "string"},
                "description": (
                    "Lineage parents. Populated on derived verdicts "
                    "(e.g. outcome_resolution); null/absent on roots."
                ),
            },
            "chain_depth": {
                "type": "integer",
                "minimum": 0,
                "description": "Depth in the lineage chain (0 = root).",
            },
            "outcome": {
                "type": ["object", "null"],
                "description": (
                    "Outcome metadata. Absent or null until resolution; "
                    "mutated in place by POST /verdicts/{id}/override (the "
                    "shape is defined by ``apply_override_to_verdict`` in "
                    "nthlayer-common). No enum is enforced server-side."
                ),
                "additionalProperties": True,
            },
            "outcome_status": {
                "type": "string",
                "description": (
                    "Top-level outcome status, set on outcome_resolution "
                    "verdicts created by POST /verdicts/{id}/outcome. "
                    "Defaults to ``confirmed`` when the request body omits "
                    "it; otherwise pass-through from the body. No enum is "
                    "enforced server-side."
                ),
            },
            "resolution": {
                "description": (
                    "Operator-supplied resolution detail on "
                    "outcome_resolution verdicts. Shape is caller-defined."
                ),
            },
            "reasoning": {
                "description": (
                    "Operator-supplied free-form reasoning on "
                    "outcome_resolution verdicts."
                ),
            },
            "pipeline_latency_ms": {
                "type": ["number", "null"],
                "description": (
                    "Optional pipeline-latency annotation. Pass-through "
                    "from the outcome request body."
                ),
            },
        },
        "additionalProperties": True,
    },
    "EventEnvelope": {
        "type": "object",
        "description": (
            "CloudEvents v1.0 envelope. POST /verdicts and POST "
            "/assessments auto-detect this shape via the top-level "
            "``specversion`` field and unwrap before validating the "
            "inner record carried in ``data``. The envelope is reused "
            "across routes; the shape of ``data`` is determined by the "
            "wrapping route (Verdict for /verdicts, Assessment for "
            "/assessments) and validated by that route's handler, not "
            "by this schema."
        ),
        "required": ["specversion", "type", "source", "id", "data"],
        "properties": {
            "specversion": {
                "type": "string",
                "enum": ["1.0"],
                "description": "CloudEvents spec version. Must be '1.0'.",
            },
            "type": {
                "type": "string",
                "description": "Event type (e.g. ``com.nthlayer.verdict.v1``).",
            },
            "source": {
                "type": "string",
                "description": "URI identifying the event producer.",
            },
            "id": {
                "type": "string",
                "description": "Envelope id (independent of the inner record id).",
            },
            "time": {
                "type": "string",
                "format": "date-time",
                "description": "Optional envelope emission timestamp.",
            },
            "datacontenttype": {
                "type": "string",
                "description": (
                    "Optional content type of ``data``. Typically "
                    "``application/json``."
                ),
            },
            "data": {
                "type": "object",
                "additionalProperties": True,
                "description": (
                    "Inner record. Type depends on the wrapping route — "
                    "Verdict for /verdicts, Assessment for "
                    "/assessments. Validated by the route handler "
                    "after unwrap; not constrained at the envelope "
                    "schema layer."
                ),
            },
        },
        "additionalProperties": True,
    },
}
