"""Per-path-group OpenAPI spec fragments.

Each module exports:
  PATHS: dict[str, dict]  — OpenAPI Path Item objects keyed by path.
  SCHEMAS: dict[str, dict]  — Component schemas this group contributes.

The leading underscore marks this as internal: consumers read the
assembled spec via openapi_spec.OPENAPI, not by importing individual
modules. Module names follow paths_<group>.py for discoverability.
"""
