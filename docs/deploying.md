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

Seven failure modes account for nearly every fresh-machine deployment
problem. The table summarises the user-visible symptom; the paragraphs
below name the underlying invariant and what to grep for in logs.

| # | Symptom | Cause | Fix |
|---|---|---|---|
| 1 | `nthlayer: command not found` after install | uv tool-shim dir not on `PATH` | `uv tool update-shell` (or add `~/.local/bin` to `PATH`) |
| 2 | `OSError: [Errno 48] Address already in use` | Port 8000 taken | `nthlayer serve --port 8001` or kill the prior process |
| 3 | `sqlite3.OperationalError: unable to open database file` | Cwd not writable, or `NTHLAYER_STORE_PATH` points at a missing dir | `NTHLAYER_STORE_PATH=/tmp/nthlayer.db` or chdir to a writable dir |
| 4 | `sqlite3.OperationalError: database is locked` (persistent, not transient) | Two `nthlayer serve` processes on the same DB | Kill the duplicate; one writer per store. WAL + 5s busy-timeout handles transient contention, not two writers |
| 5 | `GET /manifests` returns `[]` despite `NTHLAYER_MANIFESTS_DIR` set | Relative path resolved from wrong cwd, or dir is empty/missing | Use an absolute path; check server logs for the load summary |
| 6 | One manifest missing from `GET /manifests` even though the file exists | Invalid YAML or schema mismatch; catalogue skips bad manifests rather than crashing the server | Check server logs for the parse error; fix the YAML; `POST /manifests/-/reload` |
| 7 | Local `curl` works, remote `curl` times out | Cloud firewall / security group / host firewall blocks 8000 | Open the port, or bind `--host 127.0.0.1` and SSH-tunnel |

#### 1. Command not found

`uv tool install` writes a shim to `~/.local/bin` (Linux/macOS) and
prints a warning if that directory is not on `PATH`. If you missed the
warning, `uv tool update-shell` edits your shell rc to add it; opening
a new terminal then resolves `nthlayer`. Verify with `which nthlayer`.
On macOS with zsh, a stale `~/.zshrc` cache or a non-login shell can
also hide the shim — `exec zsh -l` forces a re-read.

#### 2. Port in use

The exact error is `OSError: [Errno 48] Address already in use` on
macOS and `[Errno 98]` on Linux. Confirm with `lsof -i :8000` (macOS)
or `ss -ltnp 'sport = :8000'` (Linux); the output names the process
holding the port. Either kill it or pass `--port 8001` (or any free
port) to `nthlayer serve`. Re-running a backgrounded server without
killing the prior process is the usual cause.

#### 3. Store path not writable

SQLite needs to create the database file and, in WAL mode, the
`-wal` and `-shm` sidecar files next to it. A relative
`NTHLAYER_STORE_PATH` (or the default `nthlayer.db`) resolves against
the server's cwd at startup; if that directory is read-only the open
fails on the first write request, not at startup. The fix is either
`NTHLAYER_STORE_PATH=/tmp/nthlayer.db` (or any writable absolute path)
or chdir to a writable directory before `exec`. Container images that
run as a non-root user need a writable volume mounted at the store
path.

#### 4. Database locked

The store opens with `PRAGMA journal_mode=WAL`,
`PRAGMA synchronous=NORMAL`, and `PRAGMA busy_timeout=5000`
(store.py:167–169). WAL allows concurrent readers alongside one
writer, and the 5s busy-timeout absorbs transient contention from a
single process's connection pool. A `database is locked` error that
persists past 5s indicates two writers on the same file — typically a
second `nthlayer serve` started against the same `NTHLAYER_STORE_PATH`.
Kill the duplicate; the single-writer invariant is load-bearing. A
stale `nthlayer.db-wal` file alone is not the cause and should not be
deleted while any process holds the database open.

#### 5. Manifests directory not loaded

On startup the catalogue logs `catalogue_loaded` with `count=` and
`directory=` (the resolved absolute path). If `count=0` and the
`directory=` path is not what you intended, the relative
`NTHLAYER_MANIFESTS_DIR` resolved against the wrong cwd. If the
log line is missing entirely, the path does not exist or is not a
directory — the catalogue silently treats this the same as unset
(catalogue.py:51) and `GET /manifests` returns `[]`. Use an absolute
path and confirm with `ls "$NTHLAYER_MANIFESTS_DIR"/*.y*ml`. Files
under nested subdirectories are also ignored.

#### 6. One manifest missing from the list

The catalogue wraps each file's parse in `try/except` and logs
`catalogue_load_failed` with `file=` and `error=` for the failure,
then continues with the rest (catalogue.py:121). The server stays
healthy and `GET /manifests` returns the manifests that did parse.
Grep the server log for `catalogue_load_failed` to find the offending
file and the parse error; fix the YAML and call
`POST /manifests/-/reload` to pick it up without a restart. A manifest
whose `name` field collides with another file's `name` will also
appear "missing" — the later file wins in load order.

#### 7. Remote curl times out

`nthlayer serve` binds to `0.0.0.0:8000` by default, so a local
`curl localhost:8000/health` returns `{"status":"ok"}` even when
remote clients time out. The timeout (as opposed to a connection
refused) is the tell: the SYN is being dropped, not rejected, which
means a firewall — cloud provider security group, host `ufw`/`iptables`,
or a corporate egress filter — is blocking 8000 inbound. Open the
port for trusted CIDRs, or keep the server on `--host 127.0.0.1` and
reach it through an SSH tunnel (`ssh -L 8000:localhost:8000 host`).
Binding to `0.0.0.0` on an internet-exposed host without authentication
is itself a hardening problem — see How-to: hardening for production.

#### Out of scope for this table

A few classes of failure are deliberately not covered here:

- **LLM provider keys, worker errors, judgment failures** — `nthlayer-core`
  has no LLM and no worker process; these surface only when workers
  are deployed. See `nthlayer-workers`.
- **TLS, reverse proxy, certificate renewal** — core speaks plain HTTP
  by design. See How-to: hardening for production below.
- **Authentication, authorization, rate limiting** — core has none in
  v1.5; the deployment is expected to terminate auth at a reverse
  proxy. See How-to: hardening for production below.

## How-to: hardening for production

### Durable storage with Litestream
