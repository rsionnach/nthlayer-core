# Changelog — nthlayer-core (Tier 1)

This file narrates the build sequence behind the initial state of this repository,
in prose. The repository was created from working code that had been developed
across the ecosystem under the v1.5 epic plan; we did not reconstruct phase-by-phase
git history because that history did not exist as commits at the time the work
was being done. This narrative is the honest substitute.

## v1.5.0 — 2026-05-03

First lockstep release with the rest of the v1.5 ecosystem. Major change:

**CloudEvents envelope auto-detect on POST /verdicts and /assessments**
(opensrm-saun.1.2). Both endpoints now detect a CloudEvents v1.0 envelope
by the presence of a top-level `specversion` field and unwrap the inner
`data` payload before validation. Raw record submissions continue to work
(back-compat for tests and pre-saun.1.2 callers). v2 will deprecate the
raw path and require the envelope. New error contract:
- `400 envelope_invalid` — envelope-level error (missing required
  CloudEvents attribute, wrong specversion, non-dict data).
  `envelope_version: null` so workers debugging transport issues can
  distinguish from domain errors.
- `422 verdict_invalid` / `422 assessment_invalid` — envelope unwrapped,
  inner record fails validation. `envelope_version: "1.0"` so the
  caller knows the envelope side was OK.

The bead also surfaced and resolved the cross-tier wire-format alignment
issue: workers' `to_dict(Verdict)` was emitting `verdict_type`/`timestamp`
while core's API expected `type`/`created_at`. Fix landed in
`nthlayer-common`; core's contract now matches what wrapped envelopes
deliver.

7 new tests in `tests/test_api.py::TestPostVerdictEnvelope` cover the
auto-detect contract: envelope round-trip, missing-attr 400, wrong
specversion 400, non-dict data 400, inner-record 422 with
`envelope_version: "1.0"`, and the raw-fallback path (no envelope, status
quo behaviour).

## Provenance

`nthlayer-core` is the Tier 1 (reliability-critical) process in the three-tier
NthLayer architecture decided 2026-04-21
([`docs/superpowers/specs/2026-04-21-spec-revision-summary.md`][spec-revision] in the
`opensrm` repo). It is one of the three new repositories created as part of the
six-repo consolidation
([`docs/superpowers/specs/2026-04-21-repo-consolidation-recommendation.md`][consol]).

The package name on PyPI is `nthlayer` — `pip install nthlayer` gives you the core
process (server, verdict store, case management, manifest catalogue, change-freeze
state, heartbeat tracking, retention). Workers and bench depend on this service
via HTTP API only.

## Build sequence (epic-level)

The contents of this initial commit reflect work from the **v1.5 epic plan**
([`docs/superpowers/plans/2026-04-21-nthlayer-v1.5-epic-tree.md`][v15-plan]),
phases:

- **Phase 0 — pre-implementation decisions.** Auth flow, default policy posture,
  team-filtering for case routing, Regorus-vs-regopy fallback, v1.5 boundary
  decisions ratified. Decision document:
  `docs/superpowers/plans/2026-04-21-phase-0-decisions.md`.
- **Phase 1A — primitives.** Most of this work landed in `nthlayer-common`
  (CoreAPIClient, CloudEvents helpers, unified Config, v1.5 verdict types,
  error hierarchy). `nthlayer-core`'s own contribution at this phase was the
  HTTP API skeleton.
- **Phase 1B — core completeness.** Unified store schema (verdicts, assessments,
  cases, change-freezes, heartbeats, component-state, manifests, retention),
  HTTP API surface for all of them, lineage walking, retention runner,
  server lifecycle. This is the bulk of the code shipped here.
- **Phase 2 — manifest catalogue.** `apiVersion: opensrm.nthlayer.io/v2` parser,
  v1 backward-compatibility, manifest catalogue endpoints
  (`GET /manifests`, `GET /manifests/{service}`), suppression audit hooks,
  component-state persistence for worker modules.

## What is in this initial commit

**Source layout** (`src/nthlayer/`):

- `server.py` — Starlette ASGI server. Routes for verdicts, assessments,
  cases (with lease acquisition for operator handling), change-freezes,
  heartbeats, manifests, component-state, monitoring (`/monitoring/stuck-action-requests`).
  Health endpoint at `GET /health`.
- `store.py` — `StorePool` with per-table SQLite stores (WAL mode,
  thread-local connections). Atomic conditional UPDATE for verdict outcome
  resolution. Retention runner. Idempotent inserts where appropriate.
- `catalogue.py` — Manifest catalogue. Loads OpenSRM manifests from a configured
  directory, normalises into a single `Manifest` shape, exposes them via the
  manifest endpoints. Used by every worker module to look up service tier,
  SLOs, dependencies, ownership.
- `cli.py` — `nthlayer serve` entry point. Parses config, opens stores, mounts
  the ASGI app, runs uvicorn.
- `__init__.py` — Package marker; declares the public re-export surface.

**Tests** (`tests/`):

- `test_health.py`, `test_api.py`, `test_api_manifests.py`,
  `test_api_cases.py`, `test_api_heartbeats.py`,
  `test_api_component_state.py`, `test_api_suppressions.py` — endpoint
  contract tests (Starlette TestClient).
- `test_store.py`, `test_retention.py` — storage layer tests.

**Configuration:**

- `pyproject.toml` — depends on `nthlayer-common>=0.1.8`, `starlette>=0.40`,
  `uvicorn>=0.30`, `httpx>=0.27`. Console script: `nthlayer = "nthlayer.cli:main"`.
- `uv.lock` — committed for reproducible dev installs.

## Things deliberately NOT yet in this repo

- **Authorise / executor modules.** Per the v1.5 boundary decision, respond
  retains execution ownership in v1.5; `nthlayer-core` will gain authorise +
  executor modules in v2 (Regorus + Biscuit policy evaluation, IPLD-CID-anchored
  capability tokens). Tracked in
  `docs/superpowers/plans/2026-04-21-nthlayer-v1.5-epic-tree.md` v2-deferred section.
- **IPLD CIDv1 verdict identity.** v1.5 uses string IDs (`vrd-...`); v2 migrates
  to canonical-CBOR-encoded CIDs.
- **Rekor anchoring.** v2 daily Merkle-root publication for tamper evidence.
- **Bytewax dataflow for correlation.** v1.5 uses asyncio session windows in the
  workers process; v2 may migrate the high-throughput path to Bytewax.

## How this repo evolves

`nthlayer-core` is API-stability-critical from v1.5 onwards: every other tier
(workers, bench) depends on its HTTP API surface. Strict semver applies. The
HTTP API is documented in OpenAPI form (planned: `docs/openapi.yaml`).

Future work attaches as normal commits with conventional commit messages.
The next major work item is the v1.5 → v2 migration, which is a separate
epic and will be developed on a feature branch.

[spec-revision]: ../opensrm/docs/superpowers/specs/2026-04-21-spec-revision-summary.md
[consol]: ../opensrm/docs/superpowers/specs/2026-04-21-repo-consolidation-recommendation.md
[v15-plan]: ../opensrm/docs/superpowers/plans/2026-04-21-nthlayer-v1.5-epic-tree.md
