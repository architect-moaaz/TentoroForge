"""QA D-04: a build that plans N pages and composes fewer must REPORT the pages
it did not build, not claim success. page_funnel is that report."""
import json
from pathlib import Path

from services.blueprint.assembly import page_funnel


def _app(tmp_path: Path, served_routes: list[str]) -> Path:
    schemas = tmp_path / "src" / "schemas"
    schemas.mkdir(parents=True)
    # The generated registry maps "<route>": () => import(...); page_funnel reads it.
    body = "\n".join(f'  "{r}": () => import("./x"),' for r in served_routes)
    (schemas / "registry.ts").write_text(
        "export const registry = {\n" + body + "\n};\n", "utf-8")
    return tmp_path


def _doc(routes: list[str]) -> dict:
    return {"pages": [{"id": f"PAGE-{i}", "route": r} for i, r in enumerate(routes)]}


def test_a_page_that_failed_composition_is_reported_as_missing(tmp_path):
    # Planned 3, the composer shipped 2 — the third failed and is not in the registry.
    root = _app(tmp_path, served_routes=["/tasks", "/tasks/new"])
    funnel = page_funnel(_doc(["/tasks", "/tasks/new", "/tasks/[id]"]), root)
    assert funnel["planned"] == 3
    assert funnel["served"] == 2
    assert funnel["missing"] == ["/tasks/[id]"]
    assert funnel["status"] == "short"


def test_a_complete_build_reports_nothing_missing(tmp_path):
    root = _app(tmp_path, served_routes=["/tasks", "/tasks/new"])
    funnel = page_funnel(_doc(["/tasks", "/tasks/new"]), root)
    assert funnel["missing"] == [] and funnel["status"] == "complete"
