"""The scaffold's own tests are the scaffold's, and do not ship.

`src/hooks/__tests__/useAgentChat.test.tsx` was copied into every generated
application. `tsconfig.json` there excludes only `node_modules`, so `next
build` type-checked a file importing `vitest` and `@testing-library/react` —
neither of which `standalone-app/package.json.tmpl` declares, and neither of
which it should: an application gets a test suite from
`services.test_suite_emitter`, which writes `src/__tests__/generated/` AND
injects the `vitest` devDependency beside it. Tests arrive with their runner
or they do not arrive.

`test_template_dep_coverage` had been reporting this for as long as the file
existed, and was read as a scanner walking directories it should not — the
scanner was right and the copy was wrong.

WHY THIS TEST AND NOT JUST THAT ONE. The dependency test reasons about
imports; this one reasons about files, at the copier. They fail for different
reasons: a test file that imported nothing outside the floor would be invisible
to the first and is caught by this.
"""
from __future__ import annotations

from pathlib import Path

from services.blueprint.assembly import (
    copy_scaffold, skipped_by_scaffold,
)


def _floor() -> Path:
    from services.app_emitter import _TEMPLATE_DIR
    return _TEMPLATE_DIR.parent / "app-foundation"


def test_the_floor_really_does_carry_a_test_file():
    """The premise. If the scaffold ever stops shipping one, this test is
    measuring nothing and should be deleted rather than left green."""
    assert list(_floor().rglob("__tests__/*")), (
        "no __tests__ under the app-foundation floor — this guard has nothing "
        "left to guard"
    )


def test_no_scaffold_test_file_reaches_a_generated_app(tmp_path):
    copy_scaffold(tmp_path, project_short_id="t")
    stowaways = sorted(
        str(p.relative_to(tmp_path))
        for p in tmp_path.rglob("*")
        if p.is_file() and "__tests__" in p.parts
    )
    assert not stowaways, f"scaffold tests copied into the app: {stowaways}"


def test_the_rule_is_about_the_directory_not_the_filename(tmp_path):
    """`stopWhen.node.mjs` is not named `*.test.*` and is still the scaffold
    testing itself. The directory is what says so."""
    assert skipped_by_scaffold(Path("src/lib/__tests__/stopWhen.node.mjs"))
    assert skipped_by_scaffold(Path("src/hooks/__tests__/useAgentChat.test.tsx"))
    assert not skipped_by_scaffold(Path("src/lib/stopWhen.ts"))


def test_the_app_still_gets_the_rest_of_the_floor(tmp_path):
    """The exclusion must not take anything else with it — `src/lib` is the
    runtime the catch-all route imports."""
    copy_scaffold(tmp_path, project_short_id="t")
    assert (tmp_path / "src" / "lib" / "stopWhen.ts").is_file()
    assert (tmp_path / "tsconfig.json").is_file()


def test_an_emitted_suite_is_not_what_this_excludes():
    """`test_suite_emitter` writes `src/__tests__/generated/` INTO the app
    after the copy, and injects `vitest` with it. That path is untouched here:
    this rule only governs what is copied out of the templates."""
    from services import test_suite_emitter

    assert test_suite_emitter.GENERATED_DIR.startswith("src")
    assert "__tests__" in test_suite_emitter.GENERATED_DIR
