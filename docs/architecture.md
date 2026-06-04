# nthlayer-core architecture

Source layout, store schema, and the design decisions behind the
single-writer SQLite store. The hard rules in `CLAUDE.md` are
canonical for runtime invariants — this file is the "what lives where"
reference.

## Source layout

```
nthlayer-core/
  src/nthlayer_core/
    __init__.py
    cli.py        # nthlayer serve [--host 0.0.0.0] [--port 8000]
    catalogue.py  # ManifestCatalogue: loads/caches OpenSRM manifests
                  # from dir, mtime-based polling (load, poll, get,
                  # list_all, to_dict_list). _manifest_to_dict()
                  # serialises to JSON-safe dict.
    server.py     # Starlette app: full verdict + assessment + case +
                  # change-freeze + heartbeat + component-state +
                  # manifests + suppressions HTTP API. set_store() /
                  # set_catalogue() injection. _derive_priority().
                  # run_server(host, port) via uvicorn.
                  # CloudEvents auto-detect (opensrm-saun.1.2): body
                  # with top-level specversion → unwrap envelope
                  # before validation; without → raw dict (back-compat;
                  # v2 will require envelope).
                  # _ENVELOPE_REQUIRED_ATTRS=
                  #   ("specversion","type","source","id")
                  # Error split: 400 envelope_invalid (cannot unwrap)
                  # vs 422 record_invalid (inner record fails
                  # validation). Both carry envelope_version
                  # (None=envelope-level, "1.0"=inner record
                  # validated). Helpers: _looks_like_envelope(),
                  # _unwrap_envelope(), _validate_required().
                  # _store_error_response(handler, exc, **context):
                  # logs full exception server-side via structlog
                  # (core_store_error event), returns generic
                  # {"error":"internal_error"} 500 to client (no raw
                  # SQLite strings leak, opensrm-9uow.1).
                  # TestStoreErrorOpacity (3 tests in test_api.py)
                  # validates opacity.
                  # post_verdict_override handler (opensrm-jmy.18):
                  # mutation-style POST /verdicts/{verdict_id}/override
                  # — coerces ISO timestamp string to datetime, calls
                  # apply_override_to_verdict with pre_redacted=True
                  # (privacy applied once at sidecar boundary), returns
                  # 200 {id, status:"overridden"} / 404 verdict_not_found
                  # / 409 conflict / 422 validation_error / 400
                  # decision_id_mismatch (path vs body decision_id
                  # mismatch guard).
    store.py      # Unified SQLite store: Store class formally
                  # implements VerdictStore ABC (opensrm-jmy.18 B0).
                  # 10-table schema v1.5.0, WAL mode.
  tests/          # Full HTTP API + store + retention test suite
  tests/smoke/    # Walks every module via pkgutil + asserts every
                  # __all__ resolves; asserts CLI on PATH + --help
                  # exits 0
  pyproject.toml  # name="nthlayer-core", version="1.0.0"; script:
                  # nthlayer → nthlayer_core.cli:main; deps:
                  # nthlayer-common, starlette, uvicorn, httpx
```

## HTTP API

### Verdicts (immutable — no PUT/PATCH)

| Method | Path | Response |
|--------|------|----------|
| `POST` | `/verdicts` | 201 `{id}` \| 400 `envelope_invalid` (malformed CE envelope, envelope_version=null) \| 422 `verdict_invalid` (missing id/type/created_at; envelope_version=null for raw, "1.0" for unwrapped envelope) \| 409 duplicate. `+00:00` timezone offset in `created_after`/`created_before` URL-safe (+ decoded as space handled). |
| `GET` | `/verdicts` | list; query params: `service`, `type`, `created_after`, `created_before`, `limit` (default 100). |
| `GET` | `/verdicts/{verdict_id}` | dict \| 404 not_found. |
| `GET` | `/verdicts/{verdict_id}/ancestors` | list; query param: `max_hops`. |
| `GET` | `/verdicts/{verdict_id}/descendants` | list. |
| `POST` | `/verdicts/{verdict_id}/outcome` | 201 `{id}` — creates NEW `outcome_resolution` verdict with `parent_ids=[original_id]`; original never mutated. |
| `POST` | `/verdicts/{verdict_id}/override` | 200 `{id, status:"overridden"}` — mutation-style; mutates original verdict's outcome in place (opensrm-jmy.18) \| 400 `decision_id_mismatch` \| 404 `verdict_not_found` \| 409 `conflict` (existing override differs) \| 422 `validation_error` (terminal status / schema failure). |

`outcome_resolution` verdict fields: `id` (default
`out-{original_id}`), `type="outcome_resolution"`, `service` (copied
from original), `created_at` (now UTC), `parent_ids=[original_id]`,
`chain_depth=original.chain_depth+1`, `pipeline_latency_ms`,
`outcome_status` (default `"confirmed"`), `resolution`, `reasoning`.

### Assessments

| Method | Path | Response |
|--------|------|----------|
| `POST` | `/assessments` | 201 `{id}` \| 422 missing_fields (required: id, service, kind, created_at) \| 409 duplicate. |
| `GET` | `/assessments` | list; query params: `service`, `kind`, `limit` (default 100). |

### Cases

| Method | Path | Response |
|--------|------|----------|
| `POST` | `/cases` | 201 `{id, priority}` \| 422 missing_fields (required: id, kind, created_at, underlying_verdict) \| 409 duplicate. Priority explicit or derived from blast_radius + has_active_incident. |
| `GET` | `/cases` | list; query params: `state`, `priority`, `service`, `limit` (default 100). |
| `GET` | `/cases/{case_id}` | dict \| 404 not_found; expired leases show state=pending. |
| `PUT` | `/cases/{case_id}/lease` | 200 `{leased, holder}` \| 409 lease_conflict \| 422 expires_at in past or missing \| 404 not_found. |
| `DELETE` | `/cases/{case_id}/lease` | 200 `{released}` \| 404 not_found. |
| `PUT` | `/cases/{case_id}/resolve` | 200 `{resolved, resolution_id}` \| 409 already_resolved \| 422 missing resolution_id \| 404 not_found. |

Priority derivation (`_derive_priority(blast_radius,
has_active_incident)`):

- `("production", True)` → P0
- `("production", False)` → P1
- `("staging", True)` → P1
- `("staging", False)` → P2
- dev / ephemeral / None → P3 (default)

Uses a lookup dict, not regex.

### Change Freezes

| Method | Path | Response |
|--------|------|----------|
| `POST` | `/change-freezes` | 201 `{name}` \| 422 missing_fields or inverted range (active_until must be after active_from) \| 409 duplicate. |
| `GET` | `/change-freezes` | list of active freezes (active_from ≤ now ≤ active_until, not lifted). |
| `PUT` | `/change-freezes/{freeze_name}/lift` | 200 `{lifted, name}` \| 422 missing lifted_by \| 404 not_found or already lifted. |

### Heartbeats

| Method | Path | Response |
|--------|------|----------|
| `POST` | `/heartbeats` | 200 `{ok: true}` \| 422 missing_fields (required: component, instance_id; optional: state dict). Upserts by (component, instance_id). |
| `GET` | `/heartbeats` | list with computed `health` ("healthy"/"degraded") and `age_seconds`; query param: `threshold` (int seconds, default 30). |

### Component State

| Method | Path | Response |
|--------|------|----------|
| `PUT` | `/component-state/{component}` | 200 `{ok: true, component}` — save processing state (cursor, hysteresis, dedup cache); workers call after each cycle for crash recovery. |
| `GET` | `/component-state/{component}` | 200 `{component, last_cursor, hysteresis_state, dedup_cache, ...}` \| 404 not_found — workers restore on startup to resume from last checkpoint. |

### Suppressions

| Method | Path | Response |
|--------|------|----------|
| `POST` | `/suppressions` | 201 `{id}` \| 422 missing_fields (required: component, reason, suppressed_verdict_id; optional: related_verdict_id, suppressed_at). |
| `GET` | `/suppressions` | list; query params: `component`, `created_after`, `created_before`, `limit` (default 100). |

### Manifests (read from `ManifestCatalogue`)

| Method | Path | Response |
|--------|------|----------|
| `GET` | `/manifests` | list of all loaded manifests as dicts (name, team, tier, type, namespace, source_format, slos, dependencies, contracts). |
| `GET` | `/manifests/{service_name}` | single manifest dict \| 404 not_found. |
| `POST` | `/manifests/-/reload` | 200 `{changed: [...], total: N}` — triggers `catalogue.poll()`, returns changed service names and new total count. |

### Monitoring

| Method | Path | Response |
|--------|------|----------|
| `GET` | `/monitoring/stuck-action-requests` | `{count, stuck: [...]}` — action_request verdicts older than threshold with no corresponding case; query param: `threshold` (int seconds, default 60). |

### Other

- `GET /health` → `{"status": "ok"}` — liveness check.

## Store (SQLite, v1.5.0 schema)

Unified SQLite store, **owned exclusively by the core process**.
Workers and bench access via the HTTP API — never directly.

### Tables (10)

| Table | Purpose |
|-------|---------|
| `verdicts` | Immutable verdict records with lineage. |
| `assessments` | Component outputs that are not decisions. |
| `cases` | Bench domain model with lease management. |
| `change_freezes` | RBAC §7 change freeze documents. |
| `heartbeats` | Component liveness (upsert per instance). |
| `component_state` | Persistent state across restarts (cursor, hysteresis, dedup cache). |
| `suppressions` | Suppression audit trail (POST/GET API live; not deferred). |
| `rekor_anchors` | Forward-compat for v2 Rekor anchoring (empty in v1.5). |
| `lineage` | Pre-computed transitive closure of verdict ancestry. |
| `schema_meta` | Schema version tracking. |

### Design decisions

- WAL mode + `PRAGMA synchronous=NORMAL` + `busy_timeout=5000` —
  concurrent reads without blocking writes.
- Thread-local connection pool — one connection per thread, safe for
  multi-threaded server.
- `BEGIN IMMEDIATE` for all writes — prevents write conflicts under
  concurrent load.
- Transitive lineage closure computed at write time via `INSERT OR
  IGNORE` — fast ancestor/descendant queries.
- Expired leases revert to pending in the presentation layer
  (`_apply_effective_state`) — no DB write, avoids a background sweep
  process.
- Retention: verdicts only pruned when old AND no younger descendant
  in lineage AND not referenced by a surviving case; `rekor_anchors`
  never pruned; active change freezes always preserved.

### Public API (`Store`)

VerdictStore ABC methods (opensrm-jmy.18 B0 — used by
`apply_override_to_verdict` and other nthlayer-common callers):

- `put(verdict: Verdict) -> None` — serialises via `to_dict()` and
  writes; also populates lineage index.
- `get(id: str) -> Verdict | None` — deserialises via `from_dict()`;
  returns None if not found.
- `update_outcome(id, new_outcome, expected_status=None) -> Verdict` —
  CAS write. Raises `KeyError` if verdict not found; raises
  `OutcomeStatusMismatch` if `expected_status` is set and doesn't
  match current status; returns the updated `Verdict`. **CAS
  predicate** uses `IFNULL(json_extract(content, '$.outcome.status'),
  'pending')` so a verdict whose `content` blob omits the `outcome`
  field entirely is treated as `status='pending'` and accepts a CAS
  with `expected_status='pending'`. Pinned by
  `test_store_verdictstore.py::test_cas_with_expected_pending_against_missing_outcome_succeeds`.
- `query(filter: VerdictFilter) -> list[Verdict]` — maps
  `subject_service`→service, `subject_type`→verdict_type,
  `from_time`/`to_time`→created_after/created_before, `limit` to SQL;
  post-filters `producer_system`, `subject_agent`, `status`, `tags` in
  Python (not expressible as Store SQL predicates against the
  content-blob schema).
- `by_lineage(id, direction) -> list[Verdict]` — direction: `"up"`
  (ancestors), `"down"` (descendants), `"both"`; raises `ValueError`
  on unknown direction.
- `accuracy()` / `expire()` raise `NotImplementedError` — schema
  unification tracked in opensrm-jmy.20.

Core-specific methods (not on the VerdictStore ABC):

- `put_verdict(verdict)` → `str` — writes verdict + populates lineage
  index.
- `get_verdict(id)` → `dict | None`.
- `query_verdicts(*, service, verdict_type, created_after,
  created_before, limit=100)` → `list[dict]`.
- `ancestors_of(verdict_id, max_hops=None)` → `list[dict]` — ordered
  by hop distance.
- `descendants_of(verdict_id)` → `list[dict]`.
- `put_assessment` / `get_assessment` / `query_assessments`.
- `put_case(case)` → `str`; `get_case(id)` → `dict | None`;
  `query_cases(*, state, priority, service, limit=100)` →
  `list[dict]`.
- `acquire_lease(case_id, holder, expires_at)` → `bool` — atomic;
  acquirable if pending or lease expired.
- `release_lease(case_id)` → `bool`; `resolve_case(case_id,
  resolution_id)` → `bool`.
- `put_change_freeze` / `lift_change_freeze` / `get_active_freezes`.
- `put_heartbeat(component, instance_id, state=None)` — upsert by
  (component, instance_id);
  `get_heartbeats()` → raw rows;
  `get_heartbeats_with_health(degraded_threshold_seconds=30)` → rows
  with computed `health` and `age_seconds`.
- `get_stuck_action_requests(threshold_seconds=60)` → `list[dict]` —
  action_request verdicts older than cutoff with no case referencing
  them via `underlying_verdict`.
- `put_component_state` / `get_component_state` — JSON sub-fields
  (hysteresis_state, dedup_cache) auto-serialized; empty dicts
  preserved on roundtrip.
- `put_suppression(component, reason, suppressed_verdict_id, *,
  related_verdict_id=None, suppressed_at=None)` → `int` (row id);
  `query_suppressions(*, component=None, created_after=None,
  created_before=None, limit=100)` → `list[dict]`.
- `run_retention(retention=None)` → `dict[str, int]` — prune expired
  rows per policy. Defaults: verdicts/cases=365d,
  assessments/change_freezes/suppressions=90d, heartbeats=1d; raises
  `ValueError` if any window < 1.
- `table_exists(name)` → `bool`.
- `close()` — releases thread-local connection.

## Test suite

- `test_health.py` — async ASGI test: GET /health returns 200
  `{"status": "ok"}`.
- `test_api.py` — full HTTP API: TestHealth, TestPostVerdict,
  TestGetVerdicts (incl. time_range_filter_with_timezone_offset),
  TestLineage, TestOutcomeResolution, TestAssessments.
- `test_api_cases.py` — TestPriorityDerivation, TestPostCase,
  TestGetCases, TestCaseLease, TestCaseResolve, TestChangeFreezes.
- `test_api_heartbeats.py` — TestPostHeartbeat, TestGetHeartbeats,
  TestStuckActionRequests.
- `test_api_component_state.py` — TestPutComponentState (save,
  overwrite, invalid_body), TestGetComponentState (get_existing,
  get_nonexistent, empty_dict_roundtrip, roundtrip_preserves_state).
- `test_api_suppressions.py` — TestPostSuppression (create,
  create_without_related_verdict, missing_*→422), TestGetSuppressions
  (query_all, filter_by_component, filter_by_time_range, empty_result,
  suppression_contains_all_fields).
- `test_api_overrides.py` (opensrm-jmy.18) — 8 async tests:
  happy_path_returns_200_and_mutates_outcome,
  idempotent_reapply_returns_200, verdict_not_found_returns_404,
  decision_id_mismatch_returns_400, schema_failure_returns_422
  (missing corrected_action), conflict_with_existing_returns_409,
  terminal_status_returns_422 (confirmed verdict),
  override_persists_to_real_sqlite_store (B3 — real Store not
  MemoryStore; verifies fresh-read persistence + idempotent re-apply +
  CAS conflict). Uses `Store.put(Verdict)` + `Store.get(id)` ABC
  methods. `pre_redacted=True` means reviewer stored plaintext in
  `outcome.override.by`.
- `test_api_manifests.py` — TestGetManifests (list_all,
  expected_fields, slo_includes_judgment_type), TestGetManifest
  (get_existing, get_nonexistent → 404), TestManifestsReload (new /
  modified / deleted file detection, no_changes), TestCatalogueUnit
  (empty / nonexistent dir, invalid yaml skipped).
- `test_store.py` — schema, verdicts, lineage, cases, freezes,
  heartbeats, component state.
- `test_store_verdictstore.py` (opensrm-jmy.18 B0) —
  TestStoreIsVerdictStore, TestPutAndGet,
  TestUpdateOutcomeUnconditional, TestUpdateOutcomeCAS (success /
  mismatch / race), TestQuery (filter / limit), TestByLineage (up /
  down / both / unknown direction). All tests use real SQLite
  `Store(tmp_path)`.
- `test_retention.py` — TestVerdictRetention, TestAssessmentRetention,
  TestCaseRetention, TestChangeFreezeRetention, TestHeartbeatRetention,
  TestRekorAnchorsNeverPruned, TestRetentionGuards.
- `tests/smoke/test_imports.py` — walks every module under
  `nthlayer_core` via `pkgutil`; asserts every `__all__` symbol
  resolves via `getattr`.
- `tests/smoke/test_cli.py` — asserts the `nthlayer` console script is
  on PATH and `--help` exits 0 with non-empty stdout.

## Runtime dependencies

- `nthlayer-common>=0.1.8` (editable local, path
  `../nthlayer-common`) — shared utilities, verdict model.
- `starlette>=0.40` — ASGI web framework.
- `uvicorn>=0.30` — ASGI server.
- `httpx>=0.27` — HTTP client (also used in tests via
  `ASGITransport`).

Dev: `pytest>=8.2`, `pytest-asyncio>=0.23`
(`asyncio_mode = "auto"`), `httpx>=0.27`.

`pyproject.toml` is authoritative.
