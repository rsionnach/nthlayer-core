"""OpenAPI spec fragment for /health.

The simplest endpoint — used as the worked example in tu04.1.1.
"""
from __future__ import annotations

PATHS: dict[str, dict] = {
    "/health": {
        "get": {
            "summary": "Liveness probe",
            "description": (
                "Returns 200 with a fixed payload as long as the ASGI app is "
                "running. Does not check store connectivity — for that, query "
                "any /verdicts route and rely on the 5xx contract."
            ),
            "operationId": "getHealth",
            "tags": ["meta"],
            "responses": {
                "200": {
                    "description": "Server is running.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["status"],
                                "properties": {
                                    "status": {"type": "string", "enum": ["ok"]},
                                },
                            },
                            "examples": {
                                "ok": {"value": {"status": "ok"}},
                            },
                        },
                    },
                },
            },
        },
    },
}

SCHEMAS: dict[str, dict] = {}
