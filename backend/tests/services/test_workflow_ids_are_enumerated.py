"""A control can only name a workflow the application actually has.

The composer was told, in prose, which workflows a screen launches and to "put
the id in `workflow` on the Button or Form that runs it". It wrote
`createDocument`, `save_draft`, `raise`, `mark_read` — plausible names for real
intentions, none of them an id — and five pages were refused for naming a
workflow the application does not define.

It was not disobeying a constraint. The catalog typed `workflow` as
DynamicString, so any string was schema-valid and prose lost to schema.
"""
from __future__ import annotations

import json

from services.a2ui_catalog import build_a2ui_catalog

IDS = ["FLOW-001", "FLOW-010", "FLOW-020"]


def _component(catalog: dict, name: str) -> dict:
    stack = [catalog]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            const = (node.get("properties") or {}).get("component") or {}
            if isinstance(const, dict) and const.get("const") == name:
                return node
            stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
        elif isinstance(node, list):
            stack.extend(x for x in node if isinstance(x, (dict, list)))
    raise AssertionError(f"{name} is not in the catalog")


def test_a_control_may_only_name_a_real_workflow():
    cat = build_a2ui_catalog(workflows=IDS)
    for comp in ("Button", "Form"):
        assert _component(cat, comp)["properties"]["workflow"]["enum"] == IDS


def test_the_nested_ones_are_constrained_too():
    """`Table.bulkActions[].workflow` and `rowActions[].workflow` dispatch the
    same way and come from the contract verbatim, so a fix that only reached
    the top level would leave the commonest table action free text."""
    table = _component(build_a2ui_catalog(workflows=IDS), "Table")
    for nested in ("bulkActions", "rowActions"):
        blob = json.dumps(table["properties"][nested])
        assert "FLOW-010" in blob, f"{nested}.workflow is still free text"


def test_an_invented_name_is_no_longer_expressible():
    """The whole point: A2UI validates its own output against this catalog, so
    the id it cannot write is caught and retried inside the composer rather
    than refusing the page three minutes later."""
    allowed = _component(build_a2ui_catalog(workflows=IDS), "Button")
    assert "createDocument" not in allowed["properties"]["workflow"]["enum"]


def test_a_caller_with_no_application_gets_the_catalog_it_always_got():
    """`build_a2ui_catalog()` is called without an application in tests and in
    the catalog-emitting script; enumerating nothing must not empty the prop."""
    plain = _component(build_a2ui_catalog(), "Button")["properties"]["workflow"]
    assert "enum" not in plain
    assert "DynamicString" in json.dumps(plain)


def test_the_composer_is_handed_the_application_s_ids():
    import inspect

    from services import a2ui_authority

    src = inspect.getsource(a2ui_authority.compose_page_via_a2ui)
    assert "workflows=[" in src, "the ids never reach _mcp_surface"
    assert "write_a2ui_catalog" in inspect.getsource(a2ui_authority._mcp_surface)


def test_it_is_the_applications_ids_not_the_pages():
    """The per-page set is narrower and is what the domain context names, but
    the catalog is one document shared by every page in a run — the cached
    prefix. Enumerating per page would rebuild it once per page and lose the
    cache to buy a narrowing prose already does."""
    import inspect

    from services import a2ui_authority

    src = inspect.getsource(a2ui_authority.compose_page_via_a2ui)
    assert 'registry.get("workflows")' in src
