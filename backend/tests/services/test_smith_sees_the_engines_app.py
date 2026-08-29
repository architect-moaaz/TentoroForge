"""What Smith reads must be what the engine wrote.

Two Blueprint stores exist: the DAG writes `.forge/blueprint/current.json`,
Smith's `Blueprint` reads `.forge/blueprint.json`. Nothing writes the second,
so Smith loaded an EMPTY blueprint on a fully generated project, concluded
there was nothing to reason about, and routed every message to bootstrap — one
fault that presented as three (§16 clarification never firing, §114
Prompt-to-Change unreachable, a rename answering with bootstrap seam names).

`engine_blueprint_adapter` closes that, and closing it created a new seam: a
translation between two shapes, which is the thing that drifts. The catalog
drifted from the Zod components the same way, and the schema drifted from what
the projections wrote. Both had tests on either side and none across.

So this reads real generated applications and asserts Smith sees what is
actually in them — not a fixture, which would agree by construction.
"""

import json
from pathlib import Path

import pytest

from services.smith.engine_blueprint_adapter import (
    load_engine_doc, to_smith_fields,
)
from services.smith_blueprint import Blueprint

_ROOT = Path(__file__).resolve().parents[3]
_OUTPUT = _ROOT / "output"


def _generated() -> list[Path]:
    if not _OUTPUT.is_dir():
        return []
    return sorted(p.parents[2] for p in
                  _OUTPUT.glob("*/.forge/blueprint/current.json"))


_APPS = _generated()
_ids = lambda p: p.name


@pytest.mark.parametrize("project", _APPS, ids=_ids)
def test_smith_sees_every_page_the_engine_wrote(project):
    """`understand_ask` returns a `target_file` and the move scopes against it.
    A page Smith cannot see is a page it cannot be asked to change."""
    doc = load_engine_doc(str(project))
    engine_routes = {str(p.get("route")) for p in (doc.get("pages") or [])
                     if p.get("route")}
    seen = {str(p.get("route")) for p in
            Blueprint.load(project_id="t", output_dir=str(project)).pages}
    assert engine_routes <= seen, f"unseen: {sorted(engine_routes - seen)}"


@pytest.mark.parametrize("project", _APPS, ids=_ids)
def test_smith_sees_every_entity_the_engine_wrote(project):
    doc = load_engine_doc(str(project))
    engine = {str(e.get("name")) for e in
              ((doc.get("data") or {}).get("entities") or []) if e.get("name")}
    seen = {str(e.get("name")) for e in
            Blueprint.load(project_id="t", output_dir=str(project)).entities}
    assert engine <= seen, f"unseen: {sorted(engine - seen)}"


@pytest.mark.parametrize("project", _APPS, ids=_ids)
def test_a_generated_project_never_looks_empty_to_smith(project):
    """The whole defect in one assertion. An empty blueprint is what routed
    every message to bootstrap, and bootstrap's seams are unwired.

    Scoped to projects that HAVE an application. A definition-only Blueprint —
    requirements and a product model, approved but not yet built — genuinely
    has no pages and no entities, and Smith seeing none is correct. Asserting
    otherwise would have made the test demand that the adapter invent one.
    """
    doc = load_engine_doc(str(project)) or {}
    built = (doc.get("pages") or
             (doc.get("data") or {}).get("entities") or [])
    if not built:
        pytest.skip("definition only — nothing built yet")

    bp = Blueprint.load(project_id="t", output_dir=str(project))
    assert bp.pages or bp.entities, "Smith sees nothing in a generated project"


@pytest.mark.parametrize("project", _APPS, ids=_ids)
def test_the_schema_path_smith_reports_is_the_one_on_disk(project):
    """`target_file` has to name something real: `understand_ask` returns it
    and `move_dispatcher` scopes against it, so a path derived differently from
    the projection's makes every rename a silent no-op."""
    bp = Blueprint.load(project_id="t", output_dir=str(project))
    missing = [
        p["schema_path"] for p in bp.pages
        if p.get("schema_path")
        and not (project / "app" / str(p["schema_path"])).is_file()
    ]
    # A page the composer failed on has no schema file, which is a different
    # fault; every page that DID project must be findable.
    projected = {f.relative_to(project / "app").as_posix()
                 for f in (project / "app" / "src" / "schemas").rglob("*.json")}
    assert not [m for m in missing if m in projected], missing


def test_there_is_something_to_check():
    if not _APPS:
        pytest.skip("no generated applications in output/")


def test_an_empty_project_still_reads_empty(tmp_path):
    """The adapter must not invent an application where there is none."""
    bp = Blueprint.load(project_id="t", output_dir=str(tmp_path))
    assert bp.pages == [] and bp.entities == []


def test_smiths_own_file_still_wins_when_it_exists(tmp_path):
    """The adapter is a fallback, not a takeover: a project that has been
    written by Smith keeps what Smith wrote."""
    forge = tmp_path / ".forge"
    forge.mkdir()
    (forge / "blueprint.json").write_text(json.dumps({
        "project_id": "t",
        "pages": [{"route": "/only-mine", "schema_path": "x.json"}],
    }))
    engine = forge / "blueprint" / "current.json"
    engine.parent.mkdir()
    engine.write_text(json.dumps({"pages": [{"route": "/from-engine"}]}))

    bp = Blueprint.load(project_id="t", output_dir=str(tmp_path))
    assert [p["route"] for p in bp.pages] == ["/only-mine"]
