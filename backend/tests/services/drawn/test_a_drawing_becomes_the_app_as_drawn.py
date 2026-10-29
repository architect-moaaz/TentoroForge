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
    assert "selected: { id: string; plan: string };" in t          # a record the drawing shows is always given
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

STATIC = """export default function TenantsView() {
  return (
    <div className="flex flex-col">
      <p className="text-[28px]">Tenants</p>
      <div className="flex flex-col gap-y-[8px]" data-layer="Rows">
        <div className="flex flex-row bg-[#ffffff]" data-layer="Row">
          <p className="text-[14px]">MedStaff</p>
          <div className="w-[60px] shrink-0"><DhTagSuccess label={"Live"} /></div>
        </div>
        <div className="flex flex-row bg-[#ffffff]" data-layer="Row">
          <p className="text-[14px]">CarePoint</p>
          <div className="w-[60px] shrink-0"><DhTagWarning label={"Paused"} /></div>
        </div>
        <div className="flex flex-row bg-[#ffffff]" data-layer="Row">
          <p className="text-[14px]">Nile Health</p>
          <div className="w-[60px] shrink-0"><DhTagSuccess label={"Live"} /></div>
        </div>
      </div>
      <div className="flex flex-row pl-[14px] h-[46px] border-[1px]" data-layer="Input">
        <p className="flex-1 text-[14px]">GULFNURSE30</p>
      </div>
      <div className="flex flex-row gap-x-[8px]" data-layer="Chips">
        <div className="px-[12px] bg-[#eaf0ff] border-[1px] border-[#0443fa] rounded-full">
          <p className="text-[12px] text-[#0443fa]">Egypt</p>
        </div>
        <div className="px-[12px] bg-[#f7fafb] rounded-full">
          <p className="text-[12px] text-[#1e1e20]">Jordan</p>
        </div>
      </div>
      <div className="w-[200px] shrink-0 h-[48px]"><DhButtonPrimary label={"Create code"} /></div>
    </div>
  );
}
"""
SMALL = {"data": [{"name": "tenants", "kind": "list", "label": "Tenants", "fields": [
                       {"name": "name", "label": "Name", "type": "string"},
                       {"name": "status", "label": "Status", "type": "enum", "options": ["Live"]}]},
                  {"name": "promo", "kind": "form", "label": "New code", "fields": [
                       {"name": "code", "label": "Code", "type": "string"},
                       {"name": "market", "label": "Market", "type": "enum", "options": ["Egypt", "Jordan"]}]}],
         "actions": [{"name": "onOpen", "label": "Open", "kind": "navigate", "nodes": ["4"]},
                     {"name": "onCreateCode", "label": "Create code", "kind": "submit", "on": "promo", "nodes": ["20"]}]}
ANSWER = {"contract": SMALL,
          "lists": [{"prop": "tenants", "rows": ["4", "7", "10"],
                     "looks": [{"node": "6", "field": "status", "by": [{"value": "Live", "row": "4"},
                                                                       {"value": "Paused", "row": "7"}]}]}],
          "values": [{"node": "5", "expr": "row.name"}, {"node": "6", "expr": "row.status", "prop": "label"}],
          "inputs": [{"node": "14", "form": "promo", "field": "code", "kind": "text"},
                     {"node": "16", "form": "promo", "field": "market", "kind": "choice", "value": "Egypt",
                      "on_look": "16", "off_look": "18"},
                     {"node": "18", "form": "promo", "field": "market", "kind": "choice", "value": "Jordan",
                      "on_look": "16", "off_look": "18"}],
          "shows": []}


def test_every_element_of_the_drawing_is_numbered_for_the_model():
    from services.drawn import markup as M

    shown = M.numbered(M.parse(STATIC))
    assert '5|   <p className="text-[14px]">MedStaff</p>' in shown
    assert '6|   <div className="w-[60px] shrink-0"><DhTagSuccess label={"Live"} /></div>' in shown


def test_a_view_is_built_from_the_drawing_by_number():
    out, problems = P.apply(STATIC, json.loads(json.dumps(ANSWER)), "TenantsView",
                            components={"DhTagSuccess": ["label"], "DhTagWarning": ["label"], "DhButtonPrimary": ["label"]})
    assert problems == [] and out is not None
    code = out["code"]
    assert code.count(".map((row) => (") == 1 and "MedStaff" not in code and "CarePoint" not in code
    assert "{row.name}" in code and "key={row.id}" in code and "onClick={() => props.onOpen(row)}" in code
    # the look a row is drawn in follows its field: the other row's pill, the template's elements
    assert 'row.status === "Live" ?' in code and "<DhTagWarning label={row.status} />" in code
    assert "<input" in code and 'value={props.promo.code ?? ""}' in code
    assert 'props.onPromoChange("market", "Egypt")' in code and 'props.promo.market === "Egypt" ?' in code
    # an option keeps its own words in either look: Jordan is never drawn as Egypt
    assert code.count(">Jordan</p>") == 2 and code.count(">Egypt</p>") == 2
    assert "onClick={() => props.onCreateCode()}" in code
    assert 'import DhTagWarning from "./DhTagWarning";' in code and "export type TenantsViewProps" in code
    # every drawn class is still there and nothing is restyled: the one class
    # string not drawn is the input, in the look of the text it replaces
    import re
    drawn, made = (set(re.findall(r'className="([^"]*)"', x)) for x in (STATIC, code))
    assert drawn - made == {"flex-1 text-[14px]"}
    assert [c for c in made - drawn] == ["flex-1 text-[14px] w-full bg-transparent outline-none border-0 p-0 m-0 min-w-0 appearance-none"]
    assert out["contract"]["actions"][0]["on"] == "tenants" and "nodes" not in out["contract"]["actions"][0]


def test_the_sample_is_read_from_the_drawing():
    out, _ = P.apply(STATIC, json.loads(json.dumps(ANSWER)), "TenantsView")
    assert out["sample"]["tenants"] == [{"id": "1", "name": "MedStaff", "status": "Live"},
                                        {"id": "2", "name": "CarePoint", "status": "Paused"},
                                        {"id": "3", "name": "Nile Health", "status": "Live"}]
    assert out["sample"]["promo"] == {"code": "GULFNURSE30", "market": "Egypt"}
    # an enum's options are the values the drawing shows
    status = out["contract"]["data"][0]["fields"][1]
    assert status["options"] == ["Live", "Paused"] and '"Live" | "Paused"' in out["code"]


CODES = """export default function PromoCodesView() {
  return (
    <div className="flex flex-col">
      <div className="flex flex-row gap-x-[8px]" data-layer="Row">
        <p className="text-[14px]">GULFNURSE30</p>
        <div className="w-[60px] shrink-0"><DhTagSuccess label={"Active"} /></div>
      </div>
      <div className="flex flex-row gap-x-[8px] opacity-[0.6]" data-layer="Row">
        <p className="text-[14px]">NURSEWEEK50</p>
        <div className="w-[60px] shrink-0"><DhTagNeutral label={"Expired"} /></div>
        <div className="w-[80px] shrink-0"><DhButtonLink label={"Extend"} /></div>
      </div>
    </div>
  );
}
"""


def test_a_look_drawn_with_more_than_the_template_keeps_what_it_draws():
    answer = {"contract": {"data": [{"name": "codes", "kind": "list", "label": "Codes", "fields": [
                  {"name": "code", "label": "Code", "type": "string"},
                  {"name": "status", "label": "Status", "type": "enum", "options": ["Active", "Expired"]}]}],
                  "actions": [{"name": "onExtend", "label": "Extend", "kind": "run", "nodes": ["8"]}]},
              "lists": [{"prop": "codes", "rows": ["2", "5"], "looks": [{"field": "status", "by": [
                  {"value": "Active", "row": "2"}, {"value": "Expired", "row": "5"}]}]}],
              "values": [{"node": "3", "expr": "row.code"}, {"node": "4", "expr": "row.status"}],
              "inputs": [], "shows": []}
    out, problems = P.apply(CODES, answer, "PromoCodesView")
    assert problems == [], problems
    code = out["code"]
    expired = code[code.index(") :"):]
    assert "opacity-[0.6]" in expired and "{row.code}" in expired and "<DhTagNeutral label={row.status} />" in expired
    assert "onClick={() => props.onExtend(row)}><DhButtonLink" in expired
    assert out["sample"]["codes"][1] == {"id": "2", "code": "NURSEWEEK50", "status": "Expired"}


QUEUE = """export default function QueueView() {
  return (
    <div className="flex flex-col">
      <div className="flex flex-col" data-layer="Rows">
        <div className="flex flex-row bg-[#eaf0ff]" data-layer="Row">
          <p className="text-[14px]">GULFNURSE30</p>
          <div className="shrink-0"><DhTagSuccess label={"Active"} /></div>
        </div>
        <div className="flex flex-row bg-[#ffffff]" data-layer="Row">
          <p className="text-[14px]">DHAEXPO25</p>
          <div className="shrink-0"><DhTagSuccess label={"Active"} /></div>
        </div>
        <div className="flex flex-row bg-[#ffffff]" data-layer="Row">
          <p className="text-[14px]">NURSEWEEK50</p>
          <div className="shrink-0"><DhTagNeutral label={"Expired"} /></div>
        </div>
      </div>
    </div>
  );
}
"""


def test_the_selected_rows_highlight_and_its_pill_follow_fields_of_their_own():
    answer = {"contract": {"data": [{"name": "codes", "kind": "list", "label": "Codes", "fields": [
                  {"name": "code", "label": "Code", "type": "string"},
                  {"name": "selected", "label": "Selected", "type": "boolean"},
                  {"name": "status", "label": "Status", "type": "enum", "options": ["Active", "Expired"]}]}],
                  "actions": [{"name": "onSelect", "label": "Select", "kind": "open", "nodes": ["3"]}]},
              "lists": [{"prop": "codes", "rows": ["3", "6", "9"], "looks": [
                  {"field": "selected", "by": [{"value": "true", "row": "3"}, {"value": "false", "row": "6"}]},
                  {"node": "5", "field": "status", "by": [{"value": "Active", "row": "3"}, {"value": "Expired", "row": "9"}]}]}],
              "values": [{"node": "4", "expr": "row.code"}, {"node": "5", "expr": "row.status"}],
              "inputs": [], "shows": []}
    out, problems = P.apply(QUEUE, answer, "QueueView")
    assert problems == [], problems
    code = out["code"]
    assert "row.selected ? (" in code and 'row.status === "Active" ? (' in code
    assert code.count("bg-[#eaf0ff]") == 1, "only the selected look is highlighted"
    assert [(r["selected"], r["status"]) for r in out["sample"]["codes"]] == \
        [(True, "Active"), (False, "Active"), (False, "Expired")]
    # a look declares its field: `selected` left out of the contract is added, on/off
    undeclared = json.loads(json.dumps(answer))
    undeclared["contract"]["data"][0]["fields"] = [f for f in undeclared["contract"]["data"][0]["fields"]
                                                   if f["name"] != "selected"]
    out, problems = P.apply(QUEUE, undeclared, "QueueView")
    assert problems == [] and "selected: boolean" in out["code"]
    # without the selected look, every row would be tinted as the first is
    answer["lists"][0]["looks"] = answer["lists"][0]["looks"][1:]
    out, problems = P.apply(QUEUE, answer, "QueueView")
    assert out is None and "element 3 is drawn in other colours on row 6 (bg-[#ffffff])" in problems[0]


TABLE = """export default function PlansView() {
  return (
    <div className="flex flex-row" data-layer="Table">
      <div className="flex flex-col w-[120px]" data-layer="Plan">
        <p className="font-[600]">Free</p>
        <p className="font-[600]">Solo</p>
      </div>
      <div className="flex flex-col w-[120px]" data-layer="Monthly">
        <p className="text-[13px]">USD 0</p>
        <p className="text-[13px]">USD 89</p>
      </div>
    </div>
  );
}
"""


def test_a_table_drawn_column_by_column_is_one_list():
    answer = {"contract": {"data": [{"name": "plans", "kind": "list", "label": "Plans", "fields": [
                  {"name": "name", "label": "Plan", "type": "string"},
                  {"name": "monthly", "label": "Monthly", "type": "money"}]}], "actions": []},
              "lists": [{"prop": "plans", "rows": ["3", "4"]}, {"prop": "plans", "rows": ["6", "7"]}],
              "values": [{"node": "3", "expr": "row.name"}, {"node": "6", "expr": "row.monthly"}],
              "inputs": [], "shows": []}
    out, problems = P.apply(TABLE, answer, "PlansView")
    assert problems == [], problems
    assert out["code"].count("props.plans.map((row) => (") == 2 and "USD 89" not in out["code"]
    assert out["sample"]["plans"] == [{"id": "1", "name": "Free", "monthly": "USD 0"},
                                      {"id": "2", "name": "Solo", "monthly": "USD 89"}]


RULES = """export default function RulesView() {
  return (
    <div className="flex flex-col" data-layer="Rules">
      <div className="flex flex-row gap-x-[8px]" data-layer="R">
        <img src="/drawn/tick.svg" alt="" className="w-[15px] h-[15px]" />
        <p className="text-[12px]">Discounts DITANS fees only</p>
      </div>
      <div className="flex flex-row gap-x-[8px]" data-layer="R">
        <img src="/drawn/cross.svg" alt="" className="w-[15px] h-[15px]" />
        <p className="text-[12px]">Never discounts exam fees</p>
      </div>
      <div className="flex flex-row gap-x-[8px]" data-layer="R">
        <img src="/drawn/tick.svg" alt="" className="w-[15px] h-[15px]" />
        <p className="text-[12px]">Every redemption is logged</p>
      </div>
    </div>
  );
}
"""
RULES_ANSWER = {"contract": {"data": [{"name": "rules", "kind": "list", "label": "Rules", "fields": [
                    {"name": "text", "label": "Rule", "type": "string"},
                    {"name": "allowed", "label": "Allowed", "type": "boolean"}]}], "actions": []},
                "lists": [{"prop": "rules", "rows": ["2", "5", "8"]}],
                "values": [{"node": "4", "expr": "row.text"}], "inputs": [], "shows": []}


def test_a_list_that_would_lose_what_its_rows_draw_differently_is_refused():
    out, problems = P.apply(RULES, json.loads(json.dumps(RULES_ANSWER)), "RulesView")
    assert out is None and "element 3 is a different picture on row 5" in problems[0]
    answer = json.loads(json.dumps(RULES_ANSWER))
    answer["lists"][0]["looks"] = [{"node": "3", "field": "allowed", "by": [{"value": "true", "row": "2"},
                                                                          {"value": "false", "row": "5"}]}]
    out, problems = P.apply(RULES, answer, "RulesView")
    assert problems == [] and "row.allowed ? (" in out["code"]
    # the cross is the look's picture, drawn where the field says
    assert out["code"].index("tick.svg") < out["code"].index("cross.svg")
    assert [r["allowed"] for r in out["sample"]["rules"]] == [True, False, True]


TABS = """export default function TabsView() {
  return (
    <div className="flex flex-row gap-x-[8px]" data-layer="Tabs">
      <div className="px-[12px] border-[1px]" data-layer="Tab">
        <p className="text-[13px]">Candidate</p>
      </div>
      <div className="px-[12px] bg-[#eaf0ff] border-[#0443fa]" data-layer="Tab">
        <img src="/drawn/check.svg" alt="" className="w-[12px] h-[12px]" />
        <p className="text-[13px] text-[#0443fa]">Employer</p>
      </div>
      <div className="px-[12px] border-[1px]" data-layer="Tab">
        <p className="text-[13px]">Agency</p>
      </div>
    </div>
  );
}
"""


def test_a_look_drawn_with_an_icon_before_its_words_keeps_the_rows_words():
    answer = {"contract": {"data": [{"name": "tabs", "kind": "list", "label": "Tabs", "fields": [
                  {"name": "label", "label": "Tab", "type": "string"},
                  {"name": "selected", "label": "Selected", "type": "boolean"}]}], "actions": []},
              "lists": [{"prop": "tabs", "rows": ["2", "4", "7"], "looks": [
                  {"field": "selected", "by": [{"value": "true", "row": "4"}, {"value": "false", "row": "2"}]}]}],
              "values": [{"node": "3", "expr": "row.label"}], "inputs": [], "shows": []}
    out, problems = P.apply(TABS, answer, "TabsView")
    assert problems == [], problems
    selected = out["code"][out["code"].index("row.selected ? ("):out["code"].index(") :")]
    assert "check.svg" in selected and "{row.label}" in selected and "Employer" not in selected
    assert [r["selected"] for r in out["sample"]["tabs"]] == [False, True, False]


PILLS = """export default function PillsView() {
  return (
    <div className="flex flex-col" data-layer="Rows">
      <div className="flex flex-row bg-[#ffffff]" data-layer="Row">
        <div className="shrink-0"><DhTab label={"Candidate"} /></div>
      </div>
      <div className="flex flex-row bg-[#f2f2f2]" data-layer="Row">
        <div className="shrink-0"><DhTabSelected check={"\u2713"} label={"Employer"} /></div>
      </div>
    </div>
  );
}
"""


def test_a_look_drawn_as_another_component_takes_its_props_and_a_decided_field_is_not_asked_again():
    answer = {"contract": {"data": [{"name": "tabs", "kind": "list", "label": "Tabs", "fields": [
                  {"name": "label", "label": "Tab", "type": "string"},
                  {"name": "status", "label": "Status", "type": "enum", "options": ["Open", "Chosen"]}]}],
                  "actions": []},
              "lists": [{"prop": "tabs", "rows": ["2", "4"], "looks": [
                  {"field": "status", "by": [{"value": "Open", "row": "2"}, {"value": "Chosen", "row": "4"}]},
                  {"node": "3", "field": "status", "by": [{"value": "Open", "row": "2"}, {"value": "Chosen", "row": "4"}]}]}],
              "values": [{"node": "3", "expr": "row.label", "prop": "label"}], "inputs": [], "shows": []}
    out, problems = P.apply(PILLS, answer, "PillsView")
    assert problems == [], problems
    code = out["code"]
    assert '<DhTabSelected check={"\u2713"} label={row.label} />' in code
    assert code.count('row.status === "Open"') == 1, "inside the row's branch the pill's look is already known"


def test_a_field_shown_as_words_is_words():
    answer = json.loads(json.dumps(ANSWER))
    answer["contract"]["data"].append({"name": "terms", "kind": "record", "label": "Terms", "fields": [
        {"name": "newAccountsOnly", "label": "New accounts only", "type": "boolean"}]})
    answer["values"].append({"node": "2", "expr": "props.terms.newAccountsOnly"})
    out, problems = P.apply(STATIC, answer, "TenantsView")
    assert problems == [] and "newAccountsOnly: string" in out["code"]
    assert out["sample"]["terms"]["newAccountsOnly"] == "Tenants"


def test_an_answer_that_names_what_is_not_there_is_asked_again():
    wrong = json.loads(json.dumps(ANSWER))
    wrong["values"][0] = {"node": "99", "expr": "row.name"}
    wrong["contract"]["data"].append({"name": "owner", "kind": "value", "label": "Owner", "fields": []})
    replies = iter([json.dumps(wrong), json.dumps(ANSWER)])
    asked, spent = [], []

    class Reply:
        def __init__(self, text):
            self.text, self.usage = text, object()

    def client(*, system, user, schema, **_kw):
        asked.append(user)
        assert "controls" not in schema["properties"]
        return Reply(next(replies))

    harder = []

    def retry(**kw):
        harder.append(kw["user"])
        return client(**kw)

    out = P.parameterise(client, "TenantsView", STATIC, heading="Tenants", image=None, links=[], components={},
                         usage=spent, retry=retry)
    assert out["rounds"] == 2 and len(spent) == 2
    assert len(harder) == 1, "a refused round is asked again of the client that thinks harder"
    assert "there is no element 99" in asked[1]
    assert out["code"].startswith('"use client";')


def test_a_drawn_screen_is_bound_at_medium_and_asked_again_at_high():
    from dataclasses import dataclass

    from services.blueprint.executors import EFFORT_BY_NODE, at_high

    @dataclass
    class Client:
        effort: str

    assert EFFORT_BY_NODE["drawn_views"] == "medium"
    assert at_high(Client("medium")).effort == "high" and at_high(Client("xhigh")).effort == "xhigh"


def test_a_refused_screen_still_reports_what_it_spent():
    spent = []

    class Reply:
        text, usage = json.dumps({"contract": SMALL, "lists": [], "values": [], "inputs": [], "shows": []}), object()

    with pytest.raises(ValueError, match="nothing reads"):
        P.parameterise(lambda **_kw: Reply(), "TenantsView", STATIC, heading="T", image=None, links=[],
                       components={}, usage=spent)
    assert len(spent) == P.ROUNDS


# -- 2. the journey, written down ------------------------------------------------

def test_chapter_headings_on_the_canvas_are_the_frames_groups():
    from services.figma.reference import _screen_nodes

    section = {"id": "6:1", "type": "SECTION", "name": "Section 1", "children": [
        {"id": "6:2", "type": "TEXT", "characters": "1 · Operations & tenants", "absoluteBoundingBox": _box(0, 0, 300, 40)},
        {"id": "6:3", "type": "FRAME", "name": "A-01", "absoluteBoundingBox": _box(0, 80, 1440, 1024)},
        {"id": "6:4", "type": "TEXT", "characters": "5 · Promotions", "absoluteBoundingBox": _box(0, 1200, 300, 40)},
        {"id": "6:5", "type": "FRAME", "name": "A-11", "absoluteBoundingBox": _box(1500, 1280, 1440, 1024)}]}
    groups = {node["name"]: sec for _c, sec, node, _p in _screen_nodes({"document": section}) if node.get("type") == "FRAME"}
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
    assert "<DrawnShell controls={cluster} role={role}>{children}</DrawnShell>" in layout
    default = Path(__file__).resolve().parents[3] / "templates/app-foundation/src/components/DrawnShell.tsx"
    assert "DRAWN_SHELL = false" in default.read_text()


def test_the_build_converts_the_frames_first_and_the_requirements_read_the_journey():
    from services.blueprint.orchestrator import DAG, subjects_for
    from services.smith.smith import domain_nodes

    assert "drawn_flow" in DAG["requirements"].depends_on and DAG["drawn_views"].fanout == "drawn_frames"
    assert domain_nodes()[:3] == ["drawn_views", "drawn_pairs", "drawn_flow"]
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
    (row,) = payload["rows"]
    assert payload["table"] == "tenants" and {k: v for k, v in row.items() if k != "id"} == {"name": "MedStaff", "seats": 7}
    assert len(row["id"]) == 36                      # a uuid of its own, made from its name


def _linked_svc(tmp_path):
    from services.blueprint.service import BlueprintService

    svc = BlueprintService.create(output_dir=str(tmp_path), app_id="s", name="S", domain="unknown")
    svc.doc["data"] = {
        "entities": [
            {"id": "ENTITY-001", "name": "Tenant", "table": "tenants", "status": "PROPOSED",
             "fields": [{"name": "id", "type": "uuid"}, {"name": "code", "type": "string", "unique": True},
                        {"name": "planId", "type": "uuid", "required": True}]},
            {"id": "ENTITY-002", "name": "Plan", "table": "plans", "status": "PROPOSED",
             "fields": [{"name": "id", "type": "uuid"}, {"name": "name", "type": "string", "unique": True}]},
            {"id": "ENTITY-003", "name": "Override", "table": "overrides", "status": "PROPOSED",
             "fields": [{"name": "id", "type": "uuid"}, {"name": "key", "type": "string"},
                        {"name": "tenantId", "type": "uuid", "required": True}]}],
        "relationships": [
            {"from": "ENTITY-002", "fromField": "id", "kind": "one_to_many", "to": "ENTITY-001", "toField": "planId"},
            {"from": "ENTITY-001", "fromField": "id", "kind": "one_to_many", "to": "ENTITY-003", "toField": "tenantId"}]}
    svc.save()
    (tmp_path / "app").mkdir()
    return svc


def test_drawn_rows_point_at_the_rows_they_name_and_parents_load_first(tmp_path):
    from services.drawn.seed import record

    svc = _linked_svc(tmp_path)
    app = str(tmp_path / "app")
    said = record(svc, {
        "Override": [{"id": "o1", "key": "jobs", "tenantId": "tenant-2"},
                     {"id": "o2", "key": "seats", "tenantId": "tenant-9"}],          # names no tenant: left out
        "Tenant": [{"id": "tenant-2", "code": "TN-0011", "planId": "plan-premium"}],  # the plan by a prefixed name
        "Plan": [{"name": "Premium"}, {"name": "Starter"}]}, page_id="PAGE-001", app_root=app)
    assert said == ["Plan: 2 drawn row(s)", "Tenant: 1 drawn row(s)", "Override: 1 drawn row(s), 1 left out"]
    files = sorted((tmp_path / "app/src/db/imports").glob("*.json"))
    tables = [json.loads(f.read_text())["table"] for f in files]
    assert tables == ["plans", "tenants", "overrides"]               # the seeder's name order is the load order
    plans, tenants, overrides = (json.loads(f.read_text())["rows"] for f in files)
    premium = next(p["id"] for p in plans if p["name"] == "Premium")
    assert tenants[0]["planId"] == premium
    assert overrides == [{"id": overrides[0]["id"], "key": "jobs", "tenantId": tenants[0]["id"]}]


def test_a_row_two_pages_draw_is_loaded_once_and_named_from_the_other_page(tmp_path):
    from services.drawn.seed import record

    svc = _linked_svc(tmp_path)
    app = str(tmp_path / "app")
    record(svc, {"Plan": [{"name": "Premium"}, {"name": "Starter"}]}, page_id="PAGE-001", app_root=app)
    said = record(svc, {"Plan": [{"name": "Premium"}],
                        "Tenant": [{"code": "TN-7", "planId": "Premium"}]}, page_id="PAGE-002", app_root=app)
    assert said == ["Tenant: 1 drawn row(s)"]                         # no second Premium
    rows = [json.loads(f.read_text()) for f in sorted((tmp_path / "app/src/db/imports").glob("*.json"))]
    plan = next(r for p in rows if p["table"] == "plans" for r in p["rows"] if r["name"] == "Premium")
    assert next(p for p in rows if p["table"] == "tenants")["rows"][0]["planId"] == plan["id"]


def test_the_finished_app_compiles_a_page_with_its_parts_and_a_drawn_page_goes_back_to_its_binder(monkeypatch, tmp_path):
    from services.blueprint import ui_engineer
    from services.drawn import binder

    seen = {}

    class Svc:
        import threading
        lock = threading.RLock()
        doc = {"pages": [{"id": "PAGE-001"}],
               "pageCode": [{"page": "PAGE-001", "load": "l", "view": "v", "parts": {"TenantsView": "x"}}]}

    def typecheck(doc, root, pid, load, view, parts=None):
        seen["parts"] = parts
        return ["view.tsx(1,1): error TS2307: Cannot find module './parts/TenantsView'"]

    def bind(doc, page, root, client, *, feedback=""):
        seen["bound"] = feedback
        return {"page": "PAGE-001", "load": "l", "view": "v2", "parts": {"TenantsView": "x"}, "seed": {"T": []}}, []

    applied = []
    monkeypatch.setattr(ui_engineer, "typecheck", typecheck)
    monkeypatch.setattr(binder, "applies", lambda doc, page: True)
    monkeypatch.setattr(binder, "bind", bind)
    monkeypatch.setattr(ui_engineer, "compose_page", lambda *a, **k: pytest.fail("a drawn page is never redrawn"))
    monkeypatch.setattr("services.blueprint.agent_contract.apply_agent_result",
                        lambda svc, result, commit: applied.append(result.proposals[0].body))
    monkeypatch.setattr("services.blueprint.app_sdk.project_code_pages", lambda doc, root: None)
    assert ui_engineer.settle_code_pages(Svc(), tmp_path, client=object()) == {"PAGE-001": "rewritten"}
    assert seen["parts"] == {"TenantsView": "x"} and "TS2307" in seen["bound"]
    assert applied and "seed" not in applied[0]


def test_assembly_keeps_the_drawn_frames_wrapper():
    from services.blueprint.assembly import SCAFFOLD_DEFAULTS

    assert "src/components/DrawnShell.tsx" in SCAFFOLD_DEFAULTS


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
