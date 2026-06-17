"""Drift gate for docs/deploying.md against source.

Three parity checks pinning the doc's Reference section to reality:

1. Env-var table rows match ``os.environ.*`` lookups across the package.
2. CLI subsection matches argparse surface (flags AND subcommand names) in cli.py.
3. Manifests directory layout claim mentions both extensions catalogue.py loads.

Pattern follows ``test_openapi.py::test_route_parity`` (tu04.1). When source
adds, renames, or removes a documented surface, the corresponding test fails
with a diff naming the missing/extra symbols — the doc must be updated to
match before merge.

Each test also has a non-empty guard so a config-plumbing or loader
refactor that empties the source-side set can't pass silently against an
also-empty doc-side set (R5 P3 edge-case finding).

Bead: opensrm-tu04.2.1.
"""
from __future__ import annotations

import argparse
import pathlib
import re

from nthlayer_core.cli import build_parser

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEPLOYING_DOC = REPO_ROOT / "docs" / "deploying.md"
PACKAGE_SRC = REPO_ROOT / "src" / "nthlayer_core"
CATALOGUE_SRC = PACKAGE_SRC / "catalogue.py"

# argparse adds --help automatically; the doc deliberately doesn't list it
# (universal flag, not nthlayer-specific). Strip it from the source-side set.
AUTO_FLAGS = frozenset({"--help"})


def _doc_text() -> str:
    return DEPLOYING_DOC.read_text(encoding="utf-8")


def _doc_section(heading: str) -> str:
    """Return the body of a markdown section by exact heading match.

    Body runs from the heading line to (but not including) the next heading
    at the same level or higher. Heading is matched line-anchored so a deeper
    heading reusing the wording (e.g. ``#### Environment variables``) doesn't
    collide with the requested ``### Environment variables``.
    """
    text = _doc_text()
    heading_level = heading.count("#")
    heading_re = re.compile(rf"^{re.escape(heading)} *$", re.MULTILINE)
    sibling_re = re.compile(rf"^#{{1,{heading_level}}} ", re.MULTILINE)
    m = heading_re.search(text)
    if m is None:
        raise AssertionError(f"deploying.md missing heading: {heading}")
    start = m.start()
    after_heading = m.end()
    sib = sibling_re.search(text, after_heading)
    end = sib.start() if sib else len(text)
    return text[start:end]


def test_env_var_table_matches_source() -> None:
    """Env var names in deploying.md match os.environ lookups in the package.

    Scans every .py file under src/nthlayer_core (not just server.py) so a
    config-module refactor that moves lookups elsewhere doesn't silently
    break the gate.

    Drift the doc against the source and this fails with a set diff naming
    the missing or extra NTHLAYER_* names.
    """
    section = _doc_section("### Environment variables")
    doc_vars = set(re.findall(r"`(NTHLAYER_[A-Z_]+)`", section))

    # Cover all three idiomatic lookup forms — os.environ.get(), os.getenv(),
    # and os.environ["..."] — so a refactor that switches form doesn't make
    # the gate silently miss a new var.
    src_vars: set[str] = set()
    for py_file in PACKAGE_SRC.rglob("*.py"):
        src = py_file.read_text(encoding="utf-8")
        for pattern in (
            r'os\.environ\.get\(\s*"(NTHLAYER_[A-Z_]+)"',
            r'os\.getenv\(\s*"(NTHLAYER_[A-Z_]+)"',
            r'os\.environ\[\s*"(NTHLAYER_[A-Z_]+)"\s*\]',
        ):
            src_vars.update(re.findall(pattern, src))

    # Non-empty guard: source-side empty + doc-side empty would pass
    # silently. Today there are 2 env vars; if this drops to 0 the
    # config plumbing has moved somewhere this test doesn't see.
    assert src_vars, (
        "no NTHLAYER_* env vars found in src/nthlayer_core/ — did config "
        "move to a form this test does not recognise (pydantic-settings, "
        "dotenv, typing.cast, etc.)? Broaden the patterns or scope above."
    )

    assert doc_vars == src_vars, (
        f"In doc but not source: {sorted(doc_vars - src_vars)}\n"
        f"In source but not doc: {sorted(src_vars - doc_vars)}"
    )


def test_cli_subsection_matches_argparse() -> None:
    """CLI flags AND subcommand names documented in deploying.md match cli.py.

    Imports the real parser via ``build_parser()`` and walks its actions
    (plus any subparsers) so the test sees exactly what users see.

    Pins both *flag* parity and *subcommand-name* parity — a new top-level
    subcommand (e.g. ``nthlayer migrate``) added to cli.py without a
    matching mention in the deploying.md CLI section fails this test.
    """
    section = _doc_section("### CLI")
    doc_flags = set(re.findall(r"--[a-z][a-z0-9-]*", section))

    # argparse exposes no public introspection API; `_actions` is the
    # documented-by-convention escape hatch (used the same way by Sphinx's
    # argparse extension and similar tooling).
    parser = build_parser()
    src_flags: set[str] = set()
    src_subcommands: set[str] = set()
    for action in parser._actions:
        src_flags.update(o for o in action.option_strings if o.startswith("--"))
        # Recurse into subparsers (serve, etc.).
        if isinstance(action, argparse._SubParsersAction):
            src_subcommands.update(action.choices.keys())
            for sub_parser in action.choices.values():
                for sub_action in sub_parser._actions:
                    src_flags.update(
                        o for o in sub_action.option_strings if o.startswith("--")
                    )
    src_flags -= AUTO_FLAGS

    assert src_flags, (
        "build_parser() exposed no flags — did the CLI surface collapse?"
    )

    assert doc_flags == src_flags, (
        f"In doc but not cli.py: {sorted(doc_flags - src_flags)}\n"
        f"In cli.py but not doc: {sorted(src_flags - doc_flags)}"
    )

    # Subcommand-name parity: each subcommand registered with the parser
    # must appear verbatim in the CLI section (typically inside a code
    # block like ``nthlayer serve``). Catches "new subcommand added,
    # nobody updated the docs."
    missing_subcommands = {sc for sc in src_subcommands if sc not in section}
    assert not missing_subcommands, (
        f"cli.py subcommands not mentioned in deploying.md ### CLI section: "
        f"{sorted(missing_subcommands)}"
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

    # Non-empty guard: a refactor that moves catalogue loading to a
    # different file or a different idiom (e.g. `EXTS = ("*.yaml", "*.yml")`
    # then a loop) would silently drop src_extensions to empty.
    assert src_extensions, (
        "no *.yaml/*.yml glob calls found in catalogue.py — did the "
        "loader move to a different file or stop using pathlib.glob?"
    )

    assert doc_extensions == src_extensions, (
        f"In doc but not catalogue.py: {sorted(doc_extensions - src_extensions)}\n"
        f"In catalogue.py but not doc: {sorted(src_extensions - doc_extensions)}"
    )
