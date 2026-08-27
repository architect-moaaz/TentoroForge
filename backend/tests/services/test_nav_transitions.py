"""nav-flow.transitions built authoritatively from generated schemas + auth flow."""
import json

from services.nav_transitions import build_transitions


def _seed(tmp_path, pages, schemas, **navtop):
    c = tmp_path / "src" / "contracts"
    c.mkdir(parents=True, exist_ok=True)
    (c / "nav-flow.json").write_text(json.dumps({"pages": pages, **navtop}))
    for rel, obj in schemas.items():
        p = tmp_path / "src" / "schemas" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj))


def _read(tmp_path):
    return json.loads((tmp_path / "src/contracts/nav-flow.json").read_text())["transitions"]


def test_button_navigate_becomes_transition(tmp_path):
    _seed(tmp_path,
          pages=[
              {"id": "orders", "route": "/orders", "schemaFile": "src/schemas/orders.json"},
              {"id": "orders/new", "route": "/orders/new", "schemaFile": "src/schemas/orders/new.json"},
          ],
          schemas={
              "orders.json": {"root": {"children": [
                  {"type": "Button", "props": {"label": "New Order", "navigate": "/orders/new"}}]}},
              "orders/new.json": {"root": {}},
          })
    build_transitions(str(tmp_path))
    tr = _read(tmp_path)
    assert any(t["from"] == "orders" and t["to"] == "orders/new"
               and t["trigger"] == "button:New Order" for t in tr)


def test_row_href_resolves_to_detail_page(tmp_path):
    _seed(tmp_path,
          pages=[
              {"id": "orders", "route": "/orders", "schemaFile": "src/schemas/orders.json"},
              {"id": "orders/[id]", "route": "/orders/[id]", "schemaFile": "src/schemas/orders/[id].json"},
          ],
          schemas={
              "orders.json": {"root": {"children": [
                  {"type": "Table", "props": {"rowHref": "/orders/{{id}}"}}]}},
              "orders/[id].json": {"root": {}},
          })
    build_transitions(str(tmp_path))
    tr = _read(tmp_path)
    assert any(t["from"] == "orders" and t["to"] == "orders/[id]" for t in tr)


def test_auth_flow_edges_added_when_gated(tmp_path):
    _seed(tmp_path,
          pages=[
              {"id": "login", "route": "/login", "schemaFile": "src/schemas/login.json"},
              {"id": "signup", "route": "/signup", "schemaFile": "src/schemas/signup.json"},
              {"id": "orders", "route": "/orders", "schemaFile": "src/schemas/orders.json"},
          ],
          schemas={"login.json": {"root": {}}, "signup.json": {"root": {}}, "orders.json": {"root": {}}},
          authGated=True, post_login_redirect="/orders")
    build_transitions(str(tmp_path))
    tr = _read(tmp_path)
    pairs = {(t["from"], t["to"]) for t in tr}
    assert ("login", "signup") in pairs and ("signup", "login") in pairs
    assert ("login", "orders") in pairs                       # post-login entry
    assert any(t["from"] == "login" and t["to"] == "orders" and t["navType"] == "redirect" for t in tr)


def test_unresolvable_target_skipped(tmp_path):
    _seed(tmp_path,
          pages=[{"id": "orders", "route": "/orders", "schemaFile": "src/schemas/orders.json"}],
          schemas={"orders.json": {"root": {"children": [
              {"type": "Button", "props": {"label": "X", "navigate": "/ghost"}}]}}})
    build_transitions(str(tmp_path))
    assert _read(tmp_path) == []


def test_idempotent(tmp_path):
    _seed(tmp_path,
          pages=[
              {"id": "a", "route": "/a", "schemaFile": "src/schemas/a.json"},
              {"id": "b", "route": "/b", "schemaFile": "src/schemas/b.json"},
          ],
          schemas={
              "a.json": {"root": {"children": [{"type": "Button", "props": {"label": "Go", "navigate": "/b"}}]}},
              "b.json": {"root": {}},
          })
    r1 = build_transitions(str(tmp_path))["transitions"]
    r2 = build_transitions(str(tmp_path))["transitions"]
    assert r1 == r2 == 1
