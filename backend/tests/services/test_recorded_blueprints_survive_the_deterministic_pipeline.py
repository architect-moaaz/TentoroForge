"""Real recorded output, replayed through everything that needs no model.

`fleet/blueprints/ats-live.json` is a complete 18-page Blueprint with composed
layouts, 8 entities and 16 workflows. It was used only by `smith/cli.py` and
`scoreboard.py`; no test touched it.

Half this pipeline is deterministic — prompt construction, shape slicing and
`$ref` inlining, A2UI-to-Forge translation, the substance floors, functional
completeness, the projections. Every bug fixed in the session that produced
this file lived in that half:

    references: ''            a slice that lost its pattern
    retry sent twice          feedback dropped on the generic prompt path
    /new judged as a record   the pattern enum could not name a create form
    Form is its own submit    a floor listing only child-node controls

Each was found by a 30-minute, ten-dollar generation. Each was reproducible in
under a second from output already on disk. Running the recorded corpus through
the deterministic half is the difference between those two loops.

This suite asserts PROPERTIES, never snapshots. A recorded Blueprint is
evidence of what the pipeline produced, not a statement that it was correct —
`/roles/new` in this very fixture is composed as a dashboard, with metric tiles
and a table and not one input field, which is the defect the floors now catch.
So the fixture is the input; the floors are the judgement.
"""
import json
import pathlib

import pytest

from services.page_kind_anatomy import page_family, page_kind_findings, route_family

_FLEET = pathlib.Path(__file__).resolve().parents[2] / "fleet" / "blueprints"


def _recorded() -> list[tuple[str, dict]]:
    out = []
    for p in sorted(_FLEET.glob("*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — a corrupt fixture is not a pipeline bug
            continue
        if isinstance(doc, dict) and doc.get("pages"):
            out.append((p.stem, doc))
    return out


RECORDED = _recorded()
pytestmark = pytest.mark.skipif(not RECORDED, reason="no recorded Blueprints on disk")


def _layouts(doc: dict) -> dict:
    return {l["page"]: l for l in doc.get("pageLayouts") or [] if isinstance(l, dict)}


@pytest.mark.parametrize("name,doc", RECORDED)
def test_every_page_pattern_is_a_pattern_the_floors_know(name, doc):
    """A pattern with no family is judged by a floor written for another kind
    of screen, or by none at all. Both were live defects."""
    unknown = sorted({
        str(p.get("pattern")) for p in doc["pages"]
        if p.get("pattern") and page_family(p["pattern"]) is None
    })
    assert unknown == [], f"{name}: patterns with no family: {unknown}"


@pytest.mark.parametrize("name,doc", RECORDED)
def test_create_and_edit_routes_resolve_to_the_form_family(name, doc):
    """Whatever pattern they were labelled with — and in this corpus they are
    all `record_workspace`, because the enum could not say `form`."""
    for page in doc["pages"]:
        route = str(page.get("route") or "")
        if route.endswith("/new") or route.endswith("/edit"):
            assert route_family(route) == "form", f"{name}: {route}"


@pytest.mark.parametrize("name,doc", RECORDED)
def test_the_floors_run_over_every_composed_page_without_crashing(name, doc):
    """The floors are consulted on real trees, so a shape they cannot read is
    a crash in the middle of a build. `page_root` returning None must produce a
    finding, never an exception."""
    layouts = _layouts(doc)
    for page in doc["pages"]:
        layout = layouts.get(page.get("id"))
        if layout is None:
            continue
        findings = page_kind_findings(page.get("pattern"), page.get("route"), layout)
        assert isinstance(findings, list)
        for f in findings:
            assert {"rule", "route", "slot", "detail"} <= set(f)


@pytest.mark.parametrize("name,doc", RECORDED)
def test_every_planned_page_was_composed(name, doc):
    """THE FUNNEL, AS A TEST. A run that plans N pages and ships fewer reports
    success today: `page_layouts` completes with per-subject failures and the
    missing routes are discovered in the browser. Recorded output makes the
    shortfall assertable.

    xfail rather than fail: this corpus predates the composition fixes and is
    evidence of the gap, not a regression to block on. Remove the marker once
    a corpus recorded after them is in place.
    """
    planned = {p["id"] for p in doc["pages"] if isinstance(p, dict) and p.get("id")}
    composed = set(_layouts(doc))
    missing = sorted(planned - composed)
    if missing:
        pytest.xfail(f"{name}: {len(missing)} of {len(planned)} pages never "
                     f"composed: {missing[:6]}")
    assert missing == []
