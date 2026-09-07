"""Deterministic apply: nav-flow.transitions → Button navigate props."""
import json

from services.nav_apply import apply_transitions


def _seed(tmp_path, pages, transitions, schemas):
    c = tmp_path / "src" / "contracts"
    c.mkdir(parents=True, exist_ok=True)
    (c / "nav-flow.json").write_text(json.dumps({"pages": pages, "transitions": transitions}), encoding="utf-8")
    for rel, obj in schemas.items():
        p = tmp_path / "src" / "schemas" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj), encoding="utf-8")


def _schema(tmp_path, rel):
    return json.loads((tmp_path / "src" / "schemas" / rel).read_text(encoding="utf-8"))


def test_rewrites_button_navigate_to_transition_target(tmp_path):
    _seed(tmp_path,
          pages=[
              {"id": "orders", "route": "/orders", "schemaFile": "src/schemas/orders.json"},
              {"id": "orders/new", "route": "/orders/new", "schemaFile": "src/schemas/orders/new.json"},
          ],
          transitions=[{"id": "t1", "from": "orders", "trigger": "button:New Order", "to": "orders/new"}],
          schemas={
              # Button currently points at the WRONG route — apply must fix it.
              "orders.json": {"root": {"children": [
                  {"type": "Button", "props": {"label": "New Order", "navigate": "/wrong"}}]}},
              "orders/new.json": {"root": {}},
          })
    assert apply_transitions(str(tmp_path)) == {"applied": 1}
    btn = _schema(tmp_path, "orders.json")["root"]["children"][0]
    assert btn["props"]["navigate"] == "/orders/new"


def test_generic_link_trigger_left_untouched(tmp_path):
    _seed(tmp_path,
          pages=[
              {"id": "a", "route": "/a", "schemaFile": "src/schemas/a.json"},
              {"id": "b", "route": "/b", "schemaFile": "src/schemas/b.json"},
          ],
          transitions=[{"id": "t1", "from": "a", "trigger": "link", "to": "b"}],
          schemas={"a.json": {"root": {"children": [
              {"type": "Button", "props": {"label": "Go", "navigate": "/x"}}]}}, "b.json": {"root": {}}})
    assert apply_transitions(str(tmp_path)) == {"applied": 0}


def test_idempotent(tmp_path):
    _seed(tmp_path,
          pages=[
              {"id": "orders", "route": "/orders", "schemaFile": "src/schemas/orders.json"},
              {"id": "det", "route": "/orders/[id]", "schemaFile": "src/schemas/orders/[id].json"},
          ],
          transitions=[{"id": "t1", "from": "orders", "trigger": "button:View", "to": "det"}],
          schemas={"orders.json": {"root": {"children": [
              {"type": "Button", "props": {"label": "View", "navigate": "/orders/[id]"}}]}},
              "orders/[id].json": {"root": {}}})
    assert apply_transitions(str(tmp_path))["applied"] == 0   # already correct
    # break it, then apply fixes exactly once
    s = tmp_path / "src/schemas/orders.json"
    obj = json.loads(s.read_text(encoding="utf-8")); obj["root"]["children"][0]["props"]["navigate"] = "/nope"; s.write_text(json.dumps(obj), encoding="utf-8")
    assert apply_transitions(str(tmp_path))["applied"] == 1
    assert apply_transitions(str(tmp_path))["applied"] == 0


def test_editor_edges_translate_and_apply(tmp_path):
    from services.nav_apply import apply_editor_nav
    _seed(tmp_path,
          pages=[
              {"id": "orders", "route": "/orders", "schemaFile": "src/schemas/orders.json"},
              {"id": "orders/new", "route": "/orders/new", "schemaFile": "src/schemas/orders/new.json"},
          ],
          transitions=[],
          schemas={"orders.json": {"root": {"children": [
              {"type": "Button", "props": {"label": "New Order", "navigate": "/stale"}}]}},
              "orders/new.json": {"root": {}}})
    # The editor persisted an edge orders --"New Order"--> orders/new.
    nav_data = {
        "screens": [
            {"id": "s0", "data": {"route": "/orders"}},
            {"id": "s1", "data": {"route": "/orders/new"}},
        ],
        "edges": [{"id": "e1", "source": "s0", "target": "s1", "label": "New Order"}],
    }
    res = apply_editor_nav(str(tmp_path), nav_data)
    assert res["transitions"] == 1 and res["applied"] == 1
    btn = _schema(tmp_path, "orders.json")["root"]["children"][0]
    assert btn["props"]["navigate"] == "/orders/new"


def test_round_trip_build_then_apply_is_stable(tmp_path):
    from services.nav_transitions import build_transitions
    _seed(tmp_path,
          pages=[
              {"id": "orders", "route": "/orders", "schemaFile": "src/schemas/orders.json"},
              {"id": "orders/new", "route": "/orders/new", "schemaFile": "src/schemas/orders/new.json"},
          ],
          transitions=[],
          schemas={"orders.json": {"root": {"children": [
              {"type": "Button", "props": {"label": "New Order", "navigate": "/orders/new"}}]}},
              "orders/new.json": {"root": {}}})
    build_transitions(str(tmp_path))          # derive transitions from schema
    assert apply_transitions(str(tmp_path))["applied"] == 0   # apply is a no-op (already consistent)
