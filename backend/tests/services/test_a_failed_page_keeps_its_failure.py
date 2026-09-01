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


def test_the_scaffold_import_is_what_makes_it_fatal():
    """`globals.css` is preserved by the emitter, so the tokens are a separate
    file it imports. That is a good reason and it means the import is
    unconditional: nothing degrades gracefully if the file is absent."""
    import pathlib

    scaffold = (pathlib.Path(__file__).resolve().parents[2]
                / "templates" / "app-foundation" / "src" / "app" / "globals.css")
    assert '@import "./tokens.css";' in scaffold.read_text(encoding="utf-8")
    # And the scaffold does not ship one — the projection is the only writer,
    # which is exactly why it must not be skippable.
    assert not (scaffold.parent / "tokens.css").exists()


def test_design_tokens_needs_nothing_from_the_planner():
    """The justification for moving it above the raise: it reads the design
    system, and a page that would not render has no bearing on it."""
    from services.blueprint import projection

    src = inspect.getsource(projection.project_design_tokens)
    assert 'doc.get("designSystem"' in src
    assert "failed" not in src
