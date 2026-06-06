# nthlayer-core — agent-facing commands

Reliability-critical HTTP API server: verdict store, case management,
change freezes, heartbeats, component state, manifests, suppressions,
overrides. Python + Starlette + Uvicorn, stateful, no LLM.

## Stack

- Python ≥3.11, `uv`-managed.
- Runtime: Starlette + Uvicorn (ASGI).
- Tests: `pytest`, `pytest-asyncio` (`asyncio_mode = "auto"`),
  `httpx>=0.27` (via `ASGITransport`).
- Lint: `ruff`.
- Typecheck: **not configured** (no `mypy.ini`, no `pyrightconfig.json`,
  no `[tool.mypy]`/`[tool.pyright]` in `pyproject.toml`). TODO: wire
  one when the rest of the ecosystem standardises.

## Build / test / lint / run commands

```bash
uv sync                                # set up .venv
uv pip install -e .                    # editable install
uv run pytest -q                       # full suite
uv run pytest tests/test_<name>.py -v  # single file
uv run pytest -k "<expr>" -v           # single test by name
uv run ruff check src/ tests/          # lint
nthlayer serve --host 0.0.0.0 --port 8000   # start the HTTP server
nthlayer -V                                  # print version
```

## Runtime configuration

- `NTHLAYER_STORE_PATH` — path to SQLite db (default `nthlayer.db`).
- `NTHLAYER_MANIFESTS_DIR` — directory of OpenSRM manifest YAML files
  (optional; only the `/manifests*` endpoints depend on this).
- Test override: call `set_store(store)` / `set_catalogue(catalogue)`
  in test setup.

## CI / release

- **Push/PR gate** (`.github/workflows/ci.yml`, opensrm-5vuz): runs
  `uv run pytest tests/` (matrix py3.11 + py3.12) and
  `uv run ruff check src/ tests/` on every push and PR to `main`.
  `concurrency: cancel-in-progress` + `permissions: contents:read`.
  Closes the prior gap where pytest only fired at release time inside
  the wheel-smoke gate.
- `googleapis/release-please-action@v4`. Push to `main` inspects
  Conventional Commits and maintains a release PR that bumps
  `pyproject.toml` and appends `CHANGELOG.md`. Config:
  `release-please-config.json` + `.release-please-manifest.json`.
- Conventional Commit taxonomy: `feat`/`fix`/`perf`/`deps`/`refactor`/
  `docs` surface in the changelog; `chore`/`test`/`ci`/`build`/`style`
  hidden.
- Release PR merge → release-please cuts the tag → `release.yml` runs.
- **Docker smoke gate** between `twine check` and PyPI publish: a
  `python:3.11-slim` container mounts `dist/` and `tests/smoke/`
  read-only, installs the freshly-built wheel + pytest, runs the
  smoke suite. Failure blocks publish.
- **Known trigger issue:** `release.yml` fires on `release:
  published`. The `GITHUB_TOKEN`-cascade-block means
  release-please-created releases do not trigger `release.yml`
  automatically (tag `v1.1.0` did NOT auto-publish to PyPI).
  Remediation: pivot to `push: tags: ['v*']` trigger or configure
  release-please with a PAT. See bead `opensrm-pdoe`.
- **Dependabot** (`.github/dependabot.yml`): two ecosystems —
  `uv` (`pyproject.toml` + `uv.lock`) and `github-actions` — on a
  Monday-morning Europe/Dublin schedule. Sibling `nthlayer-*` packages
  and dev deps each grouped into a single weekly PR. Auto-merge
  policy in `.github/workflows/dependabot-automerge.yml`: external
  runtime patch and dev patch/minor auto-merge; sibling packages and
  any major bump require review.
