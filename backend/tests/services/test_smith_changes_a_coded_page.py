"""Smith changes a page written as React by rewriting its code — h7gmi93x.

"Add an age × gender heatmap to the dashboard" laid a Heatmap node into the
dashboard's `pageLayouts` tree. The dashboard renders from its `pageCode`,
so nothing changed on screen, the rebuild had no page to write, and Smith
said the screen did not show what was asked. And "age group" could not be
said at all: a query grouped a number only by its every distinct value.

Held here: a coded page is changed through the analytics agent (what it
counts) and the UI engineer (the code), as ONE versioned change; a number
dimension can be grouped into ranges, checked like every other query rule.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

from services.blueprint import app_sdk, ui_engineer
from services.blueprint.agent_contract import ArtifactProposal
from services.blueprint.service import BlueprintService
from services.smith import compose
from services.smith.compose import ComposeError, recode_page

VIEW = '"use client";\nexport default function View() { return <div className="p-6" />; }\n'
LOAD = 'import type { PageContext } from "@/sdk/server";\nexport async function load(ctx: PageContext) { return {}; }\n'
AGES = [{"label": "1-17", "from": 1, "to": 18}, {"label": "18-30", "from": 18, "to": 31},
        {"label": "31-60", "from": 31, "to": 61}, {"label": "61+", "from": 61}]
HEATMAP = {"kind": "chart", "label": "Age Group × Gender Heatmap", "page": "PAGE-001",
           "chart": {"mark": "heatmap"},
           "dataSource": {"op": "query", "entity": "ENTITY-001",
                          "measures": [{"key": "count", "aggregation": "count", "label": "Records"}],
                          "dimensions": [{"field": "age", "ranges": AGES}, {"field": "gender"}]}}


def _svc(tmp_path: Path) -> BlueprintService:
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Demographics", domain="ops")
    svc.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Record", "table": "records", "fields": [
        {"name": "fullName", "type": "string"}, {"name": "age", "type": "integer"},
        {"name": "gender", "type": "enum", "enumValues": ["Male", "Female"]}]}], "relationships": []}
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "Dashboard", "route": "/dashboard", "purpose": "x",
                         "data": {"primaryEntity": "ENTITY-001"}}]
    svc.doc["pageCode"] = [{"page": "PAGE-001", "rationale": "first", "load": LOAD, "view": VIEW}]
    svc.save()
    return svc


class _Run:
    """The analytics agent, answering with what it is given, recording its briefs."""
    def __init__(self, *answers):
        self.answers, self.specs = list(answers), []

    def __call__(self, spec):
        self.specs.append(spec)
        props = self.answers.pop(0) if self.answers else []
        return type("R", (), {"proposals": [ArtifactProposal(section="widgets", natural_key=w["label"], body=dict(w))
                                            for w in props]})()


@pytest.fixture
def quiet(monkeypatch):
    """No compiler, no files: what the page becomes is what `compose_page` returns."""
    monkeypatch.setattr(ui_engineer, "ensure_sdk", lambda doc, root: None)
    monkeypatch.setattr(app_sdk, "project_code_pages", lambda doc, root: [])
    written = {}

    def compose(view):
        def _compose(doc, page, root, client, **kw):
            written.update(kw, doc=doc)
            return {"page": page["id"], "rationale": "rewrite", "load": LOAD, "view": view}, []
        monkeypatch.setattr(ui_engineer, "compose_page", _compose)
        return written
    return compose


def test_a_heatmap_on_a_coded_page_is_a_widget_and_the_code_that_draws_it(tmp_path, quiet):
    svc = _svc(tmp_path)
    before = svc.doc["version"]
    keys_after = app_sdk.widget_keys({"widgets": [{**HEATMAP, "id": "W"}]})
    written = quiet(VIEW.replace('className="p-6" />', f'className="p-6">{{widgets.{keys_after["W"]}.id}}</div>'))
    run = _Run([HEATMAP])
    out = recode_page(svc, "/dashboard", app_root=str(tmp_path / "app"),
                      request="add the heatmap: age group × gender", wanted=["age group × gender heatmap"],
                      executor=run, client=object())

    assert out["applied"] and out["missing"] == []
    assert run.specs[0].node == "analytics" and "age group × gender" in run.specs[0].brief
    # the page was written against a document that already has the widget
    assert any(w.get("label") == HEATMAP["label"] for w in written["doc"]["widgets"])
    assert "widgets." in written["brief"]
    heat = next(w for w in svc.doc["widgets"] if w["label"] == HEATMAP["label"])
    assert heat["dataSource"]["dimensions"][0]["ranges"] == AGES
    # the handle the page was compiled against is the one stored on the row
    assert heat["key"] == keys_after["W"]
    assert next(w for w in written["doc"]["widgets"] if w["label"] == HEATMAP["label"])["key"] == heat["key"]
    assert svc.doc["pageCode"][0]["rationale"] == "rewrite"
    # ONE change: one version, with the person's words on it — so one undo
    assert svc.doc["version"] == before + 1
    assert svc.doc["changeHistory"][-1]["userRequest"] == "add the heatmap: age group × gender"


def test_a_change_with_nothing_to_count_is_still_a_version(tmp_path, quiet):
    """`apply_change` versions only what reports artifacts; a pageCode row
    reports none, so a code-only change had no version and no undo."""
    svc = _svc(tmp_path)
    before = svc.doc["version"]
    quiet(VIEW.replace("p-6", "p-8"))
    out = recode_page(svc, "/dashboard", app_root=str(tmp_path / "app"),
                      request="more padding", executor=_Run([]), client=object())
    assert out["applied"] and out["widgets"] == []
    assert svc.doc["version"] == before + 1
    assert "p-8" in svc.doc["pageCode"][0]["view"]


def test_a_widget_the_new_code_does_not_draw_is_reported_missing(tmp_path, quiet):
    svc = _svc(tmp_path)
    quiet(VIEW)
    out = recode_page(svc, "/dashboard", app_root=str(tmp_path / "app"),
                      request="add the heatmap", wanted=["heatmap"], executor=_Run([HEATMAP]), client=object())
    assert out["missing"] == [HEATMAP["label"]]


def test_code_that_never_compiles_changes_nothing(tmp_path, monkeypatch, quiet):
    svc = _svc(tmp_path)
    quiet(VIEW)

    def refuse(*a, **k):
        raise ui_engineer.CompileError("PAGE-001: still does not compile")
    monkeypatch.setattr(ui_engineer, "compose_page", refuse)
    before = svc.snapshot()
    with pytest.raises(ComposeError, match="did not compile"):
        recode_page(svc, "/dashboard", app_root=str(tmp_path / "app"),
                    request="add the heatmap", wanted=["heatmap"], executor=_Run([HEATMAP]), client=object())
    assert svc.doc == before


def test_a_refused_chart_is_asked_again_then_refused(tmp_path, quiet):
    svc = _svc(tmp_path)
    quiet(VIEW)
    bad = {**HEATMAP, "dataSource": {**HEATMAP["dataSource"], "dimensions": [
        {"field": "fullName", "ranges": [{"from": 30, "to": 18}]}, {"field": "gender"}]}}
    run = _Run([bad], [bad])
    with pytest.raises(ComposeError):
        recode_page(svc, "/dashboard", app_root=str(tmp_path / "app"),
                    request="add the heatmap", wanted=["heatmap"], executor=run, client=object())
    assert len(run.specs) == 2 and "not a number" in (run.specs[1].feedback or "")
    assert not svc.doc.get("widgets")


def test_smith_routes_a_coded_page_to_its_code_and_a_laid_out_one_to_the_composer(tmp_path, monkeypatch):
    svc = _svc(tmp_path)
    svc.doc["pages"].append({"id": "PAGE-002", "name": "Plain", "route": "/plain", "purpose": "y"})
    svc.save()
    monkeypatch.setattr(compose, "prepare_capabilities", lambda *a, **k: {"declared": [], "created": []})
    calls = []
    monkeypatch.setattr(compose, "recode_page", lambda svc, route, **k: calls.append(("code", route)) or
                        {"applied": True, "committed": [], "version": 2, "reason": "", "missing": [], "widgets": []})
    monkeypatch.setattr(compose, "compose_route", lambda svc, route, **k: calls.append(("layout", route)) or
                        type("C", (), {"applied": True, "committed": [], "version": 2, "reason": ""})())
    compose.run(str(tmp_path), "compose_route", route="/dashboard", request="add a heatmap")
    compose.run(str(tmp_path), "compose_route", route="/plain", request="add a heatmap")
    # In an app whose pages are code, a page with none yet is written as code
    # too (UAT: "/" went to the layout composer for seven minutes).
    assert calls == [("code", "/dashboard"), ("code", "/plain")]
    # An app of layouts still goes to the composer.
    calls.clear()
    from services.blueprint.service import BlueprintService
    s = BlueprintService.load(output_dir=tmp_path)
    s.doc["pageCode"] = []
    s.save()
    compose.run(str(tmp_path), "compose_route", route="/plain", request="add a heatmap")
    assert calls == [("layout", "/plain")]


# --- a number grouped into ranges --------------------------------------------

def test_ranges_are_checked_like_every_other_query_rule():
    from services.blueprint.verification import range_findings

    age = {"name": "age", "type": "integer"}
    assert range_findings({"field": "age", "ranges": AGES}, age) == []
    assert any("not a number" in f for f in range_findings({"field": "n", "ranges": AGES}, {"type": "string"}))
    assert any("below `to`" in f for f in range_findings({"ranges": [{"from": 30, "to": 18}]}, age))
    assert any("overlap" in f for f in range_findings({"ranges": [{"from": 1, "to": 30}, {"from": 20, "to": 40}]}, age))
    assert any("neither" in f for f in range_findings({"ranges": [{"label": "x"}]}, age))
    assert any("both a date bucket" in f for f in range_findings({"bucket": "month", "ranges": AGES}, age))


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_the_data_engine_groups_a_number_into_its_ranges():
    """The SHIPPED data-engine.ts against a fake db that really groups."""
    script = Path(__file__).resolve().parents[2] / "templates/runtime/__tests__/run-query-tests.sh"
    proc = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-1500:]
    assert "orders per band" in proc.stdout


def test_a_form_page_is_not_filled_with_charts(tmp_path, quiet):
    """036farqu: "Open A Dispute page has nothing in it" gave a dispute FORM
    three dashboard charts. The analytics rule is that a form carries none,
    so on a form the analytics agent is not asked unless charts were named."""
    svc = _svc(tmp_path)
    svc.doc["pages"][0]["pattern"] = "form"
    svc.save()
    quiet(VIEW.replace("p-6", "p-8"))
    run = _Run([HEATMAP])
    out = recode_page(svc, "/dashboard", app_root=str(tmp_path / "app"),
                      request="this page has nothing in it", executor=run, client=object())
    assert out["applied"] and run.specs == [] and not svc.doc.get("widgets")
    # A chart asked for by name on a form is still honoured.
    run = _Run([HEATMAP])
    recode_page(svc, "/dashboard", app_root=str(tmp_path / "app"),
                request="add a heatmap", wanted=["age × gender heatmap"], executor=run, client=object())
    assert len(run.specs) == 1


def test_the_analytics_agent_is_told_what_kind_of_page_it_is(tmp_path, quiet):
    svc = _svc(tmp_path)
    svc.doc["pages"][0]["pattern"] = "dashboard"
    svc.save()
    quiet(VIEW)
    run = _Run([])
    recode_page(svc, "/dashboard", app_root=str(tmp_path / "app"),
                request="it looks empty", executor=run, client=object())
    assert "`dashboard` page" in run.specs[0].brief and "never add a widget to fill space" in run.specs[0].brief



def test_a_change_that_names_no_chart_does_not_design_charts(tmp_path):
    """0l133sp2: "change the Discover page heading" came back as four new KPI
    tiles, or — when the analytics author proposed another page's charts — as
    a refused edit after four minutes."""
    from services.smith import compose
    src = __import__("inspect").getsource(compose.recode_page)
    assert "if not charted and (wanted or has_widgets or not numbers_page):" in src


def test_a_field_to_show_is_not_handed_to_the_chart_author(tmp_path, quiet):
    """UAT replay 3: "show the product name on Discover" came back as six KPI
    tiles. A widget ask that IS a field's name is the page code's to show."""
    svc = _svc(tmp_path)
    quiet(VIEW.replace("p-6", "p-8"))
    run = _Run([HEATMAP])
    out = recode_page(svc, "/dashboard", app_root=str(tmp_path / "app"),
                      request="show the name more prominently", wanted=["fullName"],
                      executor=run, client=object())
    assert out["applied"] and run.specs == [] and not svc.doc.get("widgets")


def test_a_one_record_page_is_not_reported_as_missing_from_the_menu(tmp_path):
    from services.smith.compose import _where
    svc = _svc(tmp_path)
    svc.doc["pages"].append({"id": "PAGE-002", "name": "Record Details", "route": "/dashboard/[id]",
                             "purpose": "x", "data": {"primaryEntity": "ENTITY-001"}})
    said = _where(svc, "/dashboard/[id]")
    assert "not in the menu" not in said and "one record's page" in said and "Dashboard" in said
