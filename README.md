# nthlayer-core

**Tier 1 of the [NthLayer](https://github.com/rsionnach/nthlayer) ecosystem.** Reliability-critical HTTP API server: verdict store, case management, change-freezes, manifest catalogue, heartbeats, component state.

```bash
pip install nthlayer-core
nthlayer serve --host 0.0.0.0 --port 8000
```

## What it is

`nthlayer-core` is the single source of truth for the NthLayer runtime. It owns the SQLite store, exposes an HTTP API, and is the only component that touches the database. Tier 2 workers ([`nthlayer-workers`](https://github.com/rsionnach/nthlayer-workers)) and the Tier 3 operator TUI ([`nthlayer-bench`](https://github.com/rsionnach/nthlayer-bench)) talk to core exclusively over HTTP — never directly to SQLite.

Core availability = product availability. Worker failure is degradation; core failure is an outage.

- **Stateful, no LLM.** Pure transport. Decisions live elsewhere.
- **Python · Starlette · uvicorn · SQLite (WAL).**
- **Apache 2.0** licensed.

## Why a single API server

The v1.5 architecture moved away from per-component SQLite databases for two reasons:

1. **Lineage and case state need a single consistent view.** A verdict written by the measure module must be linkable from a case opened by the bench TUI without cross-DB joins.
2. **Workers should be replaceable.** Any worker can crash, restart, or be re-deployed without touching shared state. Core holds the state; workers hold cursors.

## HTTP API surface

Core exposes the following resources. All responses are JSON. Verdicts are immutable — the `outcome_resolution` pattern creates a NEW verdict with `parent_ids=[original_id]` rather than mutating the original.

| Resource | Endpoints |
|---|---|
| Verdicts | `POST /verdicts`, `GET /verdicts`, `GET /verdicts/{id}`, `GET /verdicts/{id}/ancestors`, `GET /verdicts/{id}/descendants`, `POST /verdicts/{id}/outcome` |
| Assessments | `POST /assessments`, `GET /assessments` |
| Cases | `POST /cases`, `GET /cases`, `GET /cases/{id}`, `PUT /cases/{id}/lease`, `DELETE /cases/{id}/lease`, `PUT /cases/{id}/resolve` |
| Change freezes | `POST /change-freezes`, `GET /change-freezes`, `PUT /change-freezes/{name}/lift` |
| Heartbeats | `POST /heartbeats`, `GET /heartbeats` |
| Component state | `PUT /component-state/{component}`, `GET /component-state/{component}` |
| Suppressions | `POST /suppressions`, `GET /suppressions` |
| Manifests | `GET /manifests`, `GET /manifests/{service}`, `POST /manifests/-/reload` |
| Monitoring | `GET /monitoring/stuck-action-requests` |
| Health | `GET /health` |

### Priority derivation

Cases without an explicit `priority` are derived from `blast_radius` + `has_active_incident`:

| blast_radius | active_incident | priority |
|---|---|---|
| `production` | true | P0 |
| `production` | false | P1 |
| `staging` | true | P1 |
| `staging` | false | P2 |
| dev / ephemeral / unknown | any | P3 |

## Configuration

| Env var | Purpose | Default |
|---|---|---|
| `NTHLAYER_STORE_PATH` | SQLite database path | `nthlayer.db` |
| `NTHLAYER_MANIFESTS_DIR` | Directory of OpenSRM YAML manifests | unset (catalogue empty) |

For step-by-step deployment, troubleshooting, and Litestream hardening, see [`docs/deploying.md`](docs/deploying.md).

## Schema (v1.5.0)

10 tables, string IDs, JSON TEXT content:

- `verdicts` — immutable records with lineage
- `assessments` — non-decision component outputs
- `cases` — bench domain model with lease management
- `change_freezes` — RBAC §7 freeze documents
- `heartbeats` — component liveness (upsert per instance)
- `component_state` — persistent worker state across restarts
- `suppressions` — suppression audit trail
- `rekor_anchors` — empty in v1.5; populated in v2 (forward-compat)
- `lineage` — pre-computed transitive closure for fast ancestor/descendant queries
- `schema_meta` — schema version

WAL mode + `PRAGMA synchronous=NORMAL` + `busy_timeout=5000`. Thread-local connection pool. `BEGIN IMMEDIATE` for all writes. Retention is policy-driven (verdicts only pruned when old AND no younger descendants AND no surviving case references); `rekor_anchors` are never pruned.

## CLI

```bash
nthlayer serve [--host 0.0.0.0] [--port 8000]   # start the HTTP server
nthlayer -V                                       # print version
```

## NthLayer ecosystem

`nthlayer-core` is one of seven repos. Each component works alone; composition happens through OpenSRM manifests + the core HTTP API.

| Repo | Tier | Role |
|---|---|---|
| [`opensrm`](https://github.com/rsionnach/opensrm) | — | The OpenSRM specification |
| [`nthlayer-common`](https://github.com/rsionnach/nthlayer-common) | — | Shared library (verdicts, manifests, LLM wrapper, CoreAPIClient) |
| [`nthlayer-generate`](https://github.com/rsionnach/nthlayer-generate) | — | Build-time compiler: specs → Grafana, Prometheus, SLOs, Backstage |
| [`nthlayer-core`](https://github.com/rsionnach/nthlayer-core) | **1** | This repo — HTTP API + state |
| [`nthlayer-workers`](https://github.com/rsionnach/nthlayer-workers) | **2** | observe / measure / correlate / respond / learn worker modules |
| [`nthlayer-bench`](https://github.com/rsionnach/nthlayer-bench) | **3** | Operator TUI |
| [`nthlayer`](https://github.com/rsionnach/nthlayer) | — | Project front door + meta-package (`pip install nthlayer`) |

## Licence

Apache 2.0
