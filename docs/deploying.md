# Deploying nthlayer-core

> Core-only deployment guide for evaluators. Workers and bench have their own surfaces.

## Tutorial: zero to first verdict

This tutorial takes you from a fresh machine to a running `nthlayer-core`
server that has accepted and returned its first verdict. Plan on under
fifteen minutes. Every command below has been executed end-to-end; the
output shown is what you should see.

### 1. Install uv

`nthlayer-core` is distributed on PyPI; this tutorial uses
[uv](https://docs.astral.sh/uv/).

Follow the upstream install instructions:
<https://docs.astral.sh/uv/getting-started/installation/>. Any recent
`uv` (≥ 0.5) will work.

### 2. Install nthlayer-core

```bash
uv tool install nthlayer-core
```

Verify the install:

```bash
nthlayer --version
```

```
nthlayer X.Y.Z
```

### 3. Choose a manifests directory

`nthlayer-core` serves a read-only catalogue of OpenSRM service
manifests from a directory you point it at. For this tutorial you have
two options.

**Option A — use the OpenSRM examples.** Clone the spec repo and
point the server at its `examples/` directory:

```bash
git clone https://github.com/rsionnach/opensrm
cd opensrm
```

You will use `opensrm/examples/` as your manifests directory in
step 4.

**Option B — start empty.** An empty directory is valid; the server
starts, accepts and returns verdicts, and `GET /manifests` simply
returns an empty list.

```bash
mkdir empty-dir
```

You will stay in the current directory and pass `./empty-dir` as your
manifests directory in step 4.

This tutorial uses Option A from here on.

### 4. Start the server

From inside the `opensrm/` directory:

```bash
NTHLAYER_MANIFESTS_DIR=./examples nthlayer serve
```

You should see the server come up on port 8000:

```
INFO:     Started server process [<pid>]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

The server is ready when you see `Application startup complete.`

> The server binds to `0.0.0.0` (all interfaces); `localhost:8000` reaches it.

Leave the server running and open a second terminal for the next
steps.

### 5. Health check

```bash
curl localhost:8000/health
```

```json
{"status":"ok"}
```

### 6. Post a verdict

A verdict is the unit of recorded outcome in NthLayer. `POST /verdicts`
requires `id`, `type`, and `created_at`. Adding `service` and `outcome`
makes the verdict useful to a worker downstream.

```bash
curl -X POST localhost:8000/verdicts \
  -H 'Content-Type: application/json' \
  -d '{
    "id": "verdict-001",
    "type": "verdict.created",
    "created_at": "2026-06-16T12:00:00Z",
    "service": "demo-service",
    "outcome": {"status": "pass"}
  }'
```

```json
{"id":"verdict-001"}
```

### 7. Fetch the verdict by id

```bash
curl localhost:8000/verdicts/verdict-001
```

```json
{"id":"verdict-001","type":"verdict.created","created_at":"2026-06-16T12:00:00Z","service":"demo-service","outcome":{"status":"pass"}}
```

### 8. List all verdicts

```bash
curl localhost:8000/verdicts
```

```json
[{"id":"verdict-001","type":"verdict.created","created_at":"2026-06-16T12:00:00Z","service":"demo-service","outcome":{"status":"pass"}}]
```

You now have a `nthlayer-core` server running on `localhost:8000`
that has stored, returned, and listed a verdict. From here you can
wire in a worker (see `nthlayer-workers`) or explore the rest of the
API surface via the OpenAPI spec at `GET /openapi.json`.

## Reference

### CLI

```
nthlayer serve [--host HOST] [--port PORT]   # defaults 0.0.0.0:8000
nthlayer --version                            # also -V
```

The CLI surface is intentionally minimal: one subcommand (`serve`) with
two flags (`--host`, `--port`) plus a top-level `--version`. The store
path and manifests directory are configured via environment variables
rather than flags by design — they are deployment-environment concerns
(filesystem layout, persistent volumes, secret-style paths) rather than
per-invocation choices, and keeping them off the CLI avoids encoding
host paths in process supervisors and shell history. See Environment
variables below.

### Environment variables

| Env var | Purpose | Default |
|---|---|---|
| `NTHLAYER_STORE_PATH` | SQLite database path | `nthlayer.db` (cwd-relative) |
| `NTHLAYER_MANIFESTS_DIR` | Directory of OpenSRM YAML manifests | unset (catalogue empty) |

**`NTHLAYER_STORE_PATH`** — when unset, the server opens `nthlayer.db`
in the process's current working directory and SQLite's WAL mode adds
`nthlayer.db-wal` and `nthlayer.db-shm` alongside it. Relative paths
resolve against the server's cwd at startup, not the cwd at install
time or the path of the `uv tool` shim, so a process supervisor that
chdirs before `exec` will land the database in that target directory.
The path requires read and write access; when unset or relative the
containing directory must also be writable so SQLite can create the
WAL and shared-memory sidecar files. A server started from a read-only
directory will appear to start cleanly and then fail on the first
write request (see Troubleshooting).

**`NTHLAYER_MANIFESTS_DIR`** — when unset, the catalogue initialises
empty and `GET /manifests` returns `[]`; verdict, case, and assessment
endpoints still function normally. Relative paths resolve against the
server's cwd at startup. The path requires read access on the
directory and on every `*.yaml` and `*.yml` file inside it. An empty
directory is a valid configuration — the server starts, the catalogue
is empty, and verdicts continue to be accepted and returned. A path
that does not exist or is not a directory is treated the same as
unset: the catalogue is empty and no error is raised at startup.

### Manifests directory layout

The catalogue loads every file matching `*.yaml` or `*.yml` at the top
level of `NTHLAYER_MANIFESTS_DIR`. The loader does not recurse into
subdirectories — files under nested folders are ignored. Convention is
one service per file, named after the service. Each file is parsed as
an OpenSRM reliability manifest; the service name comes from the
manifest's `name` field, not the filename.

Sample manifests live in the OpenSRM examples directory:
<https://github.com/rsionnach/opensrm/tree/main/examples>.

After editing files in the manifests directory, trigger a hot reload
with `POST /manifests/-/reload`. The server picks up new, changed, and
deleted files without a restart and returns the list of affected
service names.

For manifest schema and authoring guidance, see the manifest authoring
guide (tu04.3 — not yet published).

### Troubleshooting

## How-to: hardening for production

### Durable storage with Litestream
