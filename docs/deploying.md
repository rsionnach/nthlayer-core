# Deploying nthlayer-core

> Core-only deployment guide for evaluators. Workers and bench have their own surfaces.

## Tutorial: zero to first verdict

This tutorial takes you from a fresh machine to a running `nthlayer-core`
server that has accepted and returned its first verdict. Plan on five
minutes. Every command below has been executed end-to-end; the output
shown is what you should see.

### 1. Install uv

`nthlayer-core` is distributed on PyPI and easiest to install with
[uv](https://docs.astral.sh/uv/), Astral's Python package manager.

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
nthlayer 1.5.0
```

(The `nthlayer` CLI entry point ships inside the `nthlayer-core`
package; the version string above is the CLI's own, which lags the
package version on PyPI.)

### 3. Get a manifests directory

`nthlayer-core` serves a read-only catalogue of OpenSRM service
manifests from a directory you point it at. For this tutorial you have
two options.

**Option A — use the OpenSRM examples.** Clone the spec repo and
point the server at its `examples/` directory:

```bash
git clone https://github.com/rsionnach/opensrm
```

You will use `opensrm/examples/` as your manifests directory in
step 4.

**Option B — start empty.** An empty directory is valid; the server
starts, accepts and returns verdicts, and `GET /manifests` simply
returns an empty list.

```bash
mkdir empty-dir
```

Pick whichever fits your evaluation. The rest of this tutorial uses
Option A.

### 4. Start the server

From inside the cloned `opensrm/` directory:

```bash
NTHLAYER_MANIFESTS_DIR=./examples nthlayer serve
```

You should see the server come up on port 8000:

```
INFO:     Started server process [99793]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

> The server binds to `0.0.0.0` by default (all interfaces); the curl
> commands below use `localhost:8000`, which reaches it.

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

A verdict is the unit of recorded outcome in NthLayer. The minimum
fields `POST /verdicts` requires are `id`, `type`, and `created_at`;
adding `service` and `outcome` makes the verdict useful to a worker
later.

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

The HTTP status is `201 Created`.

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

The response is a JSON array of verdict records:

```json
[{"id":"verdict-001","type":"verdict.created","created_at":"2026-06-16T12:00:00Z","service":"demo-service","outcome":{"status":"pass"}}]
```

You now have a `nthlayer-core` server running on `localhost:8000`
that has stored, returned, and listed a verdict. From here you can
wire in a worker (see `nthlayer-workers`) or explore the rest of the
API surface in the Reference section below.

## Reference

### CLI

### Environment variables

### Manifests directory layout

### Troubleshooting

## How-to: hardening for production

### Durable storage with Litestream
