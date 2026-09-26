"""Smoke test: the version actually installed, against what the artifact asked for.

Runs in the normal suite AND in the release container. It is DECISIVE in the
container, because that is the only place in this pipeline where the published
ranges are the ones in force: the wheel is installed with
`pip install /dist/*.whl` and every dependency comes from PyPI, whereas
everywhere else `tool.uv.sources` substitutes the sibling checkout.

Reads installed metadata rather than pyproject.toml because that metadata is
what consumers actually get — true in both environments. Its sibling
tests/test_dependency_declarations.py reads the source of truth instead, so the
two disagree exactly when a build is stale.

Why this file exists: the container gate already ran and missed opensrm-p3bm.
Resolving from the registry is not the same as checking WHAT it resolved, and
no pre-existing smoke test asserts a version, so a range that is wrong but
satisfiable produced a green container.
"""
from __future__ import annotations

from importlib.metadata import distribution, version

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

DISTRIBUTION = "nthlayer-core"

# Each sibling mapped to the MAJOR this repo is developed against. Stated
# independently rather than derived from the declared range — deriving it would
# make the test agree with whatever the range says, including a wrong one. Only
# the major, so ordinary minor and patch upgrades flow through untouched.
EXPECTED_MAJORS = {"nthlayer-common": 2}


def _declared_requirements() -> dict[str, Requirement]:
    """The unconditional ranges the built wheel shipped, per its own metadata.

    Marker-guarded requirements are dropped: they apply only on some
    interpreters or extras, so "the installed version satisfies this" is not a
    claim that holds environment-independently. Every sibling in
    EXPECTED_MAJORS is unconditional, and the `name in declared` assertion below
    fails loudly if one ever stops being.
    """
    reqs = (Requirement(r) for r in (distribution(DISTRIBUTION).requires or []))
    return {r.name: r for r in reqs if not r.marker}


@pytest.mark.parametrize("name", sorted(EXPECTED_MAJORS))
def test_installed_version_satisfies_the_artifact_metadata(name):
    """Catches a stale build, which is how it earned its keep during opensrm-p3bm.

    Editing pyproject.toml and re-locking without re-syncing leaves the
    installed dist-info carrying the old range. This test is what said so.
    """
    declared = _declared_requirements()
    assert name in declared, (
        f"{DISTRIBUTION} does not declare {name} at all — check that the wheel "
        f"metadata survived the build"
    )
    assert version(name) in declared[name].specifier


@pytest.mark.parametrize("name", sorted(EXPECTED_MAJORS))
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
    # Version().major, not int(split(".")[0]): an epoch version like 1!2.0.0
    # makes the naive split yield "1!2" and raise ValueError, so the gate would
    # die on a traceback instead of the assertion message below.
    major = Version(installed).major
    expected = EXPECTED_MAJORS[name]
    assert major == expected, (
        f"{name} resolved from the registry to {installed} (major {major}), but "
        f"this release is built and tested against major {expected}. The "
        f"declared range in pyproject.toml admits a major nothing here has run "
        f"— the exact shape of opensrm-p3bm, where <2.0.0 shipped while 2.1.2 "
        f"was under test."
    )
