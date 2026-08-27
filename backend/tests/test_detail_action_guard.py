"""A record detail page's Edit button routinely points at ANOTHER entity's edit
route with {{item.id}}, and its Delete button has no action even though
Delete<Entity> exists. wire_detail_actions resolves the page's own entity from its
`get` dataSource and wires both correctly with {{<src>.id}}."""
import json

from services.detail_action_guard import wire_detail_actions

def _subset(result: dict, expected: dict) -> dict:
    """Project a guard's return dict down to the keys the test asserts on.

    Whole-dict equality breaks every time a guard gains a counter (e.g.
    ``asserts_logged`` from the authority demotions) even though the
    behaviour under test is unchanged. Compare only what the test means.
    """
    return {k: result.get(k) for k in expected}



def _app(tmp_path):
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {
            "Member": {"fields": {"id": {"type": "uuid"}, "fullName": {"type": "varchar"}}},
            "ClassBooking": {"fields": {"id": {"type": "uuid"}}},
        },
        "relations": [],
    }))
    wf = tmp_path / "workflows"
    wf.mkdir()
    for n in ("DeleteMember", "UpdateMember", "UpdateClassBooking"):
        (wf / f"{n}.json").write_text(json.dumps({"name": n}))
    sdir = tmp_path / "src" / "schemas"
    (sdir / "members" / "[id]").mkdir(parents=True)
    (sdir / "bookings" / "[id]").mkdir(parents=True)
    # edit schemas so the edit routes exist + resolve to their entities
    (sdir / "members" / "[id]" / "edit.json").write_text(json.dumps({
        "route": "/members/:id/edit",
        "root": {"type": "Form", "props": {"workflow": "UpdateMember"}, "children": []}}))
    (sdir / "bookings" / "[id]" / "edit.json").write_text(json.dumps({
        "route": "/bookings/:id/edit",
        "root": {"type": "Form", "props": {"workflow": "UpdateClassBooking"}, "children": []}}))
    return sdir


def _buttons(schema):
    out = {}
    def walk(n):
        if isinstance(n, list):
            for x in n: walk(x)
        elif isinstance(n, dict):
            if n.get("type") in ("Button", "IconButton"):
                p = n.get("props") or {}
                out[str(p.get("label"))] = p
            for c in (n.get("children") or []): walk(c)
            if "root" in n: walk(n["root"])
    walk(schema)
    return out


def test_wires_edit_to_own_entity_and_delete_to_workflow(tmp_path):
    sdir = _app(tmp_path)
    # Member detail page: Edit mis-wired to bookings + {{item.id}}, Delete actionless.
    (sdir / "members" / "[id].json").write_text(json.dumps({
        "route": "/members/:id",
        "dataSources": [{"name": "member", "entity": "Member", "op": "get"}],
        "root": {"type": "Stack", "children": [
            {"type": "Button", "props": {"label": "Edit", "navigate": "/bookings/{{item.id}}/edit"}},
            {"type": "Button", "props": {"label": "Delete", "variant": "danger"}},
        ]},
    }))
    res = wire_detail_actions(str(tmp_path))
    assert res["edits"] == 1 and res["deletes"] == 1
    b = _buttons(json.loads((sdir / "members" / "[id].json").read_text()))
    assert b["Edit"]["navigate"] == "/members/{{member.id}}/edit"
    assert "workflow" not in b["Edit"]
    assert b["Delete"]["workflow"] == "DeleteMember"
    assert b["Delete"]["args"] == {"id": "{{member.id}}"}
    assert "navigate" not in b["Delete"]


def test_idempotent_and_leaves_correct_alone(tmp_path):
    sdir = _app(tmp_path)
    (sdir / "members" / "[id].json").write_text(json.dumps({
        "route": "/members/:id",
        "dataSources": [{"name": "member", "entity": "Member", "op": "get"}],
        "root": {"type": "Stack", "children": [
            {"type": "Button", "props": {"label": "Edit", "navigate": "/members/{{member.id}}/edit"}},
            {"type": "Button", "props": {"label": "Delete", "workflow": "DeleteMember",
                                         "args": {"id": "{{member.id}}"}}},
        ]},
    }))
    res = wire_detail_actions(str(tmp_path))
    assert res["edits"] == 0 and res["deletes"] == 0   # already correct


def test_skips_delete_without_workflow(tmp_path):
    sdir = _app(tmp_path)
    # ClassBooking detail, but pretend no DeleteClassBooking workflow → leave Delete alone.
    (sdir / "bookings" / "[id].json").write_text(json.dumps({
        "route": "/bookings/:id",
        "dataSources": [{"name": "booking", "entity": "ClassBooking", "op": "get"}],
        "root": {"type": "Stack", "children": [
            {"type": "Button", "props": {"label": "Delete", "variant": "danger"}},
        ]},
    }))
    res = wire_detail_actions(str(tmp_path))
    assert res["deletes"] == 0   # no DeleteClassBooking workflow exists
    b = _buttons(json.loads((sdir / "bookings" / "[id].json").read_text()))
    assert "workflow" not in b["Delete"]


def test_ignores_pages_without_get_source(tmp_path):
    sdir = _app(tmp_path)
    # A list page (no get source) must not be touched by the detail pass.
    (sdir / "members.json").write_text(json.dumps({
        "route": "/members",
        "dataSources": [{"name": "members", "entity": "Member", "op": "list"}],
        "root": {"type": "Stack", "children": [
            {"type": "Button", "props": {"label": "Delete", "variant": "danger"}},
        ]},
    }))
    res = wire_detail_actions(str(tmp_path))
    assert res["deletes"] == 0


def test_missing_dir_safe(tmp_path):
    assert _subset(wire_detail_actions(str(tmp_path)), {"edits": 0, "deletes": 0, "files": 0}) == {"edits": 0, "deletes": 0, "files": 0}
