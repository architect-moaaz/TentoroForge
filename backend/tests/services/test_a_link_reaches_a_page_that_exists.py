"""A list row that links to /admin/categories/<id> needs an [id] page behind it.
UAT F&B: the page was never built and the link showed the 404 page under 200."""
import json
import logging

from services.link_target_guard import ensure_links_resolve


def _write(tmp_path, rel, doc):
    p = tmp_path / "src/schemas" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc))
    return p


def _app(tmp_path, *, with_detail=False, href="/admin/categories/{{id}}"):
    (tmp_path / "src/contracts").mkdir(parents=True)
    (tmp_path / "src/contracts/registry.json").write_text(json.dumps({"entities": {
        "Category": {"fields": [{"name": "id", "type": "uuid"}, {"name": "name", "type": "text"},
                                {"name": "sortOrder", "type": "integer"}]}}}))
    _write(tmp_path, "admin/categories.json", {
        "route": "/admin/categories",
        "dataSources": [{"name": "categories", "entity": "Category", "op": "list"}],
        "root": {"type": "Table", "props": {"rows": "{{categories}}", "rowHref": href,
                                            "rowActions": [{"label": "Open", "navigate": href}]}}})
    _write(tmp_path, "admin/categories/new.json", {"route": "/admin/categories/new", "root": {"type": "Form"}})
    if with_detail:
        _write(tmp_path, "admin/categories/[id].json", {"route": "/admin/categories/[id]", "root": {"type": "Stack"}})


def test_a_row_link_to_a_missing_id_page_gets_that_page_built(tmp_path):
    _app(tmp_path)
    r = ensure_links_resolve(str(tmp_path))
    assert r["created"] == ["/admin/categories/[id]"]
    assert r["removed"] == [] and r["findings"] == []
    page = json.loads((tmp_path / "src/schemas/admin/categories/[id].json").read_text())
    assert page["dataSources"][0]["op"] == "get" and page["dataSources"][0]["entity"] == "Category"
    # its own links point at real routes: Back at the list, no dead Edit
    blob = json.dumps(page)
    assert '"navigate": "/admin/categories"' in blob and "/edit" not in blob
    # the link itself is untouched — it now resolves
    lst = json.loads((tmp_path / "src/schemas/admin/categories.json").read_text())
    assert lst["root"]["props"]["rowHref"] == "/admin/categories/{{id}}"


def test_links_to_pages_that_exist_have_no_finding(tmp_path):
    _app(tmp_path, with_detail=True)
    before = (tmp_path / "src/schemas/admin/categories.json").read_text()
    r = ensure_links_resolve(str(tmp_path))
    assert r == {"created": [], "repointed": [], "removed": [], "findings": []}
    assert (tmp_path / "src/schemas/admin/categories.json").read_text() == before


def test_a_link_nothing_can_answer_is_removed_and_named(tmp_path, caplog):
    _app(tmp_path, href="/dine-in/{{id}}")
    with caplog.at_level(logging.WARNING, logger="services.link_target_guard"):
        r = ensure_links_resolve(str(tmp_path))
    assert {x["target"] for x in r["removed"]} == {"/dine-in/{{id}}"}
    assert {x["link"] for x in r["removed"]} == {"rowHref", "navigate"}
    assert any("/dine-in/{{id}}" in m and "admin/categories.json" in m for m in caplog.messages)


def test_rerun_is_idempotent(tmp_path):
    _app(tmp_path)
    ensure_links_resolve(str(tmp_path))
    snap = {p: p.read_text() for p in (tmp_path / "src/schemas").rglob("*.json")}
    r = ensure_links_resolve(str(tmp_path))
    assert r == {"created": [], "repointed": [], "removed": [], "findings": []}
    assert {p: p.read_text() for p in (tmp_path / "src/schemas").rglob("*.json")} == snap
