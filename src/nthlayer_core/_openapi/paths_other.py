"""OpenAPI spec fragment for change-freezes, heartbeats, manifests, suppressions, component-state, and monitoring.

Authored under opensrm-tu04.1.4 — covers the 13 remaining routes outside
the verdicts/cases/assessments and health/openapi groups.

Contributes 6 component schemas:
  - ChangeFreeze, Heartbeat, Manifest, Suppression,
    ComponentState, StuckActionRequest.
"""
from __future__ import annotations

PATHS: dict[str, dict] = {
    "/change-freezes": {
        "post": {
            "summary": "Declare a change freeze",
            "description": (
                "Creates a named window during which automated responses are "
                "blocked. The body must include name, declared_by, declared_at, "
                "active_from, and active_until; active_until must strictly "
                "follow active_from. Names are reserved while the freeze "
                "row exists: ``change_freezes.name`` is the SQL primary "
                "key (store.py:81), so a 409 ``duplicate`` is returned "
                "even when the prior freeze of the same name has been "
                "lifted. Lifted freezes are pruned after the configured "
                "retention (default 90 days, store.py:853), after which "
                "the name may be reused."
            ),
            "operationId": "postChangeFreeze",
            "tags": ["change-freezes"],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": [
                                "name",
                                "declared_by",
                                "declared_at",
                                "active_from",
                                "active_until",
                            ],
                            "properties": {
                                "name": {"type": "string"},
                                "declared_by": {"type": "string"},
                                "declared_at": {"type": "string", "format": "date-time"},
                                "active_from": {"type": "string", "format": "date-time"},
                                "active_until": {"type": "string", "format": "date-time"},
                                "reason": {"type": "string"},
                            },
                            "additionalProperties": True,
                        },
                    },
                },
            },
            "responses": {
                "201": {
                    "description": "Change freeze created.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["name"],
                                "properties": {"name": {"type": "string"}},
                            },
                        },
                    },
                },
                "409": {
                    "description": (
                        "``duplicate`` — a change freeze with this name "
                        "exists or has been recently lifted but not yet "
                        "pruned. Names are reserved while the row exists "
                        "(PK on store.py:81); a lifted freeze keeps its "
                        "name until the retention pruner runs (default "
                        "90 days, store.py:853). Use a fresh name for a "
                        "new freeze window unless you intend to wait "
                        "for pruning."
                    ),
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "422": {
                    "description": (
                        "``missing_fields`` — required body field absent; or "
                        "``invalid_parameter`` — ``active_from`` / "
                        "``active_until`` not valid ISO timestamps, or "
                        "``active_until`` is not strictly after "
                        "``active_from``."
                    ),
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "500": {
                    "description": "Store operation failed (opaque to client).",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
            },
        },
        "get": {
            "summary": "List active change freezes",
            "description": (
                "Returns the set of change freezes that are currently active "
                "according to their active_from / active_until window. Lifted "
                "freezes are excluded."
            ),
            "operationId": "getChangeFreezes",
            "tags": ["change-freezes"],
            "responses": {
                "200": {
                    "description": "Array of active change freezes.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "array",
                                "items": {"$ref": "#/components/schemas/ChangeFreeze"},
                            },
                        },
                    },
                },
                "500": {
                    "description": "Store operation failed (opaque to client).",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
            },
        },
    },
    "/change-freezes/{freeze_name}/lift": {
        "put": {
            "summary": "Lift a change freeze early",
            "description": (
                "Cancels an active change freeze before its scheduled "
                "active_until. The body must include lifted_by. Returns 404 if "
                "no freeze with that name exists."
            ),
            "operationId": "putChangeFreezeLift",
            "tags": ["change-freezes"],
            "parameters": [
                {
                    "name": "freeze_name",
                    "in": "path",
                    "required": True,
                    "description": "Name of the change freeze to lift.",
                    "schema": {"type": "string"},
                },
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["lifted_by"],
                            "properties": {"lifted_by": {"type": "string"}},
                        },
                    },
                },
            },
            "responses": {
                "200": {
                    "description": "Change freeze lifted.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["lifted", "name"],
                                "properties": {
                                    "lifted": {"type": "boolean"},
                                    "name": {"type": "string"},
                                },
                            },
                        },
                    },
                },
                "404": {
                    "description": (
                        "``not_found`` — no change freeze with this "
                        "name, OR the named freeze has already been "
                        "lifted. Lift is not idempotent on the wire: "
                        "``Store.lift_change_freeze`` only matches "
                        "rows where ``lifted_at IS NULL``, so the "
                        "second call 404s rather than no-opping."
                    ),
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "422": {
                    "description": (
                        "``missing_fields`` — ``lifted_by`` missing, empty, "
                        "or ``null`` (the handler treats all three "
                        "identically)."
                    ),
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "500": {
                    "description": "Store operation failed (opaque to client).",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
            },
        },
    },
    "/heartbeats": {
        "post": {
            "summary": "Record a component heartbeat",
            "description": (
                "Workers POST a liveness signal identifying the component and "
                "instance. The optional state field records arbitrary worker-"
                "specific status. Always returns 200 on success."
            ),
            "operationId": "postHeartbeat",
            "tags": ["heartbeats"],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["component", "instance_id"],
                            "properties": {
                                "component": {"type": "string"},
                                "instance_id": {"type": "string"},
                                "state": {
                                    "type": "object",
                                    "additionalProperties": True,
                                    "nullable": True,
                                },
                            },
                            "additionalProperties": True,
                        },
                    },
                },
            },
            "responses": {
                "200": {
                    "description": "Heartbeat recorded.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["ok"],
                                "properties": {"ok": {"type": "boolean"}},
                            },
                        },
                    },
                },
                "422": {
                    "description": (
                        "``missing_fields`` — request body missing "
                        "``component`` or ``instance_id``."
                    ),
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "500": {
                    "description": "Store operation failed (opaque to client).",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
            },
        },
        "get": {
            "summary": "List heartbeats with computed health",
            "description": (
                "Returns all known heartbeats with a derived health field. A "
                "component whose most recent heartbeat is older than the "
                "threshold (default 30 seconds, override via ?threshold=) is "
                "marked degraded."
            ),
            "operationId": "getHeartbeats",
            "tags": ["heartbeats"],
            "parameters": [
                {
                    "name": "threshold",
                    "in": "query",
                    "required": False,
                    "description": (
                        "Age in seconds beyond which a heartbeat is "
                        "treated as degraded. ``threshold=0`` is "
                        "accepted and marks every heartbeat with "
                        "``age_seconds > 0`` as degraded — "
                        "operationally useful for forcing the full "
                        "degraded set during diagnostics."
                    ),
                    "schema": {"type": "integer", "default": 30, "minimum": 0},
                },
            ],
            "responses": {
                "200": {
                    "description": "Array of heartbeats with health classification.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "array",
                                "items": {"$ref": "#/components/schemas/Heartbeat"},
                            },
                        },
                    },
                },
                "422": {
                    "description": (
                        "``invalid_parameter`` — ``threshold`` query "
                        "parameter rejected (non-integer or negative)."
                    ),
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "500": {
                    "description": "Store operation failed (opaque to client).",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
            },
        },
    },
    "/manifests": {
        "get": {
            "summary": "List loaded service manifests",
            "description": (
                "Returns every OpenSRM v2 service manifest currently loaded by "
                "the catalogue. Manifest authorship happens on disk — there is "
                "no POST /manifests endpoint."
            ),
            "operationId": "getManifests",
            "tags": ["manifests"],
            "responses": {
                "200": {
                    "description": "Array of loaded manifests.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "array",
                                "items": {"$ref": "#/components/schemas/Manifest"},
                            },
                        },
                    },
                },
            },
        },
    },
    "/manifests/-/reload": {
        "post": {
            "summary": "Reload manifests from disk",
            "description": (
                "Re-polls the catalogue source directory for added, removed, or "
                "changed manifest files and returns the list of services that "
                "changed. The path segment '-' is a literal sentinel chosen "
                "because no service is named '-'."
            ),
            "operationId": "postManifestsReload",
            "tags": ["manifests"],
            "responses": {
                "200": {
                    "description": "Reload completed; reports changed services and total count.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["changed", "total"],
                                "properties": {
                                    "changed": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "total": {"type": "integer"},
                                },
                            },
                        },
                    },
                },
            },
        },
    },
    "/manifests/{service}": {
        "get": {
            "summary": "Get a single manifest",
            "description": (
                "Returns the manifest for the named service from the in-memory "
                "catalogue. Returns 404 if no manifest with this service name "
                "is loaded."
            ),
            "operationId": "getManifest",
            "tags": ["manifests"],
            "parameters": [
                {
                    "name": "service",
                    "in": "path",
                    "required": True,
                    "description": "Service name from the manifest's metadata.",
                    "schema": {"type": "string"},
                },
            ],
            "responses": {
                "200": {
                    "description": "Manifest for the requested service.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Manifest"},
                        },
                    },
                },
                "404": {
                    "description": "No manifest with this service name is loaded.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
            },
        },
    },
    "/suppressions": {
        "post": {
            "summary": "Record a suppressed verdict",
            "description": (
                "Workers report verdicts they declined to act on (active "
                "incident, dedup window, hysteresis, etc.) so the suppression "
                "decisions are auditable. Required fields: component, reason, "
                "suppressed_verdict_id."
            ),
            "operationId": "postSuppression",
            "tags": ["suppressions"],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["component", "reason", "suppressed_verdict_id"],
                            "properties": {
                                "component": {"type": "string"},
                                "reason": {"type": "string"},
                                "suppressed_verdict_id": {"type": "string"},
                                "related_verdict_id": {"type": "string", "nullable": True},
                                "suppressed_at": {"type": "string", "format": "date-time"},
                            },
                            "additionalProperties": True,
                        },
                    },
                },
            },
            "responses": {
                "201": {
                    "description": "Suppression recorded.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["id"],
                                "properties": {"id": {"type": "integer"}},
                            },
                        },
                    },
                },
                "422": {
                    "description": (
                        "``missing_fields`` — request body missing one "
                        "of the required POST /suppressions fields."
                    ),
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "500": {
                    "description": "Store operation failed (opaque to client).",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
            },
        },
        "get": {
            "summary": "Query suppressions",
            "description": (
                "Returns suppression records filtered by component and/or "
                "creation time range. Default limit is 100; supply ?limit= to "
                "override."
            ),
            "operationId": "getSuppressions",
            "tags": ["suppressions"],
            "parameters": [
                {
                    "name": "component",
                    "in": "query",
                    "required": False,
                    "description": "Restrict to suppressions reported by this component.",
                    "schema": {"type": "string"},
                },
                {
                    "name": "created_after",
                    "in": "query",
                    "required": False,
                    "description": (
                        "Lower bound on suppression timestamp. Passed "
                        "verbatim to SQL string comparison; the handler "
                        "does NOT parse or validate ISO format, so a "
                        "malformed value silently degrades to a "
                        "lexicographic string compare. Send ISO-8601 "
                        "in UTC for stable ordering."
                    ),
                    "schema": {"type": "string"},
                },
                {
                    "name": "created_before",
                    "in": "query",
                    "required": False,
                    "description": (
                        "Upper bound on suppression timestamp. Same "
                        "verbatim-passthrough semantics as "
                        "``created_after`` — no ISO validation."
                    ),
                    "schema": {"type": "string"},
                },
                {
                    "name": "limit",
                    "in": "query",
                    "required": False,
                    "description": (
                        "Maximum number of records to return. ``limit=0`` is "
                        "accepted and returns an empty array; negative values "
                        "are rejected by the handler."
                    ),
                    "schema": {"type": "integer", "default": 100, "minimum": 0},
                },
            ],
            "responses": {
                "200": {
                    "description": "Array of suppression records.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "array",
                                "items": {"$ref": "#/components/schemas/Suppression"},
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
                    "description": "Store operation failed (opaque to client).",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
            },
        },
    },
    "/component-state/{component}": {
        "put": {
            "summary": "Persist component state",
            "description": (
                "Workers PUT an opaque JSON state blob (cursor, hysteresis, "
                "dedup cache, etc.) after each cycle so they can resume after "
                "crash. The body shape is worker-defined; core treats it as "
                "opaque."
            ),
            "operationId": "putComponentState",
            "tags": ["component-state"],
            "parameters": [
                {
                    "name": "component",
                    "in": "path",
                    "required": True,
                    "description": "Component name identifying the worker.",
                    "schema": {"type": "string"},
                },
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                    },
                },
            },
            "responses": {
                "200": {
                    "description": "State persisted.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["ok", "component"],
                                "properties": {
                                    "ok": {"type": "boolean"},
                                    "component": {"type": "string"},
                                },
                            },
                        },
                    },
                },
                "500": {
                    "description": "Store operation failed (opaque to client).",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
            },
        },
        "get": {
            "summary": "Retrieve component state",
            "description": (
                "Workers GET their previously-persisted state blob to resume "
                "from the last checkpoint. Returns 404 if no state has ever "
                "been written for this component."
            ),
            "operationId": "getComponentState",
            "tags": ["component-state"],
            "parameters": [
                {
                    "name": "component",
                    "in": "path",
                    "required": True,
                    "description": "Component name identifying the worker.",
                    "schema": {"type": "string"},
                },
            ],
            "responses": {
                "200": {
                    "description": "The component_state row previously persisted by the component.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ComponentState"},
                        },
                    },
                },
                "404": {
                    "description": "No state recorded for this component.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "500": {
                    "description": "Store operation failed (opaque to client).",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
            },
        },
    },
    "/monitoring/stuck-action-requests": {
        "get": {
            "summary": "List stuck action_request verdicts",
            "description": (
                "Diagnostic endpoint for the respond worker: returns "
                "action_request verdicts older than the threshold (default 60 "
                "seconds, override via ?threshold=) that still have no "
                "corresponding case. A non-empty list signals a silent failure "
                "in case creation."
            ),
            "operationId": "getStuckActionRequests",
            "tags": ["monitoring"],
            "parameters": [
                {
                    "name": "threshold",
                    "in": "query",
                    "required": False,
                    "description": (
                        "Age in seconds above which an unresolved "
                        "action_request is considered stuck. "
                        "``threshold=0`` is accepted and returns "
                        "every unresolved action_request — useful "
                        "for forcing the full open set during "
                        "diagnostics."
                    ),
                    "schema": {"type": "integer", "default": 60, "minimum": 0},
                },
            ],
            "responses": {
                "200": {
                    "description": "Count and list of stuck action_request verdicts.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["count", "stuck"],
                                "properties": {
                                    "count": {"type": "integer"},
                                    "stuck": {
                                        "type": "array",
                                        "items": {"$ref": "#/components/schemas/StuckActionRequest"},
                                    },
                                },
                            },
                        },
                    },
                },
                "422": {
                    "description": (
                        "``invalid_parameter`` — ``threshold`` query "
                        "parameter rejected (non-integer or negative)."
                    ),
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "500": {
                    "description": "Store operation failed (opaque to client).",
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
    "ChangeFreeze": {
        "type": "object",
        "description": (
            "A named window during which automated responses are blocked. "
            "``get_active_freezes`` returns the original POST body verbatim "
            "(stored in the ``content`` column), so the response shape is "
            "the request shape — required fields below mirror the handler's "
            "validation in ``post_change_freeze``."
        ),
        "required": [
            "name",
            "declared_by",
            "declared_at",
            "active_from",
            "active_until",
        ],
        "properties": {
            "name": {"type": "string"},
            "declared_by": {"type": "string"},
            "declared_at": {"type": "string", "format": "date-time"},
            "active_from": {"type": "string", "format": "date-time"},
            "active_until": {"type": "string", "format": "date-time"},
            "reason": {"type": "string"},
        },
        "additionalProperties": True,
    },
    "Heartbeat": {
        "type": "object",
        "description": (
            "A heartbeat row enriched with derived ``health`` and "
            "``age_seconds`` fields by "
            "``Store.get_heartbeats_with_health``. The derivation against "
            "the configured threshold is the entire purpose of this "
            "endpoint."
        ),
        "required": [
            "component",
            "instance_id",
            "last_seen",
            "health",
            "age_seconds",
        ],
        "properties": {
            "component": {"type": "string"},
            "instance_id": {"type": "string"},
            "last_seen": {"type": "string", "format": "date-time"},
            "state": {
                "type": "object",
                "additionalProperties": True,
                "nullable": True,
                "description": "Opaque worker-supplied state from the POST body, or null.",
            },
            "health": {
                "type": "string",
                "enum": ["healthy", "degraded"],
                "description": (
                    "``degraded`` when ``age_seconds`` exceeds the "
                    "``threshold`` query parameter (default 30)."
                ),
            },
            "age_seconds": {
                "type": "number",
                "description": "Seconds since ``last_seen``, rounded to one decimal.",
            },
        },
        "additionalProperties": True,
    },
    "Manifest": {
        "type": "object",
        "description": (
            "An OpenSRM v2 service manifest serialised by "
            "``catalogue.manifest_to_dict``. The shape is flat — there is "
            "no nested ``spec`` wrapper — and ``slos`` / ``dependencies`` "
            "are always present (possibly empty)."
        ),
        "required": [
            "name",
            "team",
            "tier",
            "type",
            "namespace",
            "source_format",
            "slos",
            "dependencies",
        ],
        "properties": {
            "name": {"type": "string"},
            "team": {"type": "string"},
            "tier": {"type": "string"},
            "type": {"type": "string"},
            "namespace": {"type": "string"},
            "source_format": {"type": "string"},
            "description": {"type": "string"},
            "labels": {
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
            "slos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                },
            },
            "dependencies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                },
            },
            "contracts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                },
            },
        },
        "additionalProperties": True,
    },
    "Suppression": {
        "type": "object",
        "description": (
            "An audit row recorded when a worker declined to act on a "
            "verdict (active incident, dedup window, hysteresis, etc.). "
            "Shape matches the ``suppressions`` table columns returned by "
            "``Store.query_suppressions`` (``SELECT *``)."
        ),
        "required": [
            "id",
            "component",
            "reason",
            "suppressed_verdict_id",
            "suppressed_at",
        ],
        "properties": {
            "id": {
                "type": "integer",
                "description": "Auto-increment row id from the suppressions table.",
            },
            "component": {"type": "string"},
            "reason": {"type": "string"},
            "suppressed_verdict_id": {"type": "string"},
            "related_verdict_id": {"type": "string", "nullable": True},
            "suppressed_at": {"type": "string", "format": "date-time"},
        },
        "additionalProperties": True,
    },
    "ComponentState": {
        "type": "object",
        "description": (
            "A worker's persisted processing state. Shape matches the "
            "``component_state`` table columns returned by "
            "``Store.get_component_state`` (``SELECT *``); the "
            "``hysteresis_state`` and ``dedup_cache`` JSON blobs are "
            "decoded into objects."
        ),
        "required": ["component"],
        "properties": {
            "component": {"type": "string"},
            "last_cursor": {"type": "string", "nullable": True},
            "hysteresis_state": {
                "type": "object",
                "additionalProperties": True,
                "nullable": True,
            },
            "dedup_cache": {
                "type": "object",
                "additionalProperties": True,
                "nullable": True,
            },
        },
        "additionalProperties": True,
    },
    "StuckActionRequest": {
        "description": (
            "A raw ``action_request`` verdict whose corresponding case has "
            "not yet been created. ``Store.get_stuck_action_requests`` "
            "returns the verdict's stored ``content`` blob verbatim — it "
            "does not derive ``deadline`` or ``age_seconds`` fields."
        ),
        "allOf": [{"$ref": "#/components/schemas/Verdict"}],
    },
}
