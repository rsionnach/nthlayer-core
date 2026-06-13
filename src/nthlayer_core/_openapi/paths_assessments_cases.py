"""OpenAPI spec fragment for /assessments and /cases routes.

Authored for bead opensrm-tu04.1.3. Documents the two assessment routes
(create + query) and the six case routes (create, query, fetch-by-id,
acquire-lease, release-lease, resolve). All store-error responses fall
back to the shared ErrorEnvelope with the generic ``internal_error``
code per opensrm-9uow.1.
"""
from __future__ import annotations

PATHS: dict[str, dict] = {
    "/assessments": {
        "post": {
            "summary": "Create an assessment",
            "description": (
                "Persists an assessment record produced by a worker module "
                "(e.g. slo_status, drift_signal). Accepts either a CloudEvents "
                "v1.0 envelope (auto-detected via top-level ``specversion``) or "
                "a raw assessment dict. Returns 400 ``envelope_invalid`` when "
                "the envelope cannot be unwrapped, 422 ``assessment_invalid`` "
                "when the inner record is missing required fields, and 409 "
                "``duplicate`` when the assessment id already exists."
            ),
            "operationId": "postAssessment",
            "tags": ["assessments"],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "anyOf": [
                                {"$ref": "#/components/schemas/Assessment"},
                                {"$ref": "#/components/schemas/EventEnvelope"},
                            ],
                            "description": (
                                "anyOf rather than oneOf (mirrors "
                                "POST /verdicts): the handler's auto-"
                                "detect uses a non-discriminator sniff "
                                "(presence of ``specversion``); an "
                                "envelope payload may also nominally "
                                "validate against Assessment due to "
                                "``additionalProperties: true``, so "
                                "requiring exactly-one would produce "
                                "false negatives."
                            ),
                        },
                    },
                },
            },
            "responses": {
                "201": {
                    "description": "Assessment created.",
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
                    "description": "Envelope could not be unwrapped.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "409": {
                    "description": "An assessment with this id already exists.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "422": {
                    "description": "Inner record failed validation.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "500": {
                    "description": "Store operation failed (opaque per opensrm-9uow.1).",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
            },
        },
        "get": {
            "summary": "Query assessments",
            "description": (
                "Returns assessments matching the optional filters. Filters "
                "compose with AND semantics; omitted filters do not constrain "
                "the result set. The response is a JSON array ordered by the "
                "store's default ordering (newest first)."
            ),
            "operationId": "getAssessments",
            "tags": ["assessments"],
            "parameters": [
                {
                    "name": "service",
                    "in": "query",
                    "required": False,
                    "description": "Filter assessments by the service they apply to.",
                    "schema": {"type": "string"},
                },
                {
                    "name": "kind",
                    "in": "query",
                    "required": False,
                    "description": "Filter by assessment kind (e.g. slo_status, drift_signal).",
                    "schema": {"type": "string"},
                },
                {
                    "name": "limit",
                    "in": "query",
                    "required": False,
                    "description": (
                        "Maximum number of assessments to return. "
                        "``limit=0`` is accepted by the handler and "
                        "returns an empty array (matches tu04.1.2 I1 "
                        "fix). No server-side maximum is enforced."
                    ),
                    "schema": {"type": "integer", "default": 100, "minimum": 0},
                },
            ],
            "responses": {
                "200": {
                    "description": "Array of matching assessments.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "array",
                                "items": {"$ref": "#/components/schemas/Assessment"},
                            },
                        },
                    },
                },
                "422": {
                    "description": "Invalid query parameter (e.g. non-integer limit).",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "500": {
                    "description": "Store operation failed (opaque per opensrm-9uow.1).",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
            },
        },
    },
    "/cases": {
        "post": {
            "summary": "Create a case",
            "description": (
                "Creates a new operator-facing case from an underlying verdict. "
                "Requires ``id``, ``kind``, ``created_at``, and "
                "``underlying_verdict``. When ``priority`` is not supplied it is "
                "derived from ``blast_radius`` and ``has_active_incident`` "
                "(production+incident=P0, production=P1, staging+incident=P1, "
                "staging=P2, anything else=P3). Returns 409 ``duplicate`` when "
                "the case id already exists."
            ),
            "operationId": "postCase",
            "tags": ["cases"],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/CaseCreate"},
                    },
                },
            },
            "responses": {
                "201": {
                    "description": "Case created. Response echoes id and final priority.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["id", "priority"],
                                "properties": {
                                    "id": {"type": "string"},
                                    "priority": {
                                        "type": "string",
                                        "enum": ["P0", "P1", "P2", "P3"],
                                    },
                                },
                            },
                        },
                    },
                },
                "409": {
                    "description": "A case with this id already exists.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "422": {
                    "description": "Missing required fields.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "500": {
                    "description": "Store operation failed (opaque per opensrm-9uow.1).",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
            },
        },
        "get": {
            "summary": "Query cases",
            "description": (
                "Returns cases matching the optional state, priority, and "
                "service filters. Used by the bench TUI to drive the operator "
                "queue. Filters compose with AND semantics."
            ),
            "operationId": "getCases",
            "tags": ["cases"],
            "parameters": [
                {
                    "name": "state",
                    "in": "query",
                    "required": False,
                    "description": "Filter by case state (pending, leased, resolved).",
                    "schema": {
                        "type": "string",
                        "enum": ["pending", "leased", "resolved"],
                    },
                },
                {
                    "name": "priority",
                    "in": "query",
                    "required": False,
                    "description": "Filter by derived or explicit priority.",
                    "schema": {
                        "type": "string",
                        "enum": ["P0", "P1", "P2", "P3"],
                    },
                },
                {
                    "name": "service",
                    "in": "query",
                    "required": False,
                    "description": "Filter cases by the service they concern.",
                    "schema": {"type": "string"},
                },
                {
                    "name": "limit",
                    "in": "query",
                    "required": False,
                    "description": (
                        "Maximum number of cases to return. "
                        "``limit=0`` is accepted by the handler and "
                        "returns an empty array (matches tu04.1.2 I1 "
                        "fix). No server-side maximum is enforced."
                    ),
                    "schema": {"type": "integer", "default": 100, "minimum": 0},
                },
            ],
            "responses": {
                "200": {
                    "description": "Array of matching cases.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "array",
                                "items": {"$ref": "#/components/schemas/Case"},
                            },
                        },
                    },
                },
                "422": {
                    "description": "Invalid query parameter (e.g. non-integer limit).",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "500": {
                    "description": "Store operation failed (opaque per opensrm-9uow.1).",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
            },
        },
    },
    "/cases/{case_id}": {
        "get": {
            "summary": "Fetch a single case by id",
            "description": (
                "Returns the full case record including lease state and "
                "resolution metadata if any. Responds 404 ``not_found`` for "
                "unknown ids."
            ),
            "operationId": "getCaseById",
            "tags": ["cases"],
            "parameters": [
                {
                    "name": "case_id",
                    "in": "path",
                    "required": True,
                    "description": "The case identifier.",
                    "schema": {"type": "string"},
                },
            ],
            "responses": {
                "200": {
                    "description": "The requested case.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Case"},
                        },
                    },
                },
                "404": {
                    "description": "No case with this id.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "500": {
                    "description": "Store operation failed (opaque per opensrm-9uow.1).",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
            },
        },
    },
    "/cases/{case_id}/lease": {
        "put": {
            "summary": "Acquire a case lease",
            "description": (
                "Atomically claims ownership of the case for the named holder "
                "until ``expires_at``. Exactly one concurrent caller succeeds; "
                "the loser receives 409 ``lease_conflict``. ``expires_at`` must "
                "be a future ISO-8601 timestamp (naive timestamps are treated "
                "as UTC). Returns 404 if the case does not exist."
            ),
            "operationId": "putCaseLease",
            "tags": ["cases"],
            "parameters": [
                {
                    "name": "case_id",
                    "in": "path",
                    "required": True,
                    "description": "The case identifier.",
                    "schema": {"type": "string"},
                },
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/CaseLeaseAcquire"},
                    },
                },
            },
            "responses": {
                "200": {
                    "description": "Lease acquired.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["leased", "holder"],
                                "properties": {
                                    "leased": {"type": "boolean", "enum": [True]},
                                    "holder": {"type": "string"},
                                },
                            },
                        },
                    },
                },
                "404": {
                    "description": "No case with this id.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "409": {
                    "description": "Case is already leased by another operator.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "422": {
                    "description": "Missing fields or invalid ``expires_at``.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "500": {
                    "description": "Store operation failed (opaque per opensrm-9uow.1).",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
            },
        },
        "delete": {
            "summary": "Release a case lease",
            "description": (
                "Releases any lease currently held on the case — idempotent and "
                "intentionally admin-level (any caller may release; identity is "
                "not checked). Returns 200 whether or not a lease was held, and "
                "404 only when the case itself does not exist."
            ),
            "operationId": "deleteCaseLease",
            "tags": ["cases"],
            "parameters": [
                {
                    "name": "case_id",
                    "in": "path",
                    "required": True,
                    "description": "The case identifier.",
                    "schema": {"type": "string"},
                },
            ],
            "responses": {
                "200": {
                    "description": "Lease released (idempotent).",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["released"],
                                "properties": {
                                    "released": {"type": "boolean", "enum": [True]},
                                },
                            },
                        },
                    },
                },
                "404": {
                    "description": "No case with this id.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "500": {
                    "description": "Store operation failed (opaque per opensrm-9uow.1).",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
            },
        },
    },
    "/cases/{case_id}/resolve": {
        "put": {
            "summary": "Resolve a case",
            "description": (
                "Atomically transitions the case to ``resolved`` while binding "
                "the supplied ``resolution_id`` (a verdict id) as the closing "
                "decision. The store guards against double-resolve: a second "
                "attempt returns 409 ``already_resolved`` with the previously "
                "bound resolution id."
            ),
            "operationId": "putCaseResolve",
            "tags": ["cases"],
            "parameters": [
                {
                    "name": "case_id",
                    "in": "path",
                    "required": True,
                    "description": "The case identifier.",
                    "schema": {"type": "string"},
                },
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["resolution_id"],
                            "properties": {
                                "resolution_id": {
                                    "type": "string",
                                    "description": (
                                        "Verdict id representing the resolution "
                                        "decision."
                                    ),
                                },
                            },
                        },
                    },
                },
            },
            "responses": {
                "200": {
                    "description": "Case resolved.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["resolved", "resolution_id"],
                                "properties": {
                                    "resolved": {"type": "boolean", "enum": [True]},
                                    "resolution_id": {"type": "string"},
                                },
                            },
                        },
                    },
                },
                "404": {
                    "description": "No case with this id.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "409": {
                    "description": "Case has already been resolved.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "422": {
                    "description": "Missing ``resolution_id``.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorEnvelope"},
                        },
                    },
                },
                "500": {
                    "description": "Store operation failed (opaque per opensrm-9uow.1).",
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
    "Assessment": {
        "type": "object",
        "description": (
            "An assessment record produced by a worker module — a typed "
            "observation about a service's health (e.g. SLO status, drift "
            "signal). Inner shape varies by ``kind``; per-kind detail lives in "
            "the open-ended ``data`` field."
        ),
        "required": ["id", "kind", "service", "created_at"],
        "properties": {
            "id": {
                "type": "string",
                "description": "Unique assessment identifier.",
            },
            "kind": {
                "type": "string",
                "description": "Assessment type discriminator.",
                "examples": ["slo_status", "drift_signal"],
            },
            "service": {
                "type": "string",
                "description": "Service the assessment applies to.",
            },
            "created_at": {
                "type": "string",
                "format": "date-time",
                "description": "ISO-8601 creation timestamp.",
            },
            "data": {
                "type": "object",
                "additionalProperties": True,
                "description": "Kind-specific assessment payload.",
            },
        },
    },
    "Case": {
        "type": "object",
        "description": (
            "An operator-facing investigation derived from an underlying "
            "verdict. Cases progress through ``pending`` → (optionally "
            "``leased``) → ``resolved``. The lease step is not required: "
            "PUT /cases/{id}/resolve accepts a case in ``pending`` state "
            "directly. A lease names the operator currently working the "
            "case; ``null`` means no operator holds it."
        ),
        "required": ["id", "kind", "state", "created_at", "underlying_verdict"],
        "properties": {
            "id": {"type": "string", "description": "Unique case identifier."},
            "kind": {
                "type": "string",
                "description": "Case kind (e.g. correlation_alert).",
            },
            "state": {
                "type": "string",
                "enum": ["pending", "leased", "resolved"],
                "description": "Lifecycle state.",
            },
            "priority": {
                "type": "string",
                "enum": ["P0", "P1", "P2", "P3"],
                "description": (
                    "Derived from blast_radius × incident context if not "
                    "explicitly supplied at creation."
                ),
            },
            "service": {
                "type": "string",
                "description": "Service the case concerns.",
            },
            "blast_radius": {
                "type": "string",
                "description": "Deployment scope (production, staging, dev, ephemeral).",
            },
            "has_active_incident": {
                "type": "boolean",
                "description": "Whether an active incident was in flight at create time.",
            },
            "created_at": {
                "type": "string",
                "format": "date-time",
                "description": "ISO-8601 creation timestamp.",
            },
            "underlying_verdict": {
                "type": "string",
                "description": "Verdict id that originated this case.",
            },
            "resolution_id": {
                "type": "string",
                "description": "Verdict id bound when the case was resolved (resolved state only).",
            },
            "lease": {
                "oneOf": [
                    {"type": "null"},
                    {"$ref": "#/components/schemas/CaseLease"},
                ],
                "description": "Current lease, or null when unleased.",
            },
        },
    },
    "CaseLease": {
        "type": "object",
        "description": (
            "An exclusive claim by an operator on a case, bounded by an "
            "expiry timestamp. Acquired via PUT /cases/{id}/lease and released "
            "via DELETE on the same path."
        ),
        "required": ["holder", "expires_at"],
        "properties": {
            "holder": {
                "type": "string",
                "description": "Operator identifier currently holding the lease.",
            },
            "claimed_at": {
                "type": "string",
                "format": "date-time",
                "description": "When the lease was acquired.",
            },
            "expires_at": {
                "type": "string",
                "format": "date-time",
                "description": "When the lease lapses if not refreshed.",
            },
        },
    },
    "CaseCreate": {
        "type": "object",
        "description": (
            "Request body for POST /cases. ``priority`` is optional — when "
            "omitted it is derived from ``blast_radius`` and "
            "``has_active_incident``."
        ),
        "required": ["id", "kind", "created_at", "underlying_verdict"],
        "properties": {
            "id": {"type": "string"},
            "kind": {"type": "string"},
            "created_at": {"type": "string", "format": "date-time"},
            "underlying_verdict": {
                "type": "string",
                "description": "Verdict id that originated this case.",
            },
            "service": {"type": "string"},
            "priority": {
                "type": "string",
                "enum": ["P0", "P1", "P2", "P3"],
                "description": "Optional explicit priority; otherwise derived.",
            },
            "blast_radius": {
                "type": "string",
                "description": "Deployment scope used for priority derivation.",
            },
            "has_active_incident": {
                "type": "boolean",
                "description": "Incident context used for priority derivation.",
                "default": False,
            },
        },
        "additionalProperties": True,
    },
    "CaseLeaseAcquire": {
        "type": "object",
        "description": "Request body for PUT /cases/{id}/lease.",
        "required": ["holder", "expires_at"],
        "properties": {
            "holder": {
                "type": "string",
                "description": "Operator identifier acquiring the lease.",
            },
            "expires_at": {
                "type": "string",
                "format": "date-time",
                "description": (
                    "Future ISO-8601 timestamp at which the lease lapses. "
                    "Naive timestamps are treated as UTC."
                ),
            },
        },
    },
}
