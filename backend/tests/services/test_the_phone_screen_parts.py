"""Choosing a look from the kit's pick lists, putting parts in another order, and adding a ready part to a phone screen.

The pick lists are read from the kit's own types, so a choice from one cannot break the screen and is saved without the compiler.
A part is added only from the palette, exactly as written there; every palette entry is compiled against the real kit here. Where
the phone's toolchain is not installed the tests that need it are skipped, and the rest say what is refused without it."""
from __future__ import annotations

import pytest

from services.blueprint import native_engineer
from services.blueprint.service import BlueprintService
from services.react_editor import adapter, pages, phone_kit, phone_palette, phone_screens as ps, service
from services.react_editor.service import EditorError

needs_toolchain = pytest.mark.skipif(
    not (native_engineer.toolchain_dir() / "node_modules" / "typescript" / "lib" / "typescript.js").is_file(),
    reason="the phone's toolchain is not installed here")

SCREEN = '''import React from "react";
import { Screen as ScreenView, Text, Row, Stack, Button } from "@/ui";

export default function Screen() {
  return (
    <ScreenView title="Shopping List">
      <Text variant="body">First</Text>
      <Text variant="body">Second</Text>
      <Row gap="sm">
        <Button variant="accent" onPress={() => {}}>Add</Button>
      </Row>
      <Stack gap="sm">
        <Text>Inside</Text>
      </Stack>
    </ScreenView>
  );
}
'''


@pytest.fixture
def p(tmp_path, monkeypatch):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Cart Buddy", domain="ops")
    doc = svc.doc
    doc["pages"] = [{"id": "PAGE-001", "name": "Shopping List", "route": "/", "purpose": "The list.",
                     "access": "authenticated", "pattern": "entity_list"}]
    doc["navigation"] = {"style": "topbar", "tree": [{"label": "Shopping List", "page": "PAGE-001"}]}
    doc["mobile"] = {"surface": "native_only", "native": {"enabled": True}, "store": {"bundleId": "com.example.cartbuddy"}}
    doc["nativeCode"] = [{"page": "PAGE-001", "screen": SCREEN, "rationale": "r", "requirements": []}]
    doc["designSystem"] = {"colors": {"primary": "#2563EB"}}
    svc.save()
    (tmp_path / "app" / "src" / "app").mkdir(parents=True)
    (tmp_path / "app" / "package.json").write_text("{}")
    monkeypatch.setattr("services.blueprint.projection.project_public_nav", lambda doc, root: "")
    monkeypatch.setattr(pages, "project_code_pages", lambda doc, root: [])

    def no_compiler(doc, project, page_id, screen):
        raise EditorError(503, "no-compiler", "not installed")
    monkeypatch.setattr(ps, "_compile", no_compiler)            # a change that needs it must not get this far
    return service.locate(tmp_path)


def _opened(p):
    return ps.open_screen(p, "PAGE-001")


def _node(opened, type, text=None):
    return next(n for n in opened["model"]["nodes"].values() if n["type"] == type and (text is None or n.get("text") == text))


def _file(p) -> str:
    return (p.root / "native" / "src" / "screens" / "PAGE-001.tsx").read_text(encoding="utf-8")


def _saved(p) -> str:
    return next(r for r in service.load_blueprint(p).doc["nativeCode"] if r["page"] == "PAGE-001")["screen"]


def _set(node, name, value):
    return {"op": "setProp", "id": node["id"], "name": name, "value": value}


STR = lambda v: {"kind": "string", "value": v}       # noqa: E731


# ---- the choices a part has --------------------------------------------------------------------------------------

@needs_toolchain
def test_the_pick_lists_are_read_from_the_kits_own_types(tmp_path):
    shown = phone_kit.for_browser(tmp_path)
    assert shown["ok"] is True
    button = shown["components"]["Button"]["props"]
    assert set(button["variant"]["values"]) == {"primary", "accent", "secondary", "outline", "ghost", "danger"}
    assert button["size"]["values"] == ["sm", "md"]
    assert shown["components"]["Text"]["props"]["tone"]["values"][:2] == ["default", "accent"]
    assert shown["components"]["Stack"]["props"]["gap"]["values"][:3] == ["xs", "sm", "md"]
    assert shown["components"]["Row"]["props"]["wrap"] == {"kind": "boolean", "optional": True}


@needs_toolchain
def test_what_the_screens_own_logic_decides_is_not_offered_as_a_choice(tmp_path):
    props = phone_kit.for_browser(tmp_path)["components"]["Button"]["props"]
    assert "loading" not in props and "disabled" not in props and "onPress" not in props


@needs_toolchain
def test_a_very_long_list_is_sent_once_not_with_every_part(tmp_path):
    shown = phone_kit.for_browser(tmp_path)
    icon = shown["components"]["Button"]["props"]["icon"]
    assert icon["values"] == [] and icon["list"] in shown["lists"] and "star" in shown["lists"][icon["list"]]


@needs_toolchain
def test_only_a_word_from_the_list_is_allowed(tmp_path):
    assert phone_kit.allows(tmp_path, "Button", "variant", STR("ghost"))
    assert not phone_kit.allows(tmp_path, "Button", "variant", STR("big"))
    assert not phone_kit.allows(tmp_path, "Button", "onPress", STR("x")), "not a choice"
    assert not phone_kit.allows(tmp_path, "Button", "loading", {"kind": "true"}), "the screen's logic"
    assert phone_kit.allows(tmp_path, "Row", "wrap", {"kind": "true"})
    assert not phone_kit.allows(tmp_path, "Row", "wrap", STR("yes"))


@needs_toolchain
def test_a_setting_can_be_taken_away_only_when_it_is_optional(tmp_path):
    assert phone_kit.allows(tmp_path, "Button", "variant", None)
    assert not phone_kit.allows(tmp_path, "SimpleChart", "type", None), "the chart needs to know what kind it is"


@needs_toolchain
def test_a_choice_from_the_list_is_saved_without_the_compiler(p):
    o = _opened(p)
    out = ps.apply(p, "PAGE-001", base_revision=o["revision"], ops=[_set(_node(o, "Button"), "variant", STR("ghost"))])
    assert out["checked"] is False and 'variant="ghost"' in _file(p) and 'variant="accent"' not in _file(p)


@needs_toolchain
def test_a_switch_is_turned_on_and_a_choice_taken_away(p):
    o = _opened(p)
    first = ps.apply(p, "PAGE-001", base_revision=o["revision"], ops=[_set(_node(o, "Row"), "wrap", {"kind": "true"})])
    assert "<Row gap=\"sm\" wrap>" in _file(p) or "wrap" in _file(p)
    ps.apply(p, "PAGE-001", base_revision=first["revision"], ops=[_set(_node(first, "Button"), "variant", None)])
    assert 'variant="accent"' not in _file(p)


@needs_toolchain
def test_a_word_that_is_not_on_the_list_needs_the_compiler_and_is_not_saved_without_it(p):
    o = _opened(p)
    before = _saved(p)
    with pytest.raises(EditorError) as e:
        ps.apply(p, "PAGE-001", base_revision=o["revision"], ops=[_set(_node(o, "Button"), "variant", STR("big"))])
    assert e.value.code == "no-compiler" and _saved(p) == before


# ---- another order ---------------------------------------------------------------------------------------------------

def test_a_part_moves_among_its_brothers_without_the_compiler(p):
    o = _opened(p)
    first, second = _node(o, "Text", "First"), _node(o, "Text", "Second")
    out = ps.apply(p, "PAGE-001", base_revision=o["revision"],
                   ops=[{"op": "move", "id": second["id"], "parentId": second["parent"], "index": first["index"]}])
    text = _file(p)
    assert out["checked"] is False and text.index("Second") < text.index("First")


def test_a_part_does_not_move_into_another_part_without_the_compiler(p):
    o = _opened(p)
    before = _saved(p)
    inside, row = _node(o, "Text", "Inside"), _node(o, "Row")
    with pytest.raises(EditorError) as e:
        ps.apply(p, "PAGE-001", base_revision=o["revision"],
                 ops=[{"op": "move", "id": inside["id"], "parentId": row["id"], "index": 0}])
    assert e.value.code == "no-compiler" and _saved(p) == before


# ---- adding a ready part -----------------------------------------------------------------------------------------------

def _add(part_id, **where):
    entry = next(e for e in phone_palette.PALETTE if e["id"] == part_id)
    return [{"op": "addImport", "source": "@/ui", "names": entry["imports"]}, {"op": "insert", "jsx": entry["jsx"], **where}]


def test_a_ready_part_is_added_inside_a_container_and_imported(p):
    o = _opened(p)
    out = ps.apply(p, "PAGE-001", base_revision=o["revision"], ops=_add("badge", parentId=_node(o, "Stack")["id"]))
    text = _file(p)
    assert out["checked"] is False and "<Badge>New</Badge>" in text and "Badge" in text.split("from \"@/ui\"")[0]
    assert text.index("<Badge>") > text.index("Inside") and text.index("<Badge>") < text.index("</Stack>")


def test_a_ready_part_goes_into_the_screen_itself_and_after_a_part(p):
    o = _opened(p)
    ps.apply(p, "PAGE-001", base_revision=o["revision"], ops=_add("divider", parentId=_node(o, "ScreenView")["id"]))
    assert "<Divider />" in _file(p)
    o2 = _opened(p)
    ps.apply(p, "PAGE-001", base_revision=o2["revision"], ops=_add("note", afterId=_node(o2, "Text", "First")["id"]))
    text = _file(p)
    assert text.index("First") < text.index("A small note") < text.index("Second")


def test_a_ready_part_dropped_before_a_part_goes_in_front_of_it_without_the_compiler(p):
    o = _opened(p)
    out = ps.apply(p, "PAGE-001", base_revision=o["revision"], ops=_add("divider", beforeId=_node(o, "Text", "Second")["id"]))
    text = _file(p)
    assert out["checked"] is False and text.index("First") < text.index("<Divider />") < text.index("Second")


def test_a_part_is_not_dropped_beside_something_whose_parent_cannot_hold_it_without_the_compiler(p):
    """A Text inside a Button: the Button holds words, not a divider."""
    nodes = {"r0": {"parent": None, "type": "ScreenView"}, "r0.0": {"parent": "r0", "type": "Button"},
             "r0.0.0": {"parent": "r0.0", "type": "Text"}}
    before = {"nodes": nodes, "imports": {"ScreenView": "Screen", "Button": "Button", "Text": "Text"}}
    divider = next(e for e in phone_palette.PALETTE if e["id"] == "divider")
    beside = {"op": "insert", "jsx": divider["jsx"], "beforeId": "r0.0.0"}
    assert ps._safe_without_compiler(beside, before, p) is False
    assert ps._safe_without_compiler({**beside, "beforeId": "r0.0"}, before, p) is True, "beside the Button, in the screen, is fine"
    slot = {**nodes, "r0@footer.0": {"parent": "r0", "type": "Stack", "slot": "footer"}}
    assert ps._safe_without_compiler({**beside, "beforeId": "r0@footer.0"}, {**before, "nodes": slot}, p) is False,         "not beside a part its parent holds as a setting"


def test_a_part_that_is_not_on_the_list_is_not_added_without_the_compiler(p):
    o = _opened(p)
    before = _saved(p)
    with pytest.raises(EditorError) as e:
        ps.apply(p, "PAGE-001", base_revision=o["revision"],
                 ops=[{"op": "insert", "parentId": _node(o, "Stack")["id"], "jsx": "<Text>mine</Text>"}])
    assert e.value.code == "no-compiler" and _saved(p) == before


def test_a_part_is_not_added_inside_something_that_cannot_hold_it_without_the_compiler(p):
    o = _opened(p)
    before = _saved(p)
    with pytest.raises(EditorError) as e:
        ps.apply(p, "PAGE-001", base_revision=o["revision"], ops=_add("badge", parentId=_node(o, "Button")["id"]))
    assert e.value.code == "no-compiler" and _saved(p) == before


def test_an_import_of_something_that_is_not_in_the_kit_is_not_a_safe_change(p):
    o = _opened(p)
    with pytest.raises(EditorError) as e:
        ps.apply(p, "PAGE-001", base_revision=o["revision"], ops=[{"op": "addImport", "source": "@/ui", "names": ["Rm"]}])
    assert e.value.code == "no-compiler"


# ---- the list of ready parts ---------------------------------------------------------------------------------------------

def test_every_ready_part_is_in_a_group_with_words_a_person_would_search_by():
    ids = [e["id"] for e in phone_palette.PALETTE]
    assert len(ids) == len(set(ids)) and len(ids) >= 25
    assert {e["category"] for e in phone_palette.PALETTE} >= {"Layout", "Content", "Form", "Actions", "Collections", "Charts", "Feedback"}
    assert all(e["label"] and e["description"] and e["jsx"] and e["imports"] for e in phone_palette.PALETTE)


def test_every_ready_part_is_something_the_parser_reads_as_one_part():
    for e in phone_palette.PALETTE:
        m = adapter.model(f"export default function S() {{ return (<>{e['jsx']}</>); }}")
        tops = [n for n in m["nodes"].values() if n["parent"] and m["nodes"][n["parent"]]["kind"] == "fragment"]
        assert len(tops) == 1, e["id"]


@needs_toolchain
def test_every_ready_part_is_in_the_kit_and_compiles_against_it(tmp_path):
    kit = phone_kit.full(tmp_path)["components"]
    imports = sorted({name for e in phone_palette.PALETTE for name in e["imports"]})
    assert [n for n in imports if n not in kit] == [], "a ready part names something the kit does not have"
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Palette", domain="ops")
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "All", "route": "/", "purpose": "All.", "access": "authenticated", "pattern": "entity_list"}]
    svc.doc["mobile"] = {"surface": "native_only", "native": {"enabled": True}, "store": {"bundleId": "com.example.palette"}}
    svc.save()
    body = "\n".join(f"      {e['jsx']}".replace("\n", "\n      ") for e in phone_palette.PALETTE)
    screen = (f'import React from "react";\nimport {{ Screen, {", ".join(i for i in imports if i != "Screen")} }} from "@/ui";\n\n'
              f"export default function Page() {{\n  return (\n    <Screen title=\"All\">\n{body}\n    </Screen>\n  );\n}}\n")
    errors = native_engineer.typecheck(svc.doc, tmp_path / "native", "PAGE-001", screen, toolchain=native_engineer.toolchain_dir())
    assert errors == [], errors[:6]
