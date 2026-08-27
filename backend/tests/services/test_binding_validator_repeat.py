"""What counts as a Repeat that names its collection.

Why this test exists
--------------------
`repeat_missing_source` was the single most common binding error in the live
corpus — 118 hits, and 7 of the 9 errors on the most recent build. The message
said the node "declares no `bind`/`source` prop"; the node it fired on read

    {"type": "Repeat", "props": {"as": "order", "bind": "draftOrders"}}

which plainly declares one. The rule read `bind` off the NODE only, and its
synonym list — items/data/rows/dataSource — omitted `bind`, so it could not
even hint at the real mistake. Anyone reading the report saw a bind prop and a
message denying a bind prop existed, which is why the class sat unfixed.

The renderer now accepts props.bind and props.dataSource as aliases, so those
nodes DO render. They are still non-canonical, so they warn rather than error:
the app works, and the drift stays visible. An error is reserved for a Repeat
that genuinely names nothing, which is the only case that renders an empty list.

The fixture mirrors the real app layout — schema in `src/db/schema/*.ts` (a
DIRECTORY), page schemas under `src/schemas/**`. Getting that wrong makes the
rule silently not run and the test pass for the wrong reason, so
`test_the_rule_fires_at_all` pins it.
"""

import json
from pathlib import Path

from services.binding_validator import validate_bindings


def _app(tmp_path: Path, repeat: dict) -> str:
    root = tmp_path / "app"
    (root / "src" / "db" / "schema").mkdir(parents=True)
    (root / "src" / "schemas").mkdir(parents=True)
    (root / "workflows").mkdir(parents=True)

    (root / "src" / "db" / "schema" / "orders.ts").write_text(
        'export const orders = pgTable("orders", {\n'
        '  id: uuid("id").primaryKey().defaultRandom(),\n'
        '  ref: varchar("ref", { length: 255 }),\n'
        "});\n", encoding="utf-8")

    (root / "src" / "schemas" / "orders.json").write_text(json.dumps({
        "schemaVersion": "2", "id": "orders", "route": "/orders",
        "layout": "main",
        "dataSources": [{"name": "orders", "entity": "Order", "op": "list"}],
        "root": {"type": "Stack", "props": {}, "children": [repeat]},
    }), encoding="utf-8")
    return str(root)


def _kinds(res: dict, bucket: str) -> list:
    return [e["kind"] for e in res[bucket]]


def _repeat(**node) -> dict:
    node.setdefault("type", "Repeat")
    node.setdefault("children", [{"type": "Text", "props": {"content": "{{order.ref}}"}}])
    return node


# ── the error case: nothing names a collection ──────────────────────────────

def test_the_rule_fires_at_all(tmp_path):
    """Fixture guard — a Repeat naming nothing must still be an error."""
    res = validate_bindings(_app(tmp_path, _repeat(props={"as": "order"})))
    assert "repeat_missing_source" in _kinds(res, "errors")


def test_a_dead_prop_is_named_in_the_message(tmp_path):
    """`props.items` is read by nothing. The message must say which prop it
    found, not describe the node as having no props at all."""
    res = validate_bindings(_app(tmp_path, _repeat(props={"items": "orders"})))
    err = next(e for e in res["errors"] if e["kind"] == "repeat_missing_source")
    assert err["ref"] == "items"
    assert "props.items" in err["detail"]


# ── the canonical shapes: silent ─────────────────────────────────────────────

def test_node_level_bind_is_clean(tmp_path):
    res = validate_bindings(_app(tmp_path, _repeat(bind="orders", props={"as": "order"})))
    assert "repeat_missing_source" not in _kinds(res, "errors")
    assert "repeat_alias_source" not in _kinds(res, "warnings")


def test_props_source_is_clean(tmp_path):
    res = validate_bindings(_app(tmp_path, _repeat(props={"source": "orders"})))
    assert "repeat_missing_source" not in _kinds(res, "errors")
    assert "repeat_alias_source" not in _kinds(res, "warnings")


# ── the alias shapes: render, but warn ───────────────────────────────────────

def test_props_bind_warns_and_does_not_error(tmp_path):
    """The 55-node shape, and the exact one this rule used to mis-report."""
    res = validate_bindings(_app(tmp_path, _repeat(props={"bind": "orders"})))
    assert "repeat_missing_source" not in _kinds(res, "errors")
    assert "repeat_alias_source" in _kinds(res, "warnings")


def test_props_datasource_warns_and_does_not_error(tmp_path):
    """The 18-node shape our own component exemplar used to teach."""
    res = validate_bindings(_app(tmp_path, _repeat(props={"dataSource": "orders"})))
    assert "repeat_missing_source" not in _kinds(res, "errors")
    assert "repeat_alias_source" in _kinds(res, "warnings")


def test_a_mustache_wrapped_name_resolves_against_the_registry(tmp_path):
    """43 of the 55 are written `{{orders}}`. The braces are binding syntax
    the renderer's interpolation pass resolves; the registry check must
    compare the bare name or every one of them looks unresolvable."""
    res = validate_bindings(_app(tmp_path, _repeat(props={"bind": "{{orders}}"})))
    assert "binding_unresolved" not in _kinds(res, "errors")


# ── the resolve check still bites ────────────────────────────────────────────

def test_a_name_matching_no_datasource_is_still_unresolved(tmp_path):
    res = validate_bindings(_app(tmp_path, _repeat(bind="ghosts")))
    assert "binding_unresolved" in _kinds(res, "errors")


def test_canonical_wins_over_a_stale_alias(tmp_path):
    """A node carrying both must be judged on the one the renderer uses."""
    res = validate_bindings(
        _app(tmp_path, _repeat(bind="orders", props={"dataSource": "ghosts"})))
    assert "binding_unresolved" not in _kinds(res, "errors")
    assert "repeat_alias_source" not in _kinds(res, "warnings")
