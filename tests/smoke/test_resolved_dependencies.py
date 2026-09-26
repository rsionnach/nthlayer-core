"""Smoke test: the version actually installed, against what the artifact asked for.

Runs inside the release container, where the wheel was installed with
`pip install /dist/*.whl` and every dependency came from PyPI. That is the only
place in this repo's pipeline where the PUBLISHED dependency ranges are the ones
in force — everywhere else `tool.uv.sources` substitutes the sibling checkout.

This container gate already existed and did not catch opensrm-p3bm, because
resolving from the registry is not the same as checking WHAT it resolved. The
wheel declared `nthlayer-common>=1.5.0,<2.0.0`, pip dutifully installed 1.7.0,
the import and CLI smoke tests passed — and they would have passed on either
major, because none of them assert a version. A range that is wrong but
satisfiable produces a green container.

Reads only installed metadata, never pyproject.toml: the source tree is not
mounted here, and the wheel's own metadata is the artifact consumers get.
"""
from __future__ import annotations

from importlib.metadata import distribution, version

import pytest
from packaging.requirements import Requirement

DISTRIBUTION = "nthlayer-core"

# Siblings whose resolved version this asserts on. Names only — an expected
# version pinned here would need updating in lockstep with pyproject.toml and
# would be the copy that drifts.
SIBLING_DEPS = ("nthlayer-common",)

# The major each sibling is developed against — an independent statement of
# intent, which is the whole point: deriving it from the declared range would
# make the test agree with whatever the range says, including a wrong one.
EXPECTED_MAJORS = {"nthlayer-common": 2}


def _declared_requirements() -> dict[str, Requirement]:
    """The ranges the built wheel actually shipped, per its own metadata."""
    reqs = (Requirement(r) for r in (distribution(DISTRIBUTION).requires or []))
    return {r.name: r for r in reqs if not r.marker}


@pytest.mark.parametrize("name", SIBLING_DEPS)
def test_installed_version_satisfies_the_artifact_metadata(name):
    """Reads the BUILT artifact's metadata, not pyproject.toml.

    That distinction earned itself immediately: editing pyproject.toml and
    re-locking without re-syncing leaves the installed dist-info carrying the
    old range, and this test is what says so. Its sibling in
    tests/test_dependency_declarations.py reads the source of truth; this one
    reads what was actually built from it, and the two disagree exactly when a
    build is stale.
    """
    declared = _declared_requirements()
    assert name in declared, (
        f"{DISTRIBUTION} does not declare {name} at all — check that the wheel "
        f"metadata survived the build"
    )
    assert version(name) in declared[name].specifier


@pytest.mark.parametrize("name", SIBLING_DEPS)
def test_installed_sibling_is_the_major_this_code_was_written_against(name):
    """The assertion the container gate was missing.

    Decisive in the release container, where deps come from PyPI: a successful
    `pip install nthlayer_core-*.whl` says only that the declared range is
    satisfiable, not that it is right. Pinning the expected MAJOR here
    — and nothing narrower — is what distinguishes "a version was installed"
    from "the version this code was developed and tested against was
    installed", while still allowing ordinary minor and patch upgrades to flow
    through without touching this test.
    """
    installed = version(name)
    major = int(installed.split(".", 1)[0])
    expected = EXPECTED_MAJORS[name]
    assert major == expected, (
        f"{name} resolved from the registry to {installed} (major {major}), but "
        f"this release is built and tested against major {expected}. The "
        f"declared range in pyproject.toml admits a major nothing here has run "
        f"— the exact shape of opensrm-p3bm, where <2.0.0 shipped while 2.1.2 "
        f"was under test."
    )
