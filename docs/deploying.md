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

### Environment variables

### Manifests directory layout

### Troubleshooting

## How-to: hardening for production

### Durable storage with Litestream
