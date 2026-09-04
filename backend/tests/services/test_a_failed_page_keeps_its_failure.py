"""One page that cannot be planned does not take the application with it.

    ./src/app/globals.css
    Module not found: Can't resolve './tokens.css'
    GET / 500

The scaffold's `globals.css` imports `./tokens.css` unconditionally and
`project_design_tokens` is the only thing that writes it. `_project_frontend`
raised `PlanError` the moment any page failed to plan — before the five
projections below it — so one bad prop on one page cost the stylesheet, the
route graph, the middleware, the public-resource list and the root route.

The result was not an application with one broken page. It was an application
that would not compile, reporting a missing CSS import and naming nothing that
had anything to do with the cause.
"""
from __future__ import annotations

import inspect

import pytest

from services.blueprint import orchestrator


def _source() -> str:
    return inspect.getsource(orchestrator._project_frontend)


#: Everything in `_project_frontend` that reads the Blueprint rather than the
#: planning result, and so has no business being skipped when a page fails.
INDEPENDENT = (
    "project_nav_flow",
    "project_design_tokens",
    "project_middleware",
    "project_public_resources",
    "project_root_route",
)


@pytest.mark.parametrize("projection", INDEPENDENT)
def test_it_runs_before_the_refusal(projection):
    src = _source()
    assert src.index(f"{projection}(svc.doc") < src.index("raise PlanError"), (
        f"{projection} is skipped when any page fails to plan"
    )


def test_the_refusal_still_happens():
    """The pages really did fail. This is about what the failure destroys, not
    about tolerating it — the node must still fail so the retry runs."""
    assert "raise PlanError" in _source()


def test_the_scaffold_ships_what_it_imports():
    """THE SOURCE, not the trigger. `globals.css` imports `./tokens.css`
    unconditionally — correctly, since globals.css is preserved by the emitter
    — so a scaffold without that file does not build. Skipping the projection
    was one way to reach it; a crash, a timeout, a partial run or an export
    taken mid-build all reach the same place.
    """
    import pathlib

    app = (pathlib.Path(__file__).resolve().parents[2]
           / "templates" / "app-foundation" / "src" / "app")
    assert '@import "./tokens.css";' in (app / "globals.css").read_text("utf-8")
    assert (app / "tokens.css").exists(), (
        "the scaffold imports a file it does not contain, so it does not build"
    )


def test_the_default_never_overwrites_the_real_palette(tmp_path):
    """Assembly runs AFTER projection, so a scaffold file that always copied
    would replace the application's own tokens with the neutral ones on every
    build. It fills a hole; it does not win."""
    from services.blueprint.assembly import copy_scaffold

    app = tmp_path / "app"
    (app / "src" / "app").mkdir(parents=True)
    (app / "src" / "app" / "tokens.css").write_text(":root{--accent:#A16207}")
    copy_scaffold(app, project_short_id="t")
    assert "#A16207" in (app / "src" / "app" / "tokens.css").read_text()


def test_the_default_lands_when_nothing_projected_one(tmp_path):
    from services.blueprint.assembly import copy_scaffold

    app = tmp_path / "app"
    copy_scaffold(app, project_short_id="t")
    assert (app / "src" / "app" / "tokens.css").exists(), (
        "a scaffold with no projection behind it still has to build"
    )


def test_design_tokens_needs_nothing_from_the_planner():
    """The justification for moving it above the raise: it reads the design
    system, and a page that would not render has no bearing on it."""
    from services.blueprint import projection

    src = inspect.getsource(projection.project_design_tokens)
    assert 'doc.get("designSystem"' in src
    assert "failed" not in src
