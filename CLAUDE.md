# nthlayer-core

Reliability-critical HTTP API server for verdict store, case management, and related NthLayer core services. Python, Starlette/uvicorn, runtime component (stateful, no LLM).

<!-- AUTO-MANAGED: architecture -->
## Architecture

```
nthlayer-core/
  src/nthlayer_core/
    __init__.py   # Package marker
    cli.py        # CLI entry point: nthlayer serve [--host 0.0.0.0] [--port 8000]
    catalogue.py  # ManifestCatalogue: loads/caches OpenSRM manifests from dir, mtime-based polling (load, poll, get, list_all, to_dict_list); _manifest_to_dict() serialises to JSON-safe dict
    server.py     # Starlette app; full verdict+assessment+case+change-freeze+heartbeat+component-state+manifests HTTP API; set_store()/set_catalogue() injection; _derive_priority(); run_server(host, port) via uvicorn; CloudEvents auto-detect (opensrm-saun.1.2): body with top-level specversion → unwrap envelope before validation; without → raw dict (back-compat; v2 will require envelope); _ENVELOPE_REQUIRED_ATTRS=("specversion","type","source","id"); error split: 400 envelope_invalid (cannot unwrap) vs 422 record_invalid (inner record fails validation); both carry envelope_version field (None=envelope-level, "1.0"=inner record validated); helpers: _looks_like_envelope(), _unwrap_envelope(), _validate_required()
    store.py      # Unified SQLite store: Store class, 10-table schema v1.5.0, WAL mode
  tests/
    test_health.py      # Async ASGI test: GET /health returns 200 {"status": "ok"}
    test_api.py         # Full HTTP API test suite: TestHealth, TestPostVerdict, TestGetVerdicts (incl. time_range_filter_with_timezone_offset), TestLineage, TestOutcomeResolution, TestAssessments
    test_api_cases.py       # Cases + change-freeze API: TestPriorityDerivation, TestPostCase, TestGetCases, TestCaseLease, TestCaseResolve, TestChangeFreezes
    test_api_heartbeats.py      # Heartbeat + monitoring API: TestPostHeartbeat, TestGetHeartbeats, TestStuckActionRequests
    test_api_component_state.py # Component state persistence API: TestPutComponentState (save, overwrite, invalid_body), TestGetComponentState (get_existing, get_nonexistent, empty_dict_roundtrip, roundtrip_preserves_state)
    test_api_suppressions.py    # Suppressions API: TestPostSuppression (create_suppression, create_without_related_verdict, missing_component/reason/suppressed_verdict_id → 422), TestGetSuppressions (query_all, filter_by_component, filter_by_time_range, empty_result, suppression_contains_all_fields)
    test_api_manifests.py   # Manifest catalogue API: TestGetManifests (list_all, expected_fields, slo_includes_judgment_type), TestGetManifest (get_existing, get_nonexistent → 404), TestManifestsReload (new/modified/deleted file detection, no_changes), TestCatalogueUnit (empty/nonexistent dir, invalid yaml skipped)
    test_store.py           # Store test suite: schema, verdicts, lineage, cases, freezes, heartbeats, component state
    test_retention.py       # Retention test suite: TestVerdictRetention, TestAssessmentRetention, TestCaseRetention, TestChangeFreezeRetention, TestHeartbeatRetention, TestRekorAnchorsNeverPruned, TestRetentionGuards
  pyproject.toml    # name="nthlayer-core", version="1.0.0"; script: nthlayer → nthlayer_core.cli:main; deps: nthlayer-common, starlette, uvicorn, httpx
```

### HTTP API

Env vars: `NTHLAYER_STORE_PATH` — path to SQLite db (default `nthlayer.db`); `NTHLAYER_MANIFESTS_DIR` — directory of OpenSRM manifest YAML files (optional). Override with `set_store(store)` / `set_catalogue(catalogue)` for tests.

**Verdicts** (immutable — no PUT/PATCH):

| Method | Path | Response |
|--------|------|----------|
| `POST` | `/verdicts` | 201 `{id}` \| 400 `envelope_invalid` (malformed CE envelope, envelope_version=null) \| 422 `verdict_invalid` (missing id/type/created_at, envelope_version=null for raw; "1.0" for unwrapped envelope) \| 409 duplicate; `+00:00` timezone offset in `created_after`/`created_before` URL-safe (+ decoded as space handled) |
| `GET` | `/verdicts` | list; query params: `service`, `type`, `created_after`, `created_before`, `limit` (default 100) |
| `GET` | `/verdicts/{verdict_id}` | dict \| 404 not_found |
| `GET` | `/verdicts/{verdict_id}/ancestors` | list; query param: `max_hops` |
| `GET` | `/verdicts/{verdict_id}/descendants` | list |
| `POST` | `/verdicts/{verdict_id}/outcome` | 201 `{id}` — creates NEW `outcome_resolution` verdict with `parent_ids=[original_id]`; original never mutated |

**Assessments:**

| Method | Path | Response |
|--------|------|----------|
| `POST` | `/assessments` | 201 `{id}` \| 422 missing_fields (required: id, service, kind, created_at) \| 409 duplicate |
| `GET` | `/assessments` | list; query params: `service`, `kind`, `limit` (default 100) |

**Cases:**

| Method | Path | Response |
|--------|------|----------|
| `POST` | `/cases` | 201 `{id, priority}` \| 422 missing_fields (required: id, kind, created_at, underlying_verdict) \| 409 duplicate; priority explicit or derived from blast_radius + has_active_incident |
| `GET` | `/cases` | list; query params: `state`, `priority`, `service`, `limit` (default 100) |
| `GET` | `/cases/{case_id}` | dict \| 404 not_found; expired leases show state=pending |
| `PUT` | `/cases/{case_id}/lease` | 200 `{leased, holder}` \| 409 lease_conflict \| 422 expires_at in past or missing \| 404 not_found |
| `DELETE` | `/cases/{case_id}/lease` | 200 `{released}` \| 404 not_found |
| `PUT` | `/cases/{case_id}/resolve` | 200 `{resolved, resolution_id}` \| 409 already_resolved \| 422 missing resolution_id \| 404 not_found |

**Priority derivation** (`_derive_priority(blast_radius, has_active_incident)`):
- `("production", True)` → P0; `("production", False)` → P1
- `("staging", True)` → P1; `("staging", False)` → P2
- dev / ephemeral / None → P3 (default); uses lookup dict, not regex

**Change Freezes:**

| Method | Path | Response |
|--------|------|----------|
| `POST` | `/change-freezes` | 201 `{name}` \| 422 missing_fields or inverted range (active_until must be after active_from) \| 409 duplicate |
| `GET` | `/change-freezes` | list of active freezes (active_from ≤ now ≤ active_until, not lifted) |
| `PUT` | `/change-freezes/{freeze_name}/lift` | 200 `{lifted, name}` \| 422 missing lifted_by \| 404 not_found or already lifted |

**Heartbeats:**

| Method | Path | Response |
|--------|------|----------|
| `POST` | `/heartbeats` | 200 `{ok: true}` \| 422 missing_fields (required: component, instance_id; optional: state dict); upserts by (component, instance_id) |
| `GET` | `/heartbeats` | list with computed `health` ("healthy"\|"degraded") and `age_seconds`; query param: `threshold` (int seconds, default 30) |

**Component State:**

| Method | Path | Response |
|--------|------|----------|
| `PUT` | `/component-state/{component}` | 200 `{ok: true, component}` — save processing state (cursor, hysteresis, dedup cache); workers call after each cycle for crash recovery |
| `GET` | `/component-state/{component}` | 200 `{component, last_cursor, hysteresis_state, dedup_cache, ...}` \| 404 not_found — workers restore on startup to resume from last checkpoint |

**Suppressions:**

| Method | Path | Response |
|--------|------|----------|
| `POST` | `/suppressions` | 201 `{id}` \| 422 missing_fields (required: component, reason, suppressed_verdict_id; optional: related_verdict_id, suppressed_at) |
| `GET` | `/suppressions` | list; query params: `component`, `created_after`, `created_before`, `limit` (default 100) |

**Manifests** (read from `ManifestCatalogue`, populated from `NTHLAYER_MANIFESTS_DIR`):

| Method | Path | Response |
|--------|------|----------|
| `GET` | `/manifests` | list of all loaded manifests as dicts (name, team, tier, type, namespace, source_format, slos, dependencies, contracts) |
| `GET` | `/manifests/{service_name}` | single manifest dict \| 404 not_found |
| `POST` | `/manifests/-/reload` | 200 `{changed: [...], total: N}` — triggers `catalogue.poll()`, returns changed service names and new total count |

**Monitoring:**

| Method | Path | Response |
|--------|------|----------|
| `GET` | `/monitoring/stuck-action-requests` | `{count, stuck: [...]}` — action_request verdicts older than threshold with no corresponding case; query param: `threshold` (int seconds, default 60) |

**Other:**

- `GET /health` → `{"status": "ok"}` — liveness check

**outcome_resolution verdict fields:** `id` (default `out-{original_id}`), `type="outcome_resolution"`, `service` (copied from original), `created_at` (now UTC), `parent_ids=[original_id]`, `chain_depth=original.chain_depth+1`, `pipeline_latency_ms`, `outcome_status` (default `"confirmed"`), `resolution`, `reasoning`.

### CLI

```bash
nthlayer serve [--host 0.0.0.0] [--port 8000]   # start HTTP server
nthlayer -V                                       # print version
```

### Store

Unified SQLite store owned exclusively by the core process. Workers and bench access via the HTTP API — never directly.

**Schema v1.5.0** — 10 tables (string IDs, JSON TEXT content):

| Table | Purpose |
|-------|---------|
| `verdicts` | Immutable verdict records with lineage |
| `assessments` | Component outputs that are not decisions |
| `cases` | Bench domain model with lease management |
| `change_freezes` | RBAC §7 change freeze documents |
| `heartbeats` | Component liveness (upsert per instance) |
| `component_state` | Persistent state across restarts (cursor, hysteresis, dedup cache) |
| `suppressions` | Suppression audit trail (POST/GET API live; not deferred) |
| `rekor_anchors` | Forward-compat for v2 Rekor anchoring (empty in v1.5) |
| `lineage` | Pre-computed transitive closure of verdict ancestry |
| `schema_meta` | Schema version tracking |

**Design decisions:**
- WAL mode + `PRAGMA synchronous=NORMAL` + `busy_timeout=5000` — concurrent reads without blocking writes
- Thread-local connection pool — one connection per thread, safe for multi-threaded server
- `BEGIN IMMEDIATE` for all writes — prevents write conflicts under concurrent load
- Transitive lineage closure computed at write time via `INSERT OR IGNORE` — fast ancestor/descendant queries
- Expired leases revert to pending in presentation layer (`_apply_effective_state`) — no DB write, avoids background sweep process
- Retention: verdicts only pruned when old AND no younger descendant in lineage AND not referenced by a surviving case; `rekor_anchors` never pruned; active change freezes always preserved

**Public API (`Store`):**
- `put_verdict(verdict)` → `str` — writes verdict + populates lineage index
- `get_verdict(id)` → `dict | None`
- `query_verdicts(*, service, verdict_type, created_after, created_before, limit=100)` → `list[dict]`
- `ancestors_of(verdict_id, max_hops=None)` → `list[dict]` — ordered by hop distance
- `descendants_of(verdict_id)` → `list[dict]`
- `put_assessment / get_assessment / query_assessments`
- `put_case(case)` → `str`; `get_case(id)` → `dict | None`; `query_cases(*, state, priority, service, limit=100)` → `list[dict]`
- `acquire_lease(case_id, holder, expires_at)` → `bool` — atomic; acquirable if pending or lease expired
- `release_lease(case_id)` → `bool`; `resolve_case(case_id, resolution_id)` → `bool`
- `put_change_freeze / lift_change_freeze / get_active_freezes`
- `put_heartbeat(component, instance_id, state=None)` — upsert by (component, instance_id); `get_heartbeats()` → raw rows; `get_heartbeats_with_health(degraded_threshold_seconds=30)` → rows with computed `health` and `age_seconds` fields
- `get_stuck_action_requests(threshold_seconds=60)` → `list[dict]` — action_request verdicts older than cutoff with no case referencing them via `underlying_verdict`
- `put_component_state / get_component_state` — JSON sub-fields (hysteresis_state, dedup_cache) auto-serialized; empty dicts preserved on roundtrip
- `put_suppression(component, reason, suppressed_verdict_id, *, related_verdict_id=None, suppressed_at=None)` → `int` (row id); `query_suppressions(*, component=None, created_after=None, created_before=None, limit=100)` → `list[dict]`
- `run_retention(retention=None)` → `dict[str, int]` — prune expired rows per policy; defaults: verdicts/cases=365d, assessments/change_freezes/suppressions=90d, heartbeats=1d; raises `ValueError` if any window < 1
- `table_exists(name)` → `bool`
- `close()` — releases thread-local connection
<!-- END AUTO-MANAGED -->

<!-- AUTO-MANAGED: build-commands -->
## Commands

```bash
# Run tests
uv run pytest

# Install (editable)
uv pip install -e .
```
<!-- END AUTO-MANAGED -->

## Dependencies

- `nthlayer-common>=0.1.8` (editable local, path `../nthlayer-common`) — shared utilities, verdict model
- `starlette>=0.40` — ASGI web framework
- `uvicorn>=0.30` — ASGI server
- `httpx>=0.27` — HTTP client (also used in tests via `ASGITransport`)

Dev: `pytest>=8.2`, `pytest-asyncio>=0.23` (`asyncio_mode = "auto"`), `httpx>=0.27`

## Documentation

- `README.md` — added 2026-04-28; project-level overview for GitHub and contributors
