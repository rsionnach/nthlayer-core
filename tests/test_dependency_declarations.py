"""The declared dependency ranges must admit the versions actually in use.

This file exists because nothing else checks that claim, and it diverged
silently for four minor releases (opensrm-p3bm).

`tool.uv.sources` points nthlayer-common at the sibling checkout, and a path
source REPLACES registry resolution rather than being filtered by the version
specifier. So `uv sync` and `uv pip install .` both install whatever the
sibling happens to be — 2.1.2 — while `project.dependencies` said
`>=1.5.0,<2.0.0`. Neither command warns. Only `uv pip install --no-sources`
exercises the published range, and nothing ran it.

What that cost: `pip install nthlayer-workers==2.0.0 nthlayer-core` does not
fail. The resolver silently walks core back to 1.0.0 — the only published core
with no upper bound on common, hence the only one admitting the >=2.1.2 that
workers 2.0.0 requires. The install succeeds, the versions look plausible, and
the user gets a core eight minor versions stale.
"""
from __future__ import annotations

import tomllib
from importlib.metadata import version
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

# Siblings whose declared range must admit the installed build. Deliberately a
# list of NAMES, not of expected versions: an expected-version constant here
# would be a third place to update and the first to drift.
SIBLING_DEPS = ("nthlayer-common",)


# Operators that bound a range from above. "~=" is in here on measurement, not
# on reasoning: packaging exposes a compatible-release specifier as the single
# operator "~=" and never decomposes it into ">=" plus "<", so a predicate
# looking only for "<" rejects `~=2.1` — which does exclude 3.0.0 and IS
# bounded. test_bounding_operators_match_packaging_behaviour pins that, because
# an earlier revision of this file asserted the decomposition in a comment and
# was wrong.
BOUNDING_OPERATORS = ("<", "<=", "==", "===", "~=")


def _declared() -> dict[str, Requirement]:
    data = tomllib.loads(PYPROJECT.read_text())
    reqs = (Requirement(d) for d in data["project"]["dependencies"])
    return {r.name: r for r in reqs}


@pytest.mark.parametrize("name", SIBLING_DEPS)
def test_declared_range_admits_the_installed_sibling(name):
    """The range we publish must admit the build we test against.

    Fails the moment a sibling outgrows the ceiling, in the developer's own
    suite rather than at some consumer's install. A CI job that resolves from
    the registry is the other half of this guard (see release.yml); this half
    is what makes the failure local and immediate.
    """
    declared = _declared()
    assert name in declared, f"{name} is not declared in project.dependencies"

    installed = version(name)
    specifier = declared[name].specifier

    assert installed in specifier, (
        f"{name} {installed} is installed and tested against, but "
        f"project.dependencies declares '{name}{specifier}', which excludes "
        f"it. Publishing this means consumers resolve a version no test here "
        f"has ever run. Widen the declared range, or pin the sibling back."
    )


@pytest.mark.parametrize("name", SIBLING_DEPS)
def test_declared_range_has_an_upper_bound(name):
    """A missing ceiling is how core 1.0.0 became the resolver's escape hatch.

    Without an upper bound, a future major of the sibling is silently
    considered compatible, and this package becomes the one the resolver
    reaches for when it needs to satisfy something incompatible — which is
    exactly why `pip install nthlayer-workers==2.0.0 nthlayer-core` yields
    core 1.0.0 rather than an error.
    """
    specifier = _declared()[name].specifier
    assert any(s.operator in BOUNDING_OPERATORS for s in specifier), (
        f"'{name}{specifier}' has no upper bound, so every future major of "
        f"{name} is declared compatible without anything testing it"
    )


@pytest.mark.parametrize(
    ("spec", "bounded"),
    [
        (">=2.1.2,<3.0.0", True),
        (">=2.1.2,<=2.9.9", True),
        ("==2.1.2", True),
        ("===2.1.2", True),
        ("==2.*", True),
        ("~=2.1", True),
        ("~=2.1.2", True),
        (">=2.1.2", False),
        (">2.0", False),
        ("!=2.0.0", False),
        ("", False),
    ],
)
def test_bounding_operators_match_packaging_behaviour(spec, bounded):
    """BOUNDING_OPERATORS must agree with whether a range really excludes a future major.

    Derived from what `packaging` does, not from what the operators look like
    they should do: the expected column below is each specifier's ACTUAL verdict
    on a next-major version, asserted independently, so this test fails if
    BOUNDING_OPERATORS ever drifts from reality in either direction — a missing
    operator that false-fails a bounded range, or a spurious one that lets an
    unbounded range through.
    """
    specifier = SpecifierSet(spec)
    predicate = any(s.operator in BOUNDING_OPERATORS for s in specifier)

    assert predicate is bounded

    # Independent cross-check: a bounded range must actually reject the next
    # major. Skipped for the empty specifier, which has no operators to inspect
    # and admits everything by definition.
    if spec:
        assert ("3.0.0" in specifier) is not bounded
