"""A phone screen is changed from the picture: words, a part taken away, a part copied, and the change brought back.

The screen is React Native code kept in the Blueprint (`nativeCode`) and copied to `native/src/screens`. The change is made by the
same parser the web editor uses, so it lands at the element it names; it is saved into the Blueprint and the phone's files are
rewritten; a change made against an older version is refused; and a change that could break the screen is not saved without the
compiler that checks it."""
from __future__ import annotations

import pytest

from services.blueprint.service import BlueprintService
from services.react_editor import pages, phone_screens as ps, service
from services.react_editor.service import EditorError

SCREEN = '''import React from "react";
import { Screen as ScreenView, Text, Row, Button } from "@/ui";
import { useList } from "@/sdk";

export default function Screen() {
  const list = useList("ShoppingItem", {});
  const count = list.data?.length ?? 0;

  return (
    <ScreenView title="Shopping List">
      <Text variant="caption" tone="muted">{count} to buy</Text>
      <Text variant="body">Add what you need</Text>
      <Row gap="sm">
        <Button variant="accent" onPress={() => {}}>
          Add
        </Button>
      </Row>
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
    # No compiler on this machine unless a test says so: nothing here may reach for one.
    monkeypatch.setattr("services.blueprint.native_engineer.toolchain_dir", lambda: tmp_path / "no-toolchain")
    return service.locate(tmp_path)


def _opened(p):
    return ps.open_screen(p, "PAGE-001")


def _node(opened, *, type, text=None):
    return next(n for n in opened["model"]["nodes"].values()
                if n["type"] == type and (text is None or n.get("text") == text))


def _saved(p) -> str:
    row = next(r for r in service.load_blueprint(p).doc["nativeCode"] if r["page"] == "PAGE-001")
    return row["screen"]


def _file(p) -> str:
    return (p.root / "native" / "src" / "screens" / "PAGE-001.tsx").read_text(encoding="utf-8")


def test_opening_a_screen_names_each_part_with_the_line_that_wrote_it(p):
    o = _opened(p)
    text = _node(o, type="Text", text="Add what you need")
    assert text["textEditable"] is True and SCREEN.splitlines()[text["line"] - 1].strip().startswith("<Text variant=\"body\"")
    assert _node(o, type="Text", text="{count} to buy")["textEditable"] is False, "words that come from data are not typed over"
    assert o["revision"] == _opened(p)["revision"], "the same screen is the same revision"
    assert "children" in text and "props" in text and "span" not in text, "the picture gets parts, not character positions"


def test_changing_words_saves_into_the_blueprint_and_rewrites_the_phones_file(p):
    o = _opened(p)
    node = _node(o, type="Text", text="Add what you need")
    out = ps.apply(p, "PAGE-001", base_revision=o["revision"], ops=[{"op": "setText", "id": node["id"], "text": "What do you need?"}])
    assert out["unchanged"] is False and out["checked"] is False, "words cannot break a type, so the compiler is not asked"
    for text in (_saved(p), _file(p)):
        assert "What do you need?" in text and "Add what you need" not in text
        assert 'variant="caption" tone="muted">{count} to buy</Text>' in text, "nothing else moved"
    assert out["revision"] != o["revision"] and out["history"]["label"] == "Edit"


def test_a_screens_title_is_changed_as_a_setting_of_the_screen(p):
    o = _opened(p)
    root = _node(o, type="ScreenView")
    ps.apply(p, "PAGE-001", base_revision=o["revision"],
             ops=[{"op": "setProp", "id": root["id"], "name": "title", "value": {"kind": "string", "value": "My list"}}])
    assert '<ScreenView title="My list">' in _file(p)


def test_a_part_is_taken_away_and_one_is_copied(p):
    o = _opened(p)
    body = _node(o, type="Text", text="Add what you need")
    first = ps.apply(p, "PAGE-001", base_revision=o["revision"], ops=[{"op": "duplicate", "id": body["id"]}])
    assert _file(p).count("Add what you need") == 2
    copy = [n for n in first["model"]["nodes"].values() if n.get("text") == "Add what you need"][-1]
    ps.apply(p, "PAGE-001", base_revision=first["revision"], ops=[{"op": "remove", "id": copy["id"]}])
    assert _file(p).count("Add what you need") == 1


def test_a_change_made_on_an_older_version_is_refused_and_nothing_is_lost(p):
    o = _opened(p)
    node = _node(o, type="Text", text="Add what you need")
    ps.apply(p, "PAGE-001", base_revision=o["revision"], ops=[{"op": "setText", "id": node["id"], "text": "First"}])
    with pytest.raises(EditorError) as e:
        ps.apply(p, "PAGE-001", base_revision=o["revision"], ops=[{"op": "setText", "id": node["id"], "text": "Second"}])
    assert e.value.status == 409 and e.value.code == "stale"
    assert "First" in _file(p) and "Second" not in _file(p)


def test_words_that_come_from_data_cannot_be_typed_over(p):
    o = _opened(p)
    node = _node(o, type="Text", text="{count} to buy")
    before = _saved(p)
    with pytest.raises(EditorError) as e:
        ps.apply(p, "PAGE-001", base_revision=o["revision"], ops=[{"op": "setText", "id": node["id"], "text": "Many"}])
    assert e.value.status == 422 and _saved(p) == before


def test_a_choice_the_kit_makes_is_not_saved_without_the_checker_that_knows_what_is_allowed(p):
    """`variant="big"` is not a word a person reads: only the phone's compiler can say whether it is allowed."""
    o = _opened(p)
    node = _node(o, type="Text", text="Add what you need")
    before = _saved(p)
    with pytest.raises(EditorError) as e:
        ps.apply(p, "PAGE-001", base_revision=o["revision"],
                 ops=[{"op": "setProp", "id": node["id"], "name": "variant", "value": {"kind": "string", "value": "big"}}])
    assert e.value.status == 503 and e.value.code == "no-compiler" and _saved(p) == before
    assert not (p.root / "native" / "src" / "screens" / "PAGE-001.tsx").exists(), "and no file was written either"


def test_a_change_the_compiler_refuses_is_not_saved_and_says_where(p, monkeypatch):
    monkeypatch.setattr(ps, "_compile", lambda doc, project, page_id, screen: [
        {"file": "Screen.tsx", "line": 12, "plain": "Line 12 of the screen: big is not something the app accepts here."}])
    o = _opened(p)
    node = _node(o, type="Text", text="Add what you need")
    before = _saved(p)
    with pytest.raises(EditorError) as e:
        ps.apply(p, "PAGE-001", base_revision=o["revision"],
                 ops=[{"op": "setProp", "id": node["id"], "name": "variant", "value": {"kind": "string", "value": "big"}}])
    assert e.value.status == 422 and e.value.extra["findings"][0]["line"] == 12 and _saved(p) == before


def test_a_version_is_brought_back_from_the_history(p):
    o = _opened(p)
    node = _node(o, type="Text", text="Add what you need")
    changed = ps.apply(p, "PAGE-001", base_revision=o["revision"], ops=[{"op": "setText", "id": node["id"], "text": "Changed"}])
    back = ps.restore(p, "PAGE-001", revision=o["revision"], expected=changed["revision"])
    assert back["revision"] == o["revision"] and "Add what you need" in _file(p) and "Changed" not in _file(p)


def test_a_screen_that_is_also_a_web_page_keeps_its_phone_history_apart(p):
    o = _opened(p)
    node = _node(o, type="Text", text="Add what you need")
    ps.apply(p, "PAGE-001", base_revision=o["revision"], ops=[{"op": "setText", "id": node["id"], "text": "Changed"}])
    assert (p.root / ".forge" / "editor" / "pages" / "phone-PAGE-001.jsonl").is_file()
    assert not (p.root / ".forge" / "editor" / "pages" / "PAGE-001.jsonl").exists()


def test_a_page_with_no_phone_screen_says_so(p):
    with pytest.raises(EditorError) as e:
        ps.open_screen(p, "PAGE-009")
    assert e.value.status in (404, 409)


def test_only_what_step_one_offers_can_be_asked_of_the_server():
    from routers.react_editor import _PHONE_OPS
    assert _PHONE_OPS == {"setText", "setProp", "remove", "duplicate"}


# ---- parts the screen hands to a component as settings (the footer, a row of a list) ----------------------------------

HELD = '''import React from "react";
import { Screen as ScreenView, Text, Row, Stack, TextField, ListView, ListItem } from "@/ui";
import { useList } from "@/sdk";

export default function Screen() {
  const list = useList("ShoppingItem", {});
  return (
    <ScreenView
      title="Shopping List"
      footer={
        <Stack gap="sm">
          <Row gap="sm">
            <TextField label="Item" value="" onChange={() => {}} placeholder="What do you need?" />
            <Text variant="caption">Pick one</Text>
          </Row>
        </Stack>
      }
    >
      <ListView list={list} renderItem={(item) => (<ListItem title={item.name} />)} />
    </ScreenView>
  );
}
'''


def test_a_part_inside_a_setting_of_its_parent_is_found_and_its_words_changed(p):
    row = next(r for r in service.load_blueprint(p).doc["nativeCode"])
    svc = service.load_blueprint(p)
    next(r for r in svc.doc["nativeCode"])["screen"] = HELD
    svc.save()
    o = _opened(p)
    field = _node(o, type="TextField")
    assert not field.get("slot"), "the text box is inside the footer, not the footer itself"
    footer = _node(o, type="Stack")
    assert footer["slot"] == "footer"
    ps.apply(p, "PAGE-001", base_revision=o["revision"], ops=[
        {"op": "setProp", "id": field["id"], "name": "label", "value": {"kind": "string", "value": "What"}},
        {"op": "setProp", "id": field["id"], "name": "placeholder", "value": {"kind": "string", "value": "Type here"}}])
    text = _file(p)
    assert 'label="What"' in text and 'placeholder="Type here"' in text and 'label="Item"' not in text
    assert 'title="Shopping List"' in text, "nothing else moved"


def test_what_is_held_as_a_setting_cannot_be_copied_or_taken_away_alone(p):
    svc = service.load_blueprint(p)
    next(r for r in svc.doc["nativeCode"])["screen"] = HELD
    svc.save()
    o = _opened(p)
    footer = _node(o, type="Stack")
    for op in ({"op": "remove", "ids": [footer["id"]]}, {"op": "duplicate", "id": footer["id"]}):
        with pytest.raises(EditorError) as e:
            ps.apply(p, "PAGE-001", base_revision=o["revision"], ops=[op])
        assert e.value.status == 422 and e.value.code == "held-by-parent"
    assert _saved(p) == HELD
    inner = _node(o, type="Text", text="Pick one")           # a part INSIDE the footer can
    ps.apply(p, "PAGE-001", base_revision=o["revision"], ops=[{"op": "remove", "ids": [inner["id"]]}])
    assert "Pick one" not in _file(p) and "<Stack" in _file(p)


def test_a_row_of_a_list_is_found_through_the_setting_that_draws_it(p):
    svc = service.load_blueprint(p)
    next(r for r in svc.doc["nativeCode"])["screen"] = HELD
    svc.save()
    row = _node(_opened(p), type="ListItem")
    assert row["slot"] == "renderItem"


def test_the_web_editor_still_sees_only_what_is_between_the_tags():
    from services.react_editor import adapter
    m = adapter.model(HELD)
    assert not any(n.get("slot") for n in m["nodes"].values()) and len(m["nodes"]) == 2
