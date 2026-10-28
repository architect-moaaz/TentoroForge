"""A design held as the specification becomes the app as drawn.

The D3 pilot (2026-10-28) showed the old road's limit: a page writer, shown
the frames and measured against them, still re-authored every screen and
drifted. This road converts the drawing instead (`services.drawn`): each frame
becomes a React view whose markup is the drawing's and whose example content
is typed props (its contract); the journey is written down for the
requirements; the data model and the processes are generated against the
contracts; and each page is bound to them without its views being touched.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.drawn import contract as C
from services.drawn import params as P
from services.drawn.components import Library
from services.drawn.shell import read_all, read_screen
from services.drawn.tsx import Emitter, component_name, is_vector_only


def _box(x, y, w, h):
    return {"x": x, "y": y, "width": w, "height": h}


def _text(nid, chars, y=0, size=14, name="t"):
    return {"id": nid, "type": "TEXT", "name": name, "characters": chars, "absoluteBoundingBox": _box(0, y, 100, 20),
            "style": {"fontFamily": "Inter", "fontSize": size, "fontWeight": 500, "lineHeightPx": 20},
            "fills": [{"type": "SOLID", "color": {"r": 0.12, "g": 0.12, "b": 0.13}}],
            "layoutSizingHorizontal": "HUG", "layoutSizingVertical": "HUG"}


def _icon(nid):
    return {"id": nid, "type": "INSTANCE", "name": "Icon", "componentId": "C:icon", "absoluteBoundingBox": _box(0, 0, 16, 16),
            "children": [{"id": nid + "v", "type": "VECTOR", "strokes": [{"type": "SOLID", "color": {"r": 0, "g": 0, "b": 0}}]}]}


def _tag(nid, words):
    return {"id": nid, "type": "INSTANCE", "name": "DH / Tag", "componentId": "C:tag",
            "componentProperties": {"Tone": {"type": "VARIANT", "value": "Success"}},
            "layoutMode": "HORIZONTAL", "paddingLeft": 8, "paddingRight": 8, "cornerRadius": 999,
            "fills": [{"type": "SOLID", "color": {"r": 0.9, "g": 0.96, "b": 0.94}}],
            "layoutSizingHorizontal": "HUG", "layoutSizingVertical": "HUG", "absoluteBoundingBox": _box(0, 0, 60, 20),
            "children": [_text(nid + "t", words, name="Label")]}


def _screen(n, rows=3, title="Tenants"):
    """A frame drawn like D6: sidebar, a page column with a top bar, a prototype bar."""
    fid = f"{n}:1"
    return {
        "id": fid, "type": "FRAME", "name": f"A-0{n} · {title} — detail", "layoutMode": "HORIZONTAL",
        "absoluteBoundingBox": _box(0, 0, 1440, 1024), "fills": [{"type": "SOLID", "color": {"r": 0.97, "g": 0.98, "b": 0.98}}],
        "children": [
            {"id": f"{n}:2", "type": "FRAME", "name": "Sidebar 248", "layoutMode": "VERTICAL",
             "absoluteBoundingBox": _box(0, 0, 248, 1024), "layoutSizingHorizontal": "FIXED", "layoutSizingVertical": "FILL",
             "children": [_text(f"{n}:3", "Operations"), _text(f"{n}:4", "Tenants & entitlements")]},
            {"id": f"{n}:5", "type": "FRAME", "name": "Workspace", "layoutMode": "VERTICAL",
             "absoluteBoundingBox": _box(248, 0, 1192, 1024), "layoutSizingHorizontal": "FILL", "layoutSizingVertical": "FILL",
             "children": [
                 {"id": f"{n}:6", "type": "FRAME", "name": "Top utility bar 72", "layoutMode": "HORIZONTAL",
                  "absoluteBoundingBox": _box(248, 0, 1192, 72), "layoutSizingHorizontal": "FILL",
                  "children": [_text(f"{n}:7", "Search tenants")]},
                 {"id": f"{n}:8", "type": "FRAME", "name": "Content", "layoutMode": "VERTICAL", "itemSpacing": 12,
                  "paddingTop": 32, "paddingLeft": 32, "paddingRight": 32, "paddingBottom": 32,
                  "absoluteBoundingBox": _box(248, 72, 1192, 952), "layoutSizingHorizontal": "FILL",
                  "children": [_text(f"{n}:9", title, size=28, name="Title"),
                               *[_tag(f"{n}:1{i}", ["Live", "Paused", "Live"][i % 3]) for i in range(rows)],
                               _icon(f"{n}:20")]},
             ]},
            {"id": f"{n}:30", "type": "FRAME", "name": "Demo nav (prototype only)", "layoutPositioning": "ABSOLUTE",
             "absoluteBoundingBox": _box(470, 950, 500, 50), "children": [_text(f"{n}:31", "‹ Back")]},
        ],
    }


# -- 1. the drawing as React --------------------------------------------------

def test_auto_layout_becomes_flex_with_the_drawn_values():
    out = Emitter().element(_screen(1)["children"][1]["children"][1], _screen(1)["children"][1])
    for cls in ("flex flex-col", "gap-y-[12px]", "p-[32px]", "self-stretch", "text-[28px]", "font-[500]",
                "leading-[20px]", "text-[#1f1f21]", "font-['Inter']", "rounded-full"):
        assert cls in out, cls
    assert "shrink-0" in out, "a Figma child never shrinks below its content"


def test_what_markup_cannot_draw_is_exported_from_figma():
    e = Emitter()
    out = e.element(_icon("9:9"), {"layoutMode": "VERTICAL"})
    assert is_vector_only(_icon("9:9")) and '<img src="/drawn/' in out and "w-[16px]" in out
    assert list(e.assets.items.values()) == [("9:9", "svg")]


def test_a_screen_is_named_by_what_it_is():
    assert component_name("A-05 · Tenants & Entitlements — plans, seats") == "TenantsEntitlementsView"
    assert component_name("A-PB2 · Edit a price in a draft (v1.1)") == "EditAPriceInADraftView"


def test_the_shell_is_lifted_out_and_the_prototypes_bar_dropped():
    screens = read_all({str(i): _screen(i) for i in range(1, 5)})
    s = screens["1"]
    assert s.sidebar["name"] == "Sidebar 248" and s.topbar["name"] == "Top utility bar 72"
    assert s.page_root["name"] == "Workspace" and "Demo nav (prototype only)" in s.dropped
    page = Emitter(skip=s.skip).frame(s.page_root, "TenantsView")
    assert "Operations" not in page and "Search tenants" not in page and "Back" not in page
    assert "w-full min-h-screen" in page, "the page fills what the app gives it"


def test_a_component_repeated_alike_is_one_component_with_its_words_as_props():
    screens = read_all({str(i): _screen(i) for i in range(1, 4)})
    e = Emitter(skip=set().union(*(s.skip for s in screens.values())))
    lib = Library.build([s.page_root for s in screens.values()], e)
    assert [s.name for s in lib.shared.values()] == ["DhTagSuccess"]
    e.component = lib.use
    page = e.frame(screens["1"].page_root, "TenantsView")
    assert '<DhTagSuccess label={"Paused"} />' in page
    assert "props.label" in lib.files()["DhTagSuccess"]


# -- the contract ---------------------------------------------------------------

CONTRACT = {"data": [
    {"name": "tenants", "kind": "list", "label": "Tenants", "fields": [
        {"name": "name", "label": "Tenant", "type": "string"},
        {"name": "status", "label": "Status", "type": "enum", "options": ["Live", "Paused"]}]},
    {"name": "selected", "kind": "record", "label": "Tenant", "fields": [{"name": "plan", "label": "Plan", "type": "string"}]},
    {"name": "promo", "kind": "form", "label": "New code", "fields": [{"name": "code", "label": "Code", "type": "string",
                                                                    "required": True}]}],
    "actions": [{"name": "onNewTenant", "label": "New tenant", "kind": "navigate", "target": "2:1"},
                {"name": "onPause", "label": "Pause", "kind": "run", "on": "tenants"},
                {"name": "onCreateCode", "label": "Create code", "kind": "submit", "on": "promo"}]}


def test_the_props_type_is_generated_from_the_contract():
    t = C.props_type("TenantsView", CONTRACT)
    assert 'tenants: Array<{ id: string; name: string; status: "Live" | "Paused" }>;' in t
    assert "selected?: { id: string; plan: string };" in t
    assert "promo: { code: string };" in t and "onPromoChange(field: string, value: string | boolean): void;" in t
    assert "onPause(row: { id: string; name: string; status: \"Live\" | \"Paused\" }): void;" in t
    assert "onNewTenant(): void;" in t


def test_every_contract_is_put_in_front_of_the_steps_that_back_it():
    from services.blueprint.executors import build_prompt

    doc = {"application": {"name": "A"}, "drawnViews": [
        {"key": "1:1", "kind": "screen", "name": "TenantsView", "frame": "1:1", "code": "x", "contract": CONTRACT}],
        "designSources": [{"id": "FIGMA-001", "frames": [{"nodeId": "1:1", "name": "Tenants"},
                                                          {"nodeId": "2:1", "name": "New tenant"}]}]}
    user = build_prompt(doc, "data_model")[1]
    assert "THE DESIGN IS ALREADY BUILT AS REACT VIEWS" in user
    assert "list `tenants` “Tenants”: name:string, status:enum[Live|Paused]" in user
    assert "action `onNewTenant` “New tenant” (navigate → New tenant)" in user
    assert "THE DESIGN IS ALREADY BUILT" not in build_prompt({**doc, "drawnViews": []}, "data_model")[1]


# -- the example content as props ----------------------------------------------

STATIC = ('export default function TenantsView() {\n  return (\n    <div className="flex flex-col">\n'
          '      <p className="text-[28px]">Tenants</p>\n      <div className="flex flex-row"><p className="text-[14px]">'
          'MedStaff</p></div>\n    </div>\n  );\n}\n')
GOOD = ('"use client";\nimport type * as React from "react";\n\nexport default function TenantsView(props: TenantsViewProps) {\n'
        '  return (<div className="flex flex-col"><p className="text-[28px]">Tenants</p>'
        '{props.tenants.map((row) => (<div key={row.id} className="flex flex-row" onClick={() => props.onOpen(row)}>'
        '<p className="text-[14px]">{row.name}</p></div>))}</div>);\n}\n')
SMALL = {"data": [{"name": "tenants", "kind": "list", "label": "Tenants",
                   "fields": [{"name": "name", "label": "Name", "type": "string"}]}],
         "actions": [{"name": "onOpen", "label": "Open", "kind": "navigate", "on": "tenants"}]}


def test_a_view_that_changes_the_drawing_is_refused():
    assert P.check(STATIC, GOOD, SMALL, "TenantsView") == []
    restyled = GOOD.replace('className="text-[14px]"', 'className="text-sm"')
    assert any("markup was changed" in p for p in P.check(STATIC, restyled, SMALL, "TenantsView"))
    assert any("classNames the drawing does not have" in p for p in P.check(STATIC, restyled, SMALL, "TenantsView"))
    assert any("never reads: onOpen" in p for p in P.check(STATIC, GOOD.replace("props.onOpen(row)", "0"), SMALL,
                                                           "TenantsView"))


def test_a_refused_view_is_asked_again_and_the_type_is_written_for_it():
    replies = iter([json.dumps({"contract": SMALL, "sample_json": "{}", "code": GOOD.replace("text-[14px]", "text-sm")}),
                    json.dumps({"contract": SMALL, "sample_json": json.dumps({"tenants": [{"id": "1", "name": "MedStaff"}]}),
                                "code": GOOD})])
    asked = []

    def client(*, system, user, schema, **_kw):
        asked.append(user)
        return next(replies)

    out = P.parameterise(client, "TenantsView", STATIC, heading="Tenants", image=None, links=[], components={})
    assert out["rounds"] == 2 and "markup was changed" in asked[1]
    assert "export type TenantsViewProps" in out["code"] and out["code"].startswith('"use client";')
    assert out["sample"]["tenants"][0]["name"] == "MedStaff"


# -- 2. the journey, written down ------------------------------------------------

def test_chapter_headings_on_the_canvas_are_the_frames_groups():
    from services.figma.reference import _screen_nodes

    section = {"id": "6:1", "type": "SECTION", "name": "Section 1", "children": [
        {"id": "6:2", "type": "TEXT", "characters": "1 · Operations & tenants", "absoluteBoundingBox": _box(0, 0, 300, 40)},
        {"id": "6:3", "type": "FRAME", "name": "A-01", "absoluteBoundingBox": _box(0, 80, 1440, 1024)},
        {"id": "6:4", "type": "TEXT", "characters": "5 · Promotions", "absoluteBoundingBox": _box(0, 1200, 300, 40)},
        {"id": "6:5", "type": "FRAME", "name": "A-11", "absoluteBoundingBox": _box(1500, 1280, 1440, 1024)}]}
    groups = {node["name"]: sec for _c, sec, node in _screen_nodes({"document": section}) if node.get("type") == "FRAME"}
    assert groups == {"A-01": "Section 1 / 1 · Operations & tenants", "A-11": "Section 1 / 5 · Promotions"}


def test_the_flow_says_what_each_screen_shows_does_and_states(monkeypatch):
    from services.drawn import convert, flow

    monkeypatch.setattr(convert, "prepare", lambda doc, out: convert.Prepared(static={
        "1:1": '<p className="x">Codes above 30% or longer than six months need finance approval first</p>'}))
    doc = {"designSources": [{"id": "FIGMA-001", "frames": [
        {"nodeId": "1:1", "name": "A-12 · Create a promo code", "group": "5 · Promotions"},
        {"nodeId": "2:1", "name": "A-11 · Promo codes"}]}],
        "drawnViews": [{"key": "1:1", "kind": "screen", "name": "CreateAPromoCodeView", "frame": "1:1",
                        "contract": {"data": [CONTRACT["data"][2]],
                                     "actions": [{"name": "onCreateCode", "label": "Create code", "kind": "submit",
                                                  "on": "promo"},
                                                 {"name": "onCancel", "label": "Cancel", "kind": "navigate",
                                                  "target": "2:1"}]}}]}
    text = flow.document(doc, "/nowhere")
    assert "## 5 · Promotions" in text and "### A-12 · Create a promo code" in text
    assert "“Create code” submits it to promo." in text and "“Cancel” goes to A-11 · Promo codes." in text
    assert "need finance approval first" in text


# -- 3/4. generated against the contract, bound without touching the view --------

def _bound_doc():
    return {"application": {"name": "Admin"},
            "pages": [{"id": "PAGE-001", "name": "Tenants", "route": "/tenants", "figmaFrame": "1:1",
                       "frames": [{"frame": "1:2", "as": "dialog", "label": "Add override"}]},
                      {"id": "PAGE-002", "name": "New tenant", "route": "/tenants/new", "figmaFrame": "2:1"}],
            "drawnViews": [
                {"key": "1:1", "kind": "screen", "name": "TenantsView", "frame": "1:1",
                 "code": 'import DhTagSuccess from "./DhTagSuccess";\nexport default function TenantsView() {}',
                 "contract": {"data": CONTRACT["data"][:1], "actions": CONTRACT["actions"][:2]}, "sample": {}},
                {"key": "1:2", "kind": "screen", "name": "AddOverrideView", "frame": "1:2", "code": "x",
                 "contract": {"data": [], "actions": []}},
                {"key": "component:DhTagSuccess", "kind": "component", "name": "DhTagSuccess", "code": "tag"},
                {"key": "component:Unused", "kind": "component", "name": "Unused", "code": "u"}]}


def test_a_drawn_page_is_its_views_and_their_components_as_parts():
    from services.drawn import binder

    doc = _bound_doc()
    page = doc["pages"][0]
    assert [a for a, _l, _r in binder.views_of(doc, page)] == ["main", "dialog"]
    assert set(binder.parts_of(doc, page)) == {"TenantsView", "AddOverrideView", "DhTagSuccess"}
    prompt = binder.user_prompt(doc, page)
    assert "`onNewTenant` “New tenant”: navigate → page `/tenants/new`" in prompt
    assert "its dialog “Add override”" in prompt and "export type TenantsViewProps" in prompt


def test_the_page_around_the_drawing_draws_nothing(monkeypatch):
    from services.blueprint import ui_engineer
    from services.drawn import binder

    doc = _bound_doc()
    page = doc["pages"][0]
    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: [])
    monkeypatch.setattr(ui_engineer, "system_prompt", lambda doc: "s")
    good_view = ('"use client";\nimport TenantsView from "./parts/TenantsView";\nimport AddOverrideView from '
                 '"./parts/AddOverrideView";\nexport default function View(p: any) { return p.open ? '
                 '<AddOverrideView /> : <TenantsView tenants={p.tenants} onNewTenant={() => go("/tenants/new")} '
                 'onPause={(row) => pause(row)} />; }')
    drawing_view = good_view.replace("<TenantsView", '<div className="p-4"><TenantsView').replace(" />; }", " /></div>; }", 1)
    replies = iter([{"view": drawing_view}, {"view": good_view, "seed": json.dumps({"Tenant": [{"name": "MedStaff"}]})}])

    def client(*, system, user, schema):
        r = next(replies)
        return json.dumps({"rationale": "r", "load": "export async function load() { return {}; }",
                           "view": r["view"], "needs_fields": [], "needs_workflows": [], "seed": r.get("seed", "{}")})

    body, _ = binder.bind(doc, page, Path("/tmp"), client)
    assert body["parts"] == binder.parts_of(doc, page), "the views are the drawing, as converted"
    assert all(code.startswith("// @ts-nocheck") for code in body["parts"].values())
    assert body["seed"] == {"Tenant": [{"name": "MedStaff"}]}


def test_what_the_views_need_and_nothing_backs_is_asked_for(monkeypatch):
    from services.blueprint import ui_engineer
    from services.drawn import binder

    monkeypatch.setattr(ui_engineer, "system_prompt", lambda doc: "s")
    doc = _bound_doc()

    def needs(fields, flows):
        return lambda **_k: json.dumps({"rationale": "", "load": "", "view": "", "seed": "{}",
                                        "needs_fields": fields, "needs_workflows": flows})

    with pytest.raises(binder.NeedsFields, match="Tenant.seatsUsed"):
        binder.bind(doc, doc["pages"][0], Path("/tmp"),
                    needs([{"entity": "Tenant", "name": "seatsUsed", "type": "integer", "label": "Seats used"}], []))
    with pytest.raises(ui_engineer.NeedsWorkflow, match="pause a tenant"):
        binder.bind(doc, doc["pages"][0], Path("/tmp"), needs([], ["pause a tenant"]))


def test_the_drawn_frame_is_the_apps_frame_with_its_menu_led_to_the_pages(tmp_path):
    from services.drawn.project import DEFAULT_WRAPPER, project_drawn

    doc = _bound_doc()
    doc["designSources"] = [{"id": "FIGMA-001", "frames": [
        {"nodeId": "1:1", "links": [{"to": "2:1", "kind": "navigate", "via": "Onboarding"}]}]}]
    doc["drawnViews"].append({"key": "shell", "kind": "shell", "name": "DrawnShell", "frame": "1:1",
                              "code": 'import DhTagSuccess from "./DhTagSuccess";\nexport default function DrawnShell() {}',
                              "contract": {"data": [{"name": "nav", "kind": "list", "fields": []}],
                                           "actions": [{"name": "onNav", "label": "", "kind": "navigate", "on": "nav"}]},
                              "sample": {"nav": [{"id": "1", "label": "Tenants", "active": True},
                                                 {"id": "2", "label": "Onboarding", "active": False}]}})
    out = project_drawn(doc, tmp_path, tmp_path / "app")
    wrapper = (tmp_path / "app/src/components/DrawnShell.tsx").read_text()
    assert out["shell"] and "DRAWN_SHELL = true" in wrapper
    assert '"href": "/tenants"' in wrapper and '"href": "/tenants/new"' in wrapper
    assert "onNav={(row) => router.push(row.href)}" in wrapper
    assert (tmp_path / "app/src/components/drawn/DhTagSuccess.tsx").is_file()
    doc["drawnViews"] = [v for v in doc["drawnViews"] if v["kind"] != "shell"]
    project_drawn(doc, tmp_path, tmp_path / "app")
    assert (tmp_path / "app/src/components/DrawnShell.tsx").read_text() == DEFAULT_WRAPPER


def test_the_layout_shows_the_drawn_frame_when_there_is_one():
    layout = (Path(__file__).resolve().parents[3] / "templates/app-foundation/src/app/(dashboard)/layout.tsx").read_text()
    assert 'import DrawnShell, { DRAWN_SHELL } from "@/components/DrawnShell";' in layout
    assert "<DrawnShell controls={cluster}>{children}</DrawnShell>" in layout
    default = Path(__file__).resolve().parents[3] / "templates/app-foundation/src/components/DrawnShell.tsx"
    assert "DRAWN_SHELL = false" in default.read_text()


def test_the_build_converts_the_frames_first_and_the_requirements_read_the_journey():
    from services.blueprint.orchestrator import DAG, subjects_for
    from services.smith.smith import domain_nodes

    assert "drawn_flow" in DAG["requirements"].depends_on and DAG["drawn_views"].fanout == "drawn_frames"
    assert domain_nodes()[:2] == ["drawn_views", "drawn_flow"]
    doc = {"designSources": [{"id": "FIGMA-001", "treatAs": "specification", "frames": [{"nodeId": "1:1"}]},
                             {"id": "FIGMA-002", "treatAs": "evidence", "frames": [{"nodeId": "1:1"}]}]}
    assert subjects_for(DAG["drawn_views"], doc) == ["1:1", "shell", "components"]
    assert subjects_for(DAG["drawn_views"], {"designSources": []}) == []


def test_the_drawings_examples_become_the_first_records(tmp_path):
    from services.blueprint.service import BlueprintService
    from services.drawn.seed import record

    svc = BlueprintService.create(output_dir=str(tmp_path), app_id="s", name="S", domain="unknown")
    svc.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Tenant", "table": "tenants", "status": "PROPOSED",
                                     "fields": [{"name": "name", "type": "string"}, {"name": "seats", "type": "integer"}]}]}
    svc.save()
    (tmp_path / "app").mkdir()
    said = record(svc, {"Tenant": [{"id": "1", "name": "MedStaff", "seats": "7", "nope": 1}]}, page_id="PAGE-001",
                  app_root=str(tmp_path / "app"))
    assert said == ["Tenant: 1 drawn row(s)"]
    files = list((tmp_path / "app/src/db/imports").glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text())
    assert payload["table"] == "tenants" and payload["rows"] == [{"name": "MedStaff", "seats": 7}]


def test_the_shell_is_drawn_with_its_sidebar_and_top_bar(tmp_path, monkeypatch):
    from services.drawn import convert
    from services.figma import store
    from services.figma.reference import ScreenRef

    frames = [{"nodeId": f"{i}:1", "name": f"A-0{i} · Tenants"} for i in range(1, 4)]
    doc = {"designSources": [{"id": "FIGMA-001", "treatAs": "specification", "fileKey": "K", "frames": frames}]}
    monkeypatch.setattr(store, "load_screen", lambda sid, nid, out: ScreenRef(
        node_id=nid, name="s", width=1440, height=1024,
        structure={"source": "rest_node_document", "document": _screen(int(nid.split(":")[0]))}))
    prepared = convert._prepare(doc, tmp_path)
    assert "Operations" in prepared.shell_markup and "Search tenants" in prepared.shell_markup
    assert "Back" not in prepared.shell_markup, "the prototype's bar stays out of the shell too"
    assert "{props.children}" in prepared.shell_markup
    page = prepared.static["1:1"]
    assert "Operations" not in page and "Search tenants" not in page


def test_a_heading_every_frame_shares_does_not_name_the_screens():
    from services.blueprint.page_planner import frame_slots

    frames = [{"nodeId": f"{i}:1", "name": n, "shows": "Ditans Health"} for i, n in
              enumerate(["A-05 · Tenants", "A-11 · Promo codes", "A-12 · Create a promo code"], 1)]
    slots = frame_slots(frames)
    assert [s["name"] for s in slots] == ["A-05 · Tenants", "A-11 · Promo codes", "A-12 · Create a promo code"]
    assert all("shows" not in s for s in slots)


def test_a_type_is_not_markup_and_a_drawn_action_must_do_something():
    from services.drawn import binder

    doc = _bound_doc()
    page = doc["pages"][0]
    view = ('"use client";\nimport TenantsView from "./parts/TenantsView";\nimport AddOverrideView from "./parts/AddOverrideView";\n'
            'type P = Awaited<typeof load>;\nexport default function V(p: P) { return <div><TenantsView '
            'onNewTenant={() => router.push("/x")} onPause={(row) => run(row)} /></div>; }')
    assert binder.check(view, page, doc) == []
    lazy = view.replace("onPause={(row) => run(row)}", "onPause={() => {}}")
    assert any("`onPause`" in p and "does nothing" in p for p in binder.check(lazy, page, doc))
    styled = view.replace("<div>", '<div className="p-4">')
    assert any("draws markup of its own (<div>)" in p for p in binder.check(styled, page, doc))
