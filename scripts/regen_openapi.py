"""Regenerate docs/api/openapi.json from the OPENAPI source-of-truth dict.

Run manually after editing any src/nthlayer_core/_openapi/paths_*.py:

    uv run python scripts/regen_openapi.py

The checked-in artefact MUST match what this script produces. A test
(tests/test_openapi.py::test_checked_in_artefact_matches) gates this in
CI — PRs that change the spec must commit the regenerated JSON.

Bead: opensrm-tu04.1.1.
"""
from __future__ import annotations

import json
import pathlib
import sys

from nthlayer_core.openapi_spec import OPENAPI

OUT = pathlib.Path(__file__).resolve().parent.parent / "docs" / "api" / "openapi.json"


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(OPENAPI, indent=2, sort_keys=False) + "\n")
    print(f"wrote {OUT.relative_to(OUT.parent.parent.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
