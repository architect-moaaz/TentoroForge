"""A run that plans N pages and ships fewer must say which ones are missing.

`verify_build` proves the assembled tree compiles. It cannot notice that half
the pages are absent from it, because every node downstream of composition
faithfully projects whatever survived — the projection is lossless, and
everything is lost at composition.

Two real builds, both reported successful:

    53 planned -> 27 served
    38 planned -> 23 served   (/cases/new, /admin/users/new, /audit-log, ...)

Read from the generated `src/schemas/registry.ts` rather than re-derived from
the Blueprint, so the funnel cannot agree with the intent by construction while
disagreeing with the application.
"""
import json

import pytest

from services.blueprint.assembly import page_funnel


def _app(tmp_path, routes):
    """A generated app whose registry serves exactly `routes`."""
    schemas = tmp_path / "src" / "schemas"
    schemas.mkdir(parents=True)
    body = "\n".join(f'  "{r}": () => import("./x.json"),' for r in routes)
    (schemas / "registry.ts").write_text(
        "export const schemas: Record<string, () => Promise<unknown>> = {\n"
        + body + "\n};\n", encoding="utf-8")
    return tmp_path


def _doc(routes):
    return {"pages": [{"id": f"PAGE-{i:03}", "route": r}
                      for i, r in enumerate(routes, 1)]}


def test_a_complete_run_is_complete(tmp_path):
    routes = ["/contacts", "/contacts/[id]", "/contacts/new"]
    f = page_funnel(_doc(routes), _app(tmp_path, routes))
    assert f["status"] == "complete"
    assert f["missing"] == []
    assert f["planned"] == f["served"] == 3


def test_a_short_run_names_every_page_it_did_not_ship(tmp_path):
    planned = ["/cases", "/cases/new", "/audit-log", "/admin/users/new"]
    served = ["/cases", "/audit-log"]
    f = page_funnel(_doc(planned), _app(tmp_path, served))
    assert f["status"] == "short"
    assert f["planned"] == 4
    assert f["served"] == 2
    assert f["missing"] == ["/admin/users/new", "/cases/new"]


def test_a_missing_registry_is_a_shortfall_not_a_crash(tmp_path):
    """`frontend` never running is exactly how the registry goes missing, and
    that must be reported rather than raise inside the preview node."""
    f = page_funnel(_doc(["/cases"]), tmp_path)
    assert f["status"] == "short"
    assert f["missing"] == ["/cases"]


def test_an_application_with_no_pages_is_complete_not_short(tmp_path):
    """Nothing planned, nothing missing. `short` must mean a real shortfall."""
    f = page_funnel({"pages": []}, _app(tmp_path, []))
    assert f["status"] == "complete"
    assert f["planned"] == 0


def test_extra_served_routes_are_not_a_shortfall(tmp_path):
    """The scaffold ships /login and /signup that no Blueprint page plans."""
    f = page_funnel(_doc(["/cases"]), _app(tmp_path, ["/cases", "/login", "/signup"]))
    assert f["status"] == "complete"
    assert f["missing"] == []
