"""The declared dependency ranges must admit the versions actually in use.

Reads pyproject.toml, the source of truth, and fails locally the moment a
sibling outgrows the declared range. Its counterpart
tests/smoke/test_resolved_dependencies.py reads the BUILT artifact's metadata
instead and is decisive in the release container.

The full account of why both exist is nthlayer-core CLAUDE.md hard rule 10
[opensrm-p3bm]. The short version: `tool.uv.sources` points nthlayer-common at
the sibling checkout, a path source REPLACES registry resolution rather than
being filtered by the version specifier, and nothing warned that the declared
range and the tested version had diverged.

The guarded set is DISCOVERED from project.dependencies, never hand-listed. A
hand-maintained roster can fall behind pyproject, and a roster that empties
turns every parametrised assertion below into `1 skipped, exit 0` — the same
class of bug this file exists to catch, one coordinate over.
test_at_least_one_sibling_is_guarded is the non-vacuity floor.
"""
from __future__ import annotations

import tomllib
from collections import Counter
from importlib.metadata import version
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

# Ecosystem siblings are exactly the dependencies under this prefix. Discovery
# by prefix rather than by name means a newly added sibling is guarded the day
# it is declared, with no second list to remember.
SIBLING_PREFIX = "nthlayer-"

# Operators that bound a range from above. "~=" is here on measurement, not on
# reasoning: packaging exposes a compatible-release specifier as the single
# operator "~=" and never decomposes it into ">=" plus "<", so a predicate
# looking only for "<" rejects `~=2.1` — which does exclude 3.0.0 and IS
# bounded. test_bounding_operators_match_packaging_behaviour pins that, because
# an earlier revision of this file asserted the decomposition in a comment and
# was wrong.
BOUNDING_OPERATORS = ("<", "<=", "==", "===", "~=")

# A version no realistic range admits. Lets the cross-check below ask a
# specifier what it actually does about the far future, instead of hardcoding
# one major and false-failing any case that lives at another.
UNBOUNDED_PROBE = "9999.0.0"


def _declared() -> list[Requirement]:
    data = tomllib.loads(PYPROJECT.read_text())
    return [Requirement(d) for d in data["project"]["dependencies"]]


def _siblings() -> dict[str, Requirement]:
    """Canonical-name -> requirement, for every declared ecosystem sibling.

    Names are canonicalised on the way in: `Requirement("nthlayer_common>=2")`
    reports its name verbatim as `nthlayer_common`, so an underscore spelling
    would otherwise read as a different, undeclared package.
    """
    return {
        canonicalize_name(r.name): r
        for r in _declared()
        if canonicalize_name(r.name).startswith(SIBLING_PREFIX)
    }


# Evaluated at collection time. If it is ever empty the parametrised tests below
# skip rather than fail, which test_at_least_one_sibling_is_guarded prevents.
SIBLINGS = sorted(_siblings())


def test_at_least_one_sibling_is_guarded():
    """Non-vacuity floor for every parametrised test in this file.

    An empty parametrise list is reported as `1 skipped` with exit 0. Measured,
    not assumed. Two bugs in this workspace have already shipped behind exactly
    that — a module that skipped itself when a path lookup missed, and a
    predicate whose fixture shape was unreal — so a file whose whole purpose is
    catching silent drift must not be able to go quiet itself.
    """
    assert SIBLINGS, (
        f"no dependency under '{SIBLING_PREFIX}' found in {PYPROJECT.name}; "
        f"every check in this file would silently skip"
    )


def test_no_sibling_is_declared_twice():
    """A duplicate entry silently last-wins, and can ship the broken range.

    A name-keyed dict keeps whichever comes last. Measured:
    `[nthlayer-common>=2.1.2,<3.0.0, nthlayer-common<2.0.0]` collapses to
    `<2.0.0` — so a leftover second entry has the guard verify one range while
    the wheel ships another, and in that ordering the old broken ceiling passes
    green.
    """
    names = [canonicalize_name(r.name) for r in _declared()]
    duplicated = sorted(n for n, count in Counter(names).items() if count > 1)
    assert not duplicated, (
        f"declared more than once in {PYPROJECT.name}: {duplicated}. The later "
        f"entry wins silently, so the range checked here need not be the range "
        f"shipped."
    )


@pytest.mark.parametrize("name", SIBLINGS)
def test_declared_range_admits_the_installed_sibling(name):
    """The range we publish must admit the build we test against.

    Fails the moment a sibling outgrows the ceiling, in the developer's own
    suite rather than at some consumer's install.
    """
    installed = version(name)
    specifier = _siblings()[name].specifier

    assert installed in specifier, (
        f"{name} {installed} is installed and tested against, but "
        f"project.dependencies declares '{name}{specifier}', which excludes "
        f"it. Publishing this means consumers resolve a version no test here "
        f"has ever run. Widen the declared range, or pin the sibling back."
    )


@pytest.mark.parametrize("name", SIBLINGS)
def test_declared_range_has_an_upper_bound(name):
    """A missing ceiling is how core 1.0.0 became the resolver's escape hatch.

    Without an upper bound, a future major of the sibling is silently
    considered compatible, and this package becomes the one the resolver
    reaches for when it needs to satisfy something incompatible — which is
    exactly why `pip install nthlayer-workers==2.0.0 nthlayer-core` yielded
    core 1.0.0 rather than an error.
    """
    specifier = _siblings()[name].specifier
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
        (">=4.0", False),
        (">=2.1.2", False),
        (">2.0", False),
        ("!=2.0.0", False),
        ("", False),
    ],
)
def test_bounding_operators_match_packaging_behaviour(spec, bounded):
    """BOUNDING_OPERATORS must agree with whether a range really bounds above.

    Derived from what `packaging` does, not from what the operators look like
    they should do. The cross-check asks each specifier about UNBOUNDED_PROBE
    rather than a hardcoded next-major, so a case at any major — see `>=4.0` —
    is judged on its own behaviour. Fails on drift in either direction: an
    operator missing from the tuple that false-fails a bounded range, or a
    spurious one that lets an unbounded range through.
    """
    specifier = SpecifierSet(spec)
    predicate = any(s.operator in BOUNDING_OPERATORS for s in specifier)

    assert predicate is bounded
    assert (UNBOUNDED_PROBE in specifier) is not bounded
