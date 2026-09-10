"""peer_shape_analyzer — flag pages whose dataSource shape diverges from
their archetype peers. The exact class of bug the Drive-detail issue was:
three sibling detail pages used ``{op:get}`` bare; the Drive page had an
extra ``filter`` clause that broke its fetch."""
from __future__ import annotations

import json
from pathlib import Path

from services.peer_shape_analyzer import find_peer_shape_inconsistencies, to_dict


def _write(root: Path, rel: str, doc: dict) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")


def test_drive_detail_bug_shape_detected(tmp_path):
    """The canonical case: three detail pages share ``{op:get}``, one
    has ``{op:get, filter:{...}}`` — the odd one gets flagged."""
    _write(tmp_path, "src/schemas/applications/[id].json", {
        "route": "/applications/[id]",
        "dataSources": [{"name": "application", "entity": "Application", "op": "get"}],
    })
    _write(tmp_path, "src/schemas/pipeline/[id].json", {
        "route": "/pipeline/[id]",
        "dataSources": [{"name": "application", "entity": "Application", "op": "get"}],
    })
    _write(tmp_path, "src/schemas/candidate/applications/[id].json", {
        "route": "/candidate/applications/[id]",
        "dataSources": [{"name": "application", "entity": "Application", "op": "get"}],
    })
    _write(tmp_path, "src/schemas/drives/[id].json", {
        "route": "/drives/[id]",
        "dataSources": [{
            "name": "drive", "entity": "Drive", "op": "get",
            "filter": {"field": "id", "op": "eq", "value": "{{params.id}}"},
        }],
    })
    pages = [
        {"route": "/applications/[id]",           "path": "src/schemas/applications/[id].json",           "archetype": "detail"},
        {"route": "/pipeline/[id]",               "path": "src/schemas/pipeline/[id].json",               "archetype": "detail"},
        {"route": "/candidate/applications/[id]", "path": "src/schemas/candidate/applications/[id].json", "archetype": "detail"},
        {"route": "/drives/[id]",                 "path": "src/schemas/drives/[id].json",                 "archetype": "detail"},
    ]

    result = find_peer_shape_inconsistencies(pages, str(tmp_path))
    assert len(result) == 1
    inc = result[0]
    assert inc.route == "/drives/[id]"
    assert inc.op == "get"
    assert "filter" in inc.observed_shape
    assert "filter" not in inc.peer_shape
    # Rationale names the divergence + the peer pages Smith can compare to.
    assert "filter" in inc.rationale
    assert "/applications/[id]" in inc.rationale or \
           "/pipeline/[id]" in inc.rationale


def test_all_pages_same_shape_produces_no_signal(tmp_path):
    """When every page has the same (possibly weird) shape, there's no
    signal to say it's wrong — nothing flagged."""
    for i, route in enumerate(["/a/[id]", "/b/[id]", "/c/[id]", "/d/[id]"]):
        _write(tmp_path, f"src/schemas/{route.strip('/').replace('[id]', 'x')}.json", {
            "route": route,
            "dataSources": [{"name": "x", "entity": "X", "op": "get", "filter": {}}],
        })
    pages = [
        {"route": r, "path": f"src/schemas/{r.strip('/').replace('[id]', 'x')}.json",
         "archetype": "detail"}
        for r in ["/a/[id]", "/b/[id]", "/c/[id]", "/d/[id]"]
    ]
    assert find_peer_shape_inconsistencies(pages, str(tmp_path)) == []


def test_fewer_than_three_peers_skipped(tmp_path):
    """Two detail pages don't give a reliable mode — silence is safer
    than flagging one as anomalous."""
    _write(tmp_path, "src/schemas/a/[id].json", {"dataSources": [{"op": "get"}]})
    _write(tmp_path, "src/schemas/b/[id].json",
           {"dataSources": [{"op": "get", "filter": {}}]})
    pages = [
        {"route": "/a/[id]", "path": "src/schemas/a/[id].json", "archetype": "detail"},
        {"route": "/b/[id]", "path": "src/schemas/b/[id].json", "archetype": "detail"},
    ]
    assert find_peer_shape_inconsistencies(pages, str(tmp_path)) == []


def test_50_50_split_produces_no_signal(tmp_path):
    """A 2-vs-2 split has no modal shape — anything reads as "different"
    from something. Silent."""
    for i, (r, has_filter) in enumerate([
        ("/a/[id]", False), ("/b/[id]", False),
        ("/c/[id]", True),  ("/d/[id]", True),
    ]):
        ds = {"op": "get"}
        if has_filter:
            ds["filter"] = {}
        _write(tmp_path, f"src/schemas/{r.strip('/').replace('[id]', 'x')}.json",
               {"dataSources": [ds]})
    pages = [
        {"route": r, "path": f"src/schemas/{r.strip('/').replace('[id]', 'x')}.json",
         "archetype": "detail"}
        for r, _ in [("/a/[id]", False), ("/b/[id]", False),
                     ("/c/[id]", True),  ("/d/[id]", True)]
    ]
    assert find_peer_shape_inconsistencies(pages, str(tmp_path)) == []


def test_archetypes_grouped_separately(tmp_path):
    """A list page's shape is compared to other list pages, not to
    detail pages. A detail page with ``{op:get, filter}`` amongst list
    pages with ``{op:list, filter}`` should NOT be flagged as odd."""
    for r, arch, op in [
        ("/xs",          "list",   "list"),
        ("/ys",          "list",   "list"),
        ("/zs",          "list",   "list"),
        ("/xs/[id]",     "detail", "get"),
        ("/ys/[id]",     "detail", "get"),
        ("/zs/[id]",     "detail", "get"),
    ]:
        _write(tmp_path, f"src/schemas/{r.strip('/').replace('[id]', 'x') or 'root'}.json",
               {"dataSources": [{"op": op}]})
    pages = [
        {"route": r, "path": f"src/schemas/{r.strip('/').replace('[id]', 'x') or 'root'}.json",
         "archetype": arch}
        for r, arch, _ in [
            ("/xs",       "list",   "list"),
            ("/ys",       "list",   "list"),
            ("/zs",       "list",   "list"),
            ("/xs/[id]",  "detail", "get"),
            ("/ys/[id]",  "detail", "get"),
            ("/zs/[id]",  "detail", "get"),
        ]
    ]
    assert find_peer_shape_inconsistencies(pages, str(tmp_path)) == []


def test_missing_key_also_flagged(tmp_path):
    """The 'peer has X we don't' direction too — three pages have
    ``{op:list, filter}``, one has just ``{op:list}``. That divergent
    page is flagged as MISSING a key rather than having an extra."""
    for r in ["/a", "/b", "/c"]:
        _write(tmp_path, f"src/schemas{r}.json",
               {"dataSources": [{"op": "list", "filter": {}}]})
    _write(tmp_path, "src/schemas/d.json",
           {"dataSources": [{"op": "list"}]})
    pages = [
        {"route": r, "path": f"src/schemas{r}.json", "archetype": "list"}
        for r in ["/a", "/b", "/c", "/d"]
    ]
    result = find_peer_shape_inconsistencies(pages, str(tmp_path))
    assert len(result) == 1
    assert result[0].route == "/d"
    assert "missing" in result[0].rationale.lower()


def test_to_dict_produces_json_safe_shape():
    from services.peer_shape_analyzer import ShapeInconsistency
    items = [ShapeInconsistency(
        route="/drives/[id]",
        schema_path="src/schemas/drives/[id].json",
        archetype="detail",
        data_source_name="drive",
        op="get",
        observed_shape=["entity", "filter", "name", "op"],
        peer_shape=["entity", "name", "op"],
        peer_pages=["/applications/[id]"],
        rationale="…",
    )]
    payload = to_dict(items)
    assert payload[0]["route"] == "/drives/[id]"
    assert payload[0]["observed_shape"] == ["entity", "filter", "name", "op"]
    assert payload[0]["peer_pages"] == ["/applications/[id]"]
