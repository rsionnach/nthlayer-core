"""The console script is ``nthlayer-core``, never ``nthlayer``.

nthlayer-generate owns ``nthlayer``. Both packages registering it made the
installed one depend on install order, so core declares only ``nthlayer-core``
(symmetric naming: PyPI name = repo = script). Bead: opensrm-dww5.
"""
from __future__ import annotations

import pathlib
import re
import tomllib

import pytest

from nthlayer_core.cli import build_parser

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Lines containing any of these are exempt from the guard: they name the old
# script on purpose (the rename note and the 3.x upgrade note). Keep in sync
# with those notes in README.md and docs/deploying.md.
RENAME_NOTE_MARKERS = ("before 4.0.0", "Upgrading from 3.x")

# Legitimate mentions of the bare name that are NOT the console script: the
# `nthlayer` meta-package on PyPI. Matched by line substring, not by weakening
# the regex.
ALLOWED_LINE_SUBSTRINGS = ("front door + meta-package",)

# The bare word `nthlayer` (not preceded by a word char, `/`, `.` or `-`) in a
# stale-invocation position: followed by a subcommand/flag (`serve`,
# `--version`, `-V`, `--help`), a version number (`nthlayer 1.7.0` output), a
# backtick, `:`, `→`, or end of line. So it ignores nthlayer-core,
# nthlayer-generate, nthlayer_core, NTHLAYER_*, /var/lib/nthlayer/, nthlayer.io.
STALE_SCRIPT_RE = re.compile(
    r"(?<![\w/.-])nthlayer"
    r"(?=\s+(?:serve\b|--version|-V\b|--help|\d+\.\d+)|\s*$|`|:|\s*→)",
    re.MULTILINE,
)


def _scripts() -> dict[str, str]:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["scripts"]


def test_pyproject_declares_nthlayer_core_script() -> None:
    assert _scripts().get("nthlayer-core") == "nthlayer_core.cli:main"


def test_pyproject_does_not_declare_nthlayer_script() -> None:
    assert "nthlayer" not in _scripts(), (
        "core must not register `nthlayer`; nthlayer-generate owns it"
    )


def test_parser_prog_is_nthlayer_core() -> None:
    assert build_parser().prog == "nthlayer-core"


@pytest.mark.parametrize(
    "text",
    [
        "nthlayer serve --port 8000",
        "nthlayer --version",
        "nthlayer -V",
        "nthlayer --help",
        "nthlayer 1.7.0",
        "run nthlayer",
        "see nthlayer:",
        "the `nthlayer` script",
        "nthlayer \u2192 nthlayer_core.cli:main",
    ],
)
def test_stale_script_regex_matches(text: str) -> None:
    assert STALE_SCRIPT_RE.search(text), text


@pytest.mark.parametrize(
    "text",
    [
        "nthlayer-core serve",
        "nthlayer-generate build",
        "import nthlayer_core",
        "nthlayer-common>=1.5.0",
        "NTHLAYER_STORE_PATH=/x",
        "/var/lib/nthlayer/data",
        "https://nthlayer.io/docs",
        "nthlayer.db-wal",
        "pip install nthlayer-core",
        "nthlayer-core --version",
    ],
)
def test_stale_script_regex_ignores(text: str) -> None:
    assert not STALE_SCRIPT_RE.search(text), text


def _doc_paths() -> list[pathlib.Path]:
    return [REPO_ROOT / "README.md", *sorted((REPO_ROOT / "docs").glob("*.md"))]


def test_docs_exist_so_guard_is_not_vacuous() -> None:
    names = {p.name for p in _doc_paths()}
    assert {"README.md", "deploying.md", "architecture.md"} <= names


@pytest.mark.parametrize("path", _doc_paths(), ids=lambda p: p.name)
def test_docs_invoke_nthlayer_core_not_nthlayer(path: pathlib.Path) -> None:
    lines = [
        ln
        for ln in path.read_text(encoding="utf-8").splitlines()
        if not any(m in ln for m in RENAME_NOTE_MARKERS)
        and not any(a in ln for a in ALLOWED_LINE_SUBSTRINGS)
    ]
    bare = STALE_SCRIPT_RE.findall("\n".join(lines))
    assert not bare, f"{path.name} still names the old script: {bare}"
