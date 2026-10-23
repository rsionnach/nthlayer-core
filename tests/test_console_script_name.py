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
    text = "\n".join(ln for ln in text.splitlines() if "before 4.0.0" not in ln)
    # A bare `nthlayer` followed by a space/EOL/backtick, not nthlayer-core,
    # nthlayer-common, NTHLAYER_*, or a path like /var/lib/nthlayer/.
    bare = re.findall(r"(?<![\w/.-])nthlayer(?=\s+(?:serve|--version)|`)", text)
    assert not bare, f"deploying.md still names the old script: {bare}"
