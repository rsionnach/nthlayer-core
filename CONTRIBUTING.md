# Contributing to nthlayer-core

Thank you for considering contributing to **nthlayer-core** — the
reliability-critical Tier 1 HTTP API server (Starlette + Uvicorn): verdict
store, case management, change freezes, heartbeats, component state,
manifests, suppressions, and overrides. We're in active v1.5 development and
welcome feedback from the SRE/DevOps community.

Core is the **single writer** to the SQLite store; workers and bench talk to
it over HTTP only. Treat the store invariant and the HTTP contract as
load-bearing.

## Ways to Contribute

- **Report bugs / request features** — [open an issue](https://github.com/rsionnach/nthlayer-core/issues).
- **Discuss** — [GitHub Discussions](https://github.com/rsionnach/nthlayer/discussions) for the wider ecosystem.
- **Code & docs** — pull requests welcome (see below).

## Development Setup

```bash
# Install uv (https://docs.astral.sh/uv/)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone alongside nthlayer-common (core depends on it via a sibling path)
git clone https://github.com/rsionnach/nthlayer-common.git
git clone https://github.com/rsionnach/nthlayer-core.git
cd nthlayer-core
uv sync --extra dev                  # creates .venv with test/lint tools

# Run the API locally (optional; Ctrl-C to stop, not needed before tests)
uv run nthlayer serve --host 0.0.0.0 --port 8000

# Run the test suite
uv run pytest -q                     # full suite
uv run pytest tests/test_<name>.py -v  # a single file
uv run pytest -k "<expr>" -v         # by name

# Lint
uv run ruff check src/ tests/
```

> **Sibling dependency & Python.** `pyproject.toml` declares
> `nthlayer-common = { path = "../nthlayer-common", editable = true }`, so
> `nthlayer-common` must sit next to this repo on disk or `uv sync` fails to
> resolve it. Requires Python 3.11+ (`uv` will provision it via
> `uv python install` if needed).

A clean clone to a green `uv run pytest -q` should take well under five
minutes. CI runs pytest + ruff on a py3.11/3.12 matrix for every push and
PR to `main`.

## Pull Request Process

1. Fork the repository and create a feature branch off `main`
   (`git checkout -b feat/your-change`).
2. Make your change with tests.
3. **If you edited the OpenAPI surface** (`src/nthlayer_core/_openapi/paths_*.py`
   or shared schemas in `openapi_spec.py`), regenerate the checked-in artefact
   before committing:
   ```bash
   uv run python scripts/regen_openapi.py
   ```
   CI test `test_checked_in_artefact_matches` gates this.
4. Ensure tests pass: `uv run pytest -q`.
5. Ensure lint passes: `uv run ruff check src/ tests/`.
6. Commit using Conventional Commits (see below).
7. Push to your fork and open a PR against `main`.

Commits land on `main`; `release-please` maintains the release PR. A
Docker-based smoke gate (`tests/smoke/`) runs between `twine check` and PyPI
publish.

## Development Guidelines

### Code Style

- Python 3.11+, type hints encouraged.
- Ruff for linting: `uv run ruff check src/ tests/`.
- Preserve the single-writer invariant: core is the only process that opens
  the SQLite store. Workers/bench integrate via the HTTP API.

### Commit Messages

```
<type>: <description>

<optional body>
```

`feat` / `fix` / `perf` / `deps` / `refactor` / `docs` surface in the
changelog; `chore` / `test` / `ci` / `build` / `style` are hidden.

### Testing

- Add tests for new behaviour.
- Run a single file with `-v` while iterating; run the full `-q` suite before
  opening a PR.

## Finding Something to Work On

Browse [open issues](https://github.com/rsionnach/nthlayer-core/issues) and
look for `good-first-issue` / `help-wanted` labels. Maintainers track detailed
work in **Beads**, a Dolt-backed board in the `opensrm` repo
(`cd ../opensrm && bd ready --json`) — you don't need it to contribute.

## Code of Conduct

Be respectful and constructive — we're all here to build better reliability
tooling.

## Security

Please report security vulnerabilities privately — use GitHub's "Report a
vulnerability" (the repo's **Security** tab) rather than a public issue.

## Questions?

- [GitHub Issues](https://github.com/rsionnach/nthlayer-core/issues) — bugs and features.
- [GitHub Discussions](https://github.com/rsionnach/nthlayer/discussions) — general questions.

## License

By contributing, you agree that your contributions will be licensed under
this repository's license (see `LICENSE`).

---

**Thank you for helping make NthLayer better!**
