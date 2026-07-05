# Changelog — nthlayer-core (Tier 1)

This file narrates the build sequence behind the initial state of this repository,
in prose. The repository was created from working code that had been developed
across the ecosystem under the v1.5 epic plan; we did not reconstruct phase-by-phase
git history because that history did not exist as commits at the time the work
was being done. This narrative is the honest substitute.

## [1.8.1](https://github.com/rsionnach/nthlayer-core/compare/v1.8.0...v1.8.1) (2026-07-05)


### Documentation

* add contributing guide (opensrm-tu04.4) ([6b43a51](https://github.com/rsionnach/nthlayer-core/commit/6b43a51aa827cf3292cb535f9119986fd0df0794))

## [1.8.0](https://github.com/rsionnach/nthlayer-core/compare/v1.7.0...v1.8.0) (2026-06-19)


### Features

* **tu04.2.1:** drift gate for deploying.md against source ([3d9e3eb](https://github.com/rsionnach/nthlayer-core/commit/3d9e3eb469129348446e05d704fa63d4e4e350d1))


### Documentation

* **tu04.2:** drop X.Y.Z placeholder; nthlayer --version now reports correctly ([2752532](https://github.com/rsionnach/nthlayer-core/commit/27525324ccb8a2c48e27828a0e40c92fce464cc0))

## [1.7.0](https://github.com/rsionnach/nthlayer-core/compare/v1.6.0...v1.7.0) (2026-06-17)


### Features

* **api:** add POST /verdicts/{id}/override handler · opensrm-jmy.18 ([367bc3d](https://github.com/rsionnach/nthlayer-core/commit/367bc3d73ebcf11aebc118ccb020147b68726a8b))
* **store:** implement VerdictStore ABC on Store · opensrm-jmy.18 ([1638d67](https://github.com/rsionnach/nthlayer-core/commit/1638d673ac852427a843007d15ee65ac46bf00ce))
* **tu04.1.1:** OpenAPI 3.1 framework + /health worked example ([8002a4e](https://github.com/rsionnach/nthlayer-core/commit/8002a4e28820f6adb2629100be5c78bbea095fa1))
* **tu04.1.1:** scripts/regen_openapi.py + initial openapi.json ([850a6e1](https://github.com/rsionnach/nthlayer-core/commit/850a6e1a33b161170487fc4a8073d8e0fc20f158))
* **tu04.1.1:** serve OpenAPI spec at GET /openapi.json ([bbe6418](https://github.com/rsionnach/nthlayer-core/commit/bbe641870c66e88e2399ca72396eb280e57d9bc5))
* **tu04.1.2.2:** cap GET limit at 1000 to bound DoS surface ([83dacf8](https://github.com/rsionnach/nthlayer-core/commit/83dacf832cc2229d83d757e67cc105dfa1111bee))
* **tu04.1.2:** document /verdicts* path group (7 routes) ([f966fa6](https://github.com/rsionnach/nthlayer-core/commit/f966fa6725b2a22004667929389efaf52539ff03))
* **tu04.1.3:** document /assessments and /cases path groups (8 routes) ([d60505a](https://github.com/rsionnach/nthlayer-core/commit/d60505a477f39050b607449fa262b0ee1940e337))
* **tu04.1.4:** document remainder path groups (13 routes) + close parity gap ([ec8f049](https://github.com/rsionnach/nthlayer-core/commit/ec8f0494c5ef6ab8e849e7aa39080dee0cd54870))


### Bug Fixes

* **ci:** add ruff to dev deps (5vuz miss) ([145ca59](https://github.com/rsionnach/nthlayer-core/commit/145ca59cb4563eb7d5dea67fe8d156220a1a9c2e))
* **ci:** add sibling-checkout pattern for nthlayer-common (5vuz miss) ([4f85c76](https://github.com/rsionnach/nthlayer-core/commit/4f85c7692d0a34b96b7ddedcddee654a61a68af2))
* **ci:** add tag-push + workflow_dispatch triggers to release.yml ([eb1b85a](https://github.com/rsionnach/nthlayer-core/commit/eb1b85af5b067dbc60afd9ec173bbc9ad4d1d859))


### Code Refactoring

* read version from importlib.metadata, not source literal ([9337df2](https://github.com/rsionnach/nthlayer-core/commit/9337df221d71abd0fb18de1c1e2d5896a8b58b84))


### Documentation

* **CLAUDE.md:** catch up auto-memory drift from prior bead sessions ([6945bac](https://github.com/rsionnach/nthlayer-core/commit/6945bace66b617fd21162dfe97bf501e52942cc3))
* **CLAUDE.md:** document release-please + smoke gate + Dependabot ([0f7433f](https://github.com/rsionnach/nthlayer-core/commit/0f7433f0a9de568932a8b25f1c2edd1c9e54bbf2))
* link to ecosystem testing conventions (opensrm-2wkc) ([271ddb1](https://github.com/rsionnach/nthlayer-core/commit/271ddb1a2cf3edaf73da0befe264839b9a1debb5))
* thin CLAUDE.md; move detail to AGENTS.md + docs/ ([f7fb4ca](https://github.com/rsionnach/nthlayer-core/commit/f7fb4cad547fc94529379a525b1983a44434adac))
* **tu04.1.2.1:** hard rule [#4](https://github.com/rsionnach/nthlayer-core/issues/4) record_invalid → verdict_invalid ([d2392d1](https://github.com/rsionnach/nthlayer-core/commit/d2392d19da66c66f7f9f0314aa7a4bbf4511d1a9))
* **tu04.1.4.1:** document threshold=0 semantics on /heartbeats and /monitoring ([11570c0](https://github.com/rsionnach/nthlayer-core/commit/11570c00f36dac556619dc79c217d34e726a85ad))
* **tu04.1.4.2:** clarify change-freeze name uniqueness scope ([146da2a](https://github.com/rsionnach/nthlayer-core/commit/146da2ad8321684c068d6c78df8d3e19f1003c29))
* **tu04.1.5:** OpenAPI pointer in CLAUDE.md + regen discipline in AGENTS.md ([d44dd6f](https://github.com/rsionnach/nthlayer-core/commit/d44dd6f639fbd6ac42d25efa2e67033e626fd3eb))
* **tu04.2:** deploying.md How-to — Litestream sidecar (documented, not validated) ([7d0dfbc](https://github.com/rsionnach/nthlayer-core/commit/7d0dfbc9c9c8323bb5dc81ebc545708fae245797))
* **tu04.2:** deploying.md Reference — 7-row troubleshooting table + expansions ([1a4b8fa](https://github.com/rsionnach/nthlayer-core/commit/1a4b8fab54149a19689c32a3fa5ffb24060ae1ca))
* **tu04.2:** deploying.md Reference — CLI + env vars + manifests directory ([fcfdf6a](https://github.com/rsionnach/nthlayer-core/commit/fcfdf6a96071cadb8eea4d19a48b262f104252e6))
* **tu04.2:** deploying.md skeleton + Tutorial section (validated in tmpdir) ([8c7e666](https://github.com/rsionnach/nthlayer-core/commit/8c7e666f530108332456010dcc8604ae2f510a09))
* **tu04.2:** README Configuration section links to canonical deploying.md ([61e5499](https://github.com/rsionnach/nthlayer-core/commit/61e5499820e27f05c2b2e26e7c0083ca9a59ea2c))
* **tu04.2:** troubleshooting prose-review fixes (cross-platform errno, durable path, log handle) ([b7cedb2](https://github.com/rsionnach/nthlayer-core/commit/b7cedb29d67012b4848b4ed3d24fdf06f488e369))
* **tu04.2:** Tutorial prose-review fixes (version placeholder, cd handoff, voice tightening) ([e2df256](https://github.com/rsionnach/nthlayer-core/commit/e2df256c8fcbbd69789232effd13e38792b235bb))
* **tu04.2:** Tutorial spec-review fixes — host-consistency note + 409 paragraph cut ([277d286](https://github.com/rsionnach/nthlayer-core/commit/277d286d53566417eb53d8f7059a7e3a609b2323))

## [1.6.0](https://github.com/rsionnach/nthlayer-core/compare/v1.5.0...v1.6.0) (2026-05-10)


### Features

* **server:** CloudEvents envelope auto-detect on POST /verdicts + /assessments ([9bace14](https://github.com/rsionnach/nthlayer-core/commit/9bace144f6ba292f90bdc7ef9186b6de73e506a1))


### Bug Fixes

* **core:** suppress raw exception strings in 500 responses ([76466fc](https://github.com/rsionnach/nthlayer-core/commit/76466fc514842c175fd09c1860e56e6fb1993ecf))


### Code Refactoring

* align package name + import path symmetrically (nthlayer-core) ([4cc19fc](https://github.com/rsionnach/nthlayer-core/commit/4cc19fc6353ff3c3512e7350264e0446243ee240))


### Documentation

* add README — Tier 1 HTTP API server overview ([29c351c](https://github.com/rsionnach/nthlayer-core/commit/29c351cc085f45506f8dcef7ffa1dc30a047386a))
* **CLAUDE.md:** document _store_error_response opacity helper ([32425e4](https://github.com/rsionnach/nthlayer-core/commit/32425e4997b6f32431266c220a6fee7f71cc5a0e))
* **comments:** inline pointer to envelope auto-detect decision ([ecfe749](https://github.com/rsionnach/nthlayer-core/commit/ecfe749ed57f48e8a3e94d37171c2503b05465e4))

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
