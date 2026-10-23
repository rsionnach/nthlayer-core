"""The console script is ``nthlayer-core``, never ``nthlayer``.

nthlayer-generate owns ``nthlayer``. Both packages registering it made the
installed one depend on install order, so core declares only ``nthlayer-core``
(symmetric naming: PyPI name = repo = script). Bead: opensrm-dww5.
"""
from __future__ import annotations

import pathlib
import re
import tomllib

from nthlayer_core.cli import build_parser

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Lines in docs/deploying.md containing this text are exempt from the guard: the
# note there ("The console script was `nthlayer` before 4.0.0 ...") names the
# old script on purpose. Keep in sync with that note.
RENAME_NOTE_MARKER = "before 4.0.0"


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


def test_deploying_doc_invokes_nthlayer_core_not_nthlayer() -> None:
    text = (REPO_ROOT / "docs" / "deploying.md").read_text(encoding="utf-8")
    # The rename note legitimately names the old script.
    text = "\n".join(ln for ln in text.splitlines() if RENAME_NOTE_MARKER not in ln)
    # Matches the bare word `nthlayer` (not preceded by a word char, `/`, `.` or
    # `-`) that is followed by whitespace then `serve` or `--version`, or
    # directly by a backtick, `:` or `-V`. So it ignores nthlayer-core,
    # nthlayer-common, NTHLAYER_*, and paths like /var/lib/nthlayer/.
    bare = re.findall(
        r"(?<![\w/.-])nthlayer(?=\s+(?:serve|--version)|`|:|-V)", text
    )
    assert not bare, f"deploying.md still names the old script: {bare}"
