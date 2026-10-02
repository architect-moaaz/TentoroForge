"""`npm run build` has to build everything the backend then imports.

Six packages with a `build` script were reachable from no root script:
`ir`, `compiler`, `ahtml`, `patterns`, `roundtrip` and `figma-parser`. The
root `build` ran the engine stack and the editor stack and stopped.

WHAT THAT COST. `services/ir_compiler.py` shells out to
`packages/compiler/dist/index.js` and `services/ahtml_compiler.py` imports
three files out of `packages/ahtml/dist/` — so on any checkout where somebody
had run the documented build and nothing else, both services failed at
runtime with `ERR_MODULE_NOT_FOUND`, and eleven tests reported it as an "IR
compiler error" rather than as a missing build. Forty-eight of the suite's
failures were unbuilt dists, most of them from one package.

A LIST IS WHY IT HAPPENED, SO THE LIST IS WHAT IS CHECKED. The root script
names its workspaces one by one; a package added later is simply not in it,
and nothing says so. This walks `packages/*` instead: every package that
declares a `build` must be reachable from the root `build`, and a package
that declares none is fine (`catalog` ships JSON, and builds nothing).

ORDER IS PART OF THE CONTRACT. `compiler` does not compile until `ir` has a
dist — `npm run build --workspace=packages/compiler` fails outright on a
clean tree — so the stack that contains them must name `ir` first. That is
asserted too, because the failure it prevents looks like a broken compiler
rather than a mis-ordered script.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ROOT / "packages"


def _scripts() -> dict[str, str]:
    return json.loads((ROOT / "package.json").read_text("utf-8")).get("scripts") or {}


def _reachable_from(script: str, seen: frozenset[str] = frozenset()) -> set[str]:
    """Every `packages/<name>` a root script builds, following `npm run` hops."""
    scripts = _scripts()
    body = scripts.get(script)
    if body is None or script in seen:
        return set()
    out = set(re.findall(r"--workspace=packages/([A-Za-z0-9_-]+)", body))
    for nested in re.findall(r"npm run ([A-Za-z0-9:_-]+)", body):
        if nested in scripts:
            out |= _reachable_from(nested, seen | {script})
    return out


def _builds() -> set[str]:
    """Packages that declare a `build` script — the ones that produce a dist."""
    out = set()
    for pkg in sorted(PACKAGES.iterdir()):
        manifest = pkg / "package.json"
        if not manifest.is_file():
            continue
        if "build" in (json.loads(manifest.read_text("utf-8")).get("scripts") or {}):
            out.add(pkg.name)
    return out


def test_every_package_that_builds_is_reachable_from_the_root_build():
    missing = sorted(_builds() - _reachable_from("build"))
    assert not missing, (
        "these packages declare a `build` script that `npm run build` never "
        f"runs: {missing}. Add them to a stack the root `build` calls — a "
        "dist nobody builds is a module the backend cannot import at runtime."
    )


def test_the_root_build_names_no_package_that_cannot_build():
    """The other direction: a workspace named in a stack must exist and have
    something to build, or the whole chain exits non-zero on `&&`."""
    named = _reachable_from("build")
    assert named, "the root `build` names no packages at all"
    unbuildable = sorted(named - _builds())
    assert not unbuildable, (
        f"the root `build` runs `npm run build` for {unbuildable}, which "
        "declare no build script — the chain stops there."
    )


@pytest.mark.parametrize("earlier,later", [("ir", "compiler"),
                                           ("ir", "ahtml"),
                                           ("compiler", "patterns"),
                                           ("compiler", "roundtrip")])
def test_a_package_is_built_after_what_it_compiles_against(earlier, later):
    """`tsc` on `compiler` resolves `@tentoroforge/ir` through its dist. Built
    in the wrong order the build fails, and it fails looking like the later
    package is broken."""
    body = " && ".join(_scripts().get(name, "") for name in
                       ("build:engine-stack", "build:editor-stack",
                        "build:ir-stack", "build:figma-stack"))
    where = {name: body.find(f"--workspace=packages/{name}")
             for name in (earlier, later)}
    assert where[earlier] >= 0 and where[later] >= 0, where
    assert where[earlier] < where[later], (
        f"{later} is built before {earlier}, which it compiles against"
    )


def test_a_package_that_builds_nothing_is_not_required_to():
    """`catalog` ships `workflow-nodes.json` and declares no build. The check
    above must not start demanding one."""
    catalog = json.loads((PACKAGES / "catalog" / "package.json").read_text("utf-8"))
    assert "build" not in (catalog.get("scripts") or {})
    assert "catalog" not in _reachable_from("build")
