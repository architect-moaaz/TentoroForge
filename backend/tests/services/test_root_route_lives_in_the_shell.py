"""`/` resolves inside the group that carries the sidebar.

Every route in a generated application renders through `[...slug]` inside
`src/app/(dashboard)/`, so it inherits `(dashboard)/layout.tsx` — the shell,
with the sidebar and the top bar. `/` is the one route that cannot: Next's
catch-all is *required* and never matches the root.

`project_root_route` filled that gap by writing `src/app/page.tsx`, on the
stated grounds that "the scaffold shipped one that redirects to a hardcoded
/home". The scaffold stopped doing that: it now ships
`src/app/(dashboard)/page.tsx`, which renders the `/` schema exactly as the
catch-all would.

So there were two files resolving to `/` — route groups do not affect the URL —
rendering identical content from the same registry key, and the one this
projection wrote sat outside the group. The dashboard loaded without a sidebar
and every other page had one, which reads as a styling bug rather than a
routing one.
"""
from __future__ import annotations

import pathlib

from services.blueprint.projection import project_root_route


def _app(tmp_path) -> pathlib.Path:
    app = tmp_path / "app"
    (app / "src" / "app" / "(dashboard)").mkdir(parents=True)
    (app / "src" / "app" / "(dashboard)" / "page.tsx").write_text(
        "// scaffold: renders / from the registry, inside the shell\n")
    return app


def _claims_root():
    return {"pages": [{"id": "PAGE-001", "route": "/", "name": "Home"}],
            "navigation": {}}


def test_the_scaffold_page_is_left_to_do_its_job(tmp_path):
    """Rewriting it with an identical body would be this projection claiming
    ownership of something it does not need to own."""
    app = _app(tmp_path)
    result = project_root_route(_claims_root(), app)
    assert result["files"] == []
    kept = (app / "src" / "app" / "(dashboard)" / "page.tsx").read_text()
    assert "scaffold" in kept


def test_no_second_handler_is_written_outside_the_group(tmp_path):
    app = _app(tmp_path)
    project_root_route(_claims_root(), app)
    assert not (app / "src" / "app" / "page.tsx").exists(), (
        "a root page outside (dashboard) resolves to / without the shell"
    )


def test_a_root_page_from_an_older_build_is_removed(tmp_path):
    """While it exists it shadows the in-group page, so an application built
    before this fix keeps losing its sidebar until the file goes."""
    app = _app(tmp_path)
    (app / "src" / "app" / "page.tsx").write_text("// stale\n")
    result = project_root_route(_claims_root(), app)
    assert result["removedStaleRoot"] is True
    assert not (app / "src" / "app" / "page.tsx").exists()


def test_an_unclaimed_root_redirects_from_inside_the_group(tmp_path):
    """The gap this projection exists for is real when nothing claims `/`.
    Filling it inside the group keeps the one-file rule."""
    app = _app(tmp_path)
    doc = {"pages": [{"id": "PAGE-002", "route": "/sittings", "name": "S"}],
           "navigation": {"landing": "/sittings"}}
    result = project_root_route(doc, app)
    assert result["files"] == ["src/app/(dashboard)/page.tsx"]
    assert result["redirectsTo"] == "/sittings"
    body = (app / "src" / "app" / "(dashboard)" / "page.tsx").read_text()
    assert 'redirect("/sittings")' in body
    assert not (app / "src" / "app" / "page.tsx").exists()


def test_assembly_will_not_overwrite_the_page_that_owns_the_root(tmp_path):
    """Assembly runs after projection. If the in-group page were not on the
    projected list, the scaffold copy would land on top of a redirect this
    wrote and the root would render nothing."""
    from services.blueprint.assembly import PROJECTED_PATHS

    assert "src/app/(dashboard)/page.tsx" in PROJECTED_PATHS
