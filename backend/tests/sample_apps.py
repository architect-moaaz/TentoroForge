"""Generated applications the suite reads as fixtures, and when to skip.

Nine test files hardcode an absolute path to a generated app in ANOTHER
checkout on one developer's machine, and two more read one out of this repo's
gitignored `output/`. Neither is in git; both are build products that get
cleaned.

THE GUARD WAS THERE AND CHECKED THE WRONG THING. Every one of those fixtures
already opened with

    if not _FIXTURE.exists():
        pytest.skip("bpxr6hsv fixture app not present")

and `bpxr6hsv` **does** exist — as an empty directory. So the guard passed,
the very next line copied `contracts/resource-registry.json` out of it, and 59
tests raised `FileNotFoundError` in setup instead of skipping. A directory is
not the file you are about to read, and the difference is the whole of this
module: :func:`require` is given the paths that are actually opened.

WHY NOT VENDOR THE FIXTURE. It is a whole generated application — contracts,
schemas, a nav flow, a registry. Copying one into the repo would freeze a
snapshot of output the generator is being changed under, and the tests that
read it are about what the extractors make of a REAL app. Skipping honestly is
better than asserting against a fossil.

`FORGE_SAMPLE_APP` points the lot at a different application, so anyone
holding one can run these rather than skip them.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

#: The app the `bpxr6hsv` fixtures read. Kept here rather than in nine files:
#: it is one path, written nine times, to a directory on one machine.
SAMPLE_APP = Path(os.environ.get(
    "FORGE_SAMPLE_APP",
    "/Users/m/Work/code/poc/design2ui-forge-v3/output/bpxr6hsv"))

#: The repo's own `output/` — gitignored build products, present only on a
#: machine that has generated them.
REPO_OUTPUT = Path(__file__).resolve().parents[2] / "output"


def require(*paths: str | Path) -> None:
    """Skip unless every file named here is on disk.

    Names the FIRST missing path in the reason, so a partial fixture — the
    case that produced the original defect — says which piece is absent
    rather than "not present".
    """
    for path in paths:
        if not Path(path).exists():
            pytest.skip(f"sample app not present: {path} is missing "
                        "(set FORGE_SAMPLE_APP to one you have)")


__all__ = ["REPO_OUTPUT", "SAMPLE_APP", "require"]
