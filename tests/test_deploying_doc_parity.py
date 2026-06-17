"""Drift gate for docs/deploying.md against source.

Three parity checks pinning the doc's Reference section to reality:

1. Env-var table rows match ``os.environ.get(...)`` calls in server.py.
2. CLI subsection matches argparse surface in cli.py.
3. Manifests directory layout claim mentions both extensions catalogue.py loads.

Pattern follows ``test_openapi.py::test_route_parity`` (tu04.1). When source
adds, renames, or removes a documented surface, the corresponding test fails
with a diff naming the missing/extra symbols — the doc must be updated to
match before merge.

Bead: opensrm-tu04.2.1.
"""
from __future__ import annotations

import argparse
import pathlib
import re

from nthlayer_core.cli import build_parser

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEPLOYING_DOC = REPO_ROOT / "docs" / "deploying.md"
SERVER_SRC = REPO_ROOT / "src" / "nthlayer_core" / "server.py"
CATALOGUE_SRC = REPO_ROOT / "src" / "nthlayer_core" / "catalogue.py"

# argparse adds --help automatically; the doc deliberately doesn't list it
# (universal flag, not nthlayer-specific). Strip it from the source-side set.
AUTO_FLAGS = frozenset({"--help"})


def _doc_text() -> str:
    return DEPLOYING_DOC.read_text(encoding="utf-8")


def _doc_section(heading: str) -> str:
    """Return the body of a markdown section by exact heading match.

    Body runs from the heading line to (but not including) the next heading
    at the same level. Used so each parity check reads only its own section.
    """
    text = _doc_text()
    hash_count = heading.count("#")
    sibling_re = re.compile(rf"^#{{1,{hash_count}}} ", re.MULTILINE)
    start = text.index(heading)
    after_heading = start + len(heading)
    rest = text[after_heading:]
    m = sibling_re.search(rest)
    end = after_heading + m.start() if m else len(text)
    return text[start:end]


def test_env_var_table_matches_source() -> None:
    """Env var names in deploying.md match os.environ.get calls in server.py.

    Drift the doc against server.py and this fails with a set diff naming
    the missing or extra NTHLAYER_* names.
    """
    section = _doc_section("### Environment variables")
    doc_vars = set(re.findall(r"`(NTHLAYER_[A-Z_]+)`", section))

    src = SERVER_SRC.read_text(encoding="utf-8")
    src_vars = set(re.findall(r'os\.environ\.get\(\s*"(NTHLAYER_[A-Z_]+)"', src))

    assert doc_vars == src_vars, (
        f"In doc but not server.py: {sorted(doc_vars - src_vars)}\n"
        f"In server.py but not doc: {sorted(src_vars - doc_vars)}"
    )


def test_cli_subsection_matches_argparse() -> None:
    """CLI flags documented in deploying.md match cli.py's argparse surface.

    Imports the real parser via ``build_parser()`` and walks its actions
    (plus any subparsers) so the test sees exactly what users see.
    """
    section = _doc_section("### CLI")
    doc_flags = set(re.findall(r"--[a-z][a-z0-9-]*", section))

    parser = build_parser()
    src_flags: set[str] = set()
    for action in parser._actions:
        src_flags.update(o for o in action.option_strings if o.startswith("--"))
        # Recurse into subparsers (serve, etc.).
        if isinstance(action, argparse._SubParsersAction):
            for sub_parser in action.choices.values():
                for sub_action in sub_parser._actions:
                    src_flags.update(
                        o for o in sub_action.option_strings if o.startswith("--")
                    )
    src_flags -= AUTO_FLAGS

    assert doc_flags == src_flags, (
        f"In doc but not cli.py: {sorted(doc_flags - src_flags)}\n"
        f"In cli.py but not doc: {sorted(src_flags - doc_flags)}"
    )


def test_manifests_extensions_match_catalogue() -> None:
    """Doc claim about manifest file extensions matches catalogue.py's globs.

    catalogue.py loads ``*.yaml`` AND ``*.yml`` at the top level (no
    recursion); deploying.md's Manifests directory layout subsection
    must name both extensions.
    """
    section = _doc_section("### Manifests directory layout")
    doc_extensions = set(re.findall(r"\*\.(yaml|yml)", section))

    src = CATALOGUE_SRC.read_text(encoding="utf-8")
    src_extensions = set(re.findall(r'glob\(\s*"\*\.(yaml|yml)"', src))

    assert doc_extensions == src_extensions, (
        f"In doc but not catalogue.py: {sorted(doc_extensions - src_extensions)}\n"
        f"In catalogue.py but not doc: {sorted(src_extensions - doc_extensions)}"
    )
