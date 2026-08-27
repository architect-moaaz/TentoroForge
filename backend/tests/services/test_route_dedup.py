"""Tests for services.route_dedup — one user job, one route."""
from __future__ import annotations

import json
from pathlib import Path

from services.binding_validator import _read_schema_tables, _SlugResolver
from services.route_dedup import dedupe_routes, page_signature


def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _mk_app(tmp_path: Path, *, schemas: dict[str, dict],
            plan: dict | None = None, tables: list[str] = ("documents",),
            nav_flow: dict | None = None) -> Path:
    root = tmp_path / "app"
    lines = [f'export const {t} = pgTable("{t}", {{ id: uuid("id").primaryKey() }});'
             for t in tables]
    _write(root, "src/db/schema/entities.ts", "\n".join(lines))
    _write(root, "src/contracts/plan.json", json.dumps(plan or {}))
    _write(root, "src/contracts/nav-flow.json",
           json.dumps(nav_flow or {"pages": [], "transitions": []}))
    for rel, doc in schemas.items():
        _write(root, f"src/schemas/{rel}", json.dumps(doc))
    return root


def _resolver(root: Path) -> _SlugResolver:
    return _SlugResolver(_read_schema_tables(str(root)))


def _form_page(entity: str = "Document") -> dict:
    return {"root": {"type": "Stack", "children": [
        {"type": "Form", "props": {"entity": entity, "fields": []}}]}}


def _list_page() -> dict:
    return {"dataSources": [{"name": "documents", "entity": "Document", "op": "list"}],
            "root": {"type": "Stack", "children": [
                {"type": "Table", "props": {"rows": "{{documents}}", "columns": []}}]}}


def _read(root: Path, rel: str) -> dict:
    return json.loads((root / "src/schemas" / rel).read_text())


# ── signatures ───────────────────────────────────────────────────────

def test_signature_create_vs_list_vs_detail(tmp_path: Path):
    root = _mk_app(tmp_path, schemas={})
    r = _resolver(root)
    assert page_signature("/documents/new", _form_page(), r) == ("documents", "create")
    assert page_signature("/documents", _list_page(), r) == ("documents", "list")
    detail = {"dataSources": [{"name": "doc", "entity": "Document", "op": "get"}],
              "root": {"type": "Stack", "children": []}}
    assert page_signature("/documents/[id]", detail, r) == ("documents", "detail")


def test_signature_search_beats_create(tmp_path: Path):
    """A search page contains inputs too — search must win the tie."""
    root = _mk_app(tmp_path, schemas={})
    page = {"dataSources": [{"name": "documents", "entity": "Document", "op": "list"}],
            "root": {"type": "Stack", "children": [
                {"type": "SearchInput", "props": {}},
                {"type": "Form", "props": {"entity": "Document"}}]}}
    assert page_signature("/find", page, _resolver(root)) == ("documents", "search")


def test_signature_none_for_unclassifiable(tmp_path: Path):
    root = _mk_app(tmp_path, schemas={})
    page = {"root": {"type": "Stack", "children": [{"type": "Text", "props": {}}]}}
    assert page_signature("/about", page, _resolver(root)) is None


def test_signature_none_for_existing_redirect(tmp_path: Path):
    root = _mk_app(tmp_path, schemas={})
    page = {"root": {"type": "Stack", "children": [
        {"type": "Redirect", "props": {"to": "/documents"}}]}}
    assert page_signature("/old", page, _resolver(root)) is None


# ── the collapse ─────────────────────────────────────────────────────

def test_duplicate_create_routes_collapse(tmp_path: Path):
    """The audit case: two create surfaces for the same entity."""
    root = _mk_app(
        tmp_path,
        plan={"pages": [{"route": "/documents/upload", "kind": "create"}]},
        schemas={"documents/upload.json": _form_page(),
                 "documents/new.json": _form_page()},
    )
    rep = dedupe_routes(root)
    assert len(rep["collapsed"]) == 1
    c = rep["collapsed"][0]
    assert c["winner"] == "/documents/upload"   # plan-declared wins
    assert c["loser"] == "/documents/new"
    alias = _read(root, "documents/new.json")
    node = alias["root"]["children"][0]
    assert node["type"] == "Redirect"
    assert node["props"]["to"] == "/documents/upload"


def test_landing_page_never_becomes_an_alias(tmp_path: Path):
    """`/` is the front door — it never bounces. When its only peer is
    plan-declared, both are deliberate: report the conflict, delete
    neither. (Silently collapsing deliberate pages is what made three
    persona routes redirect to one screen.)"""
    root = _mk_app(
        tmp_path,
        plan={"pages": [{"route": "/documents/upload", "kind": "create"}]},
        schemas={"index.json": _form_page(),
                 "documents/upload.json": _form_page()},
    )
    rep = dedupe_routes(root)
    assert rep["collapsed"] == []
    assert rep["kept_conflicts"] == [
        {"entity": "documents", "job": "create",
         "routes": ["/", "/documents/upload"]}]
    for rel in ("index.json", "documents/upload.json"):
        assert "Redirect" not in (root / "src" / "schemas" / rel).read_text()


def test_landing_page_wins_over_undeclared_twin(tmp_path: Path):
    """An emitter-invented twin still collapses, and never into `/`."""
    root = _mk_app(
        tmp_path,
        plan={"pages": []},
        schemas={"index.json": _form_page(),
                 "documents/upload.json": _form_page()},
    )
    rep = dedupe_routes(root)
    assert rep["collapsed"][0]["winner"] == "/"
    assert rep["collapsed"][0]["loser"] == "/documents/upload"


def test_navigate_refs_repointed_to_winner(tmp_path: Path):
    linker = {"root": {"type": "Stack", "children": [
        {"type": "Button", "props": {"label": "Add",
                                     "onClick": {"action": "navigate",
                                                 "target": "/documents/new"}}},
        {"type": "Button", "props": {"label": "Go", "navigate": "/documents/new"}},
    ]}}
    root = _mk_app(
        tmp_path,
        plan={"pages": [{"route": "/documents/upload", "kind": "create"}]},
        schemas={"documents/upload.json": _form_page(),
                 "documents/new.json": _form_page(),
                 "documents.json": linker},
    )
    rep = dedupe_routes(root)
    assert rep["collapsed"][0]["repointed_refs"] == 2
    doc = _read(root, "documents.json")
    kids = doc["root"]["children"]
    assert kids[0]["props"]["onClick"]["target"] == "/documents/upload"
    assert kids[1]["props"]["navigate"] == "/documents/upload"


def test_distinct_jobs_not_collapsed(tmp_path: Path):
    """list + create + detail for one entity are three REASONS — keep all."""
    root = _mk_app(
        tmp_path,
        schemas={"documents.json": _list_page(),
                 "documents/new.json": _form_page(),
                 "documents/[id].json": {
                     "dataSources": [{"name": "doc", "entity": "Document", "op": "get"}],
                     "root": {"type": "Stack", "children": []}}},
    )
    assert dedupe_routes(root)["collapsed"] == []


def test_different_entities_not_collapsed(tmp_path: Path):
    root = _mk_app(
        tmp_path, tables=["documents", "users"],
        schemas={"documents/new.json": _form_page("Document"),
                 "users/new.json": _form_page("User")},
    )
    assert dedupe_routes(root)["collapsed"] == []


def test_rerun_is_idempotent(tmp_path: Path):
    root = _mk_app(
        tmp_path,
        plan={"pages": [{"route": "/documents/upload", "kind": "create"}]},
        schemas={"documents/upload.json": _form_page(),
                 "documents/new.json": _form_page()},
    )
    dedupe_routes(root)
    rep2 = dedupe_routes(root)
    assert rep2["collapsed"] == []          # alias no longer classifies
    node = _read(root, "documents/new.json")["root"]["children"][0]
    assert node["props"]["to"] == "/documents/upload"


def test_report_written(tmp_path: Path):
    root = _mk_app(
        tmp_path,
        schemas={"documents/upload.json": _form_page(),
                 "documents/new.json": _form_page()},
    )
    dedupe_routes(root)
    rep = json.loads((root / "contracts" / "route-dedup.json").read_text())
    assert len(rep["collapsed"]) == 1


def test_empty_app_no_crash(tmp_path: Path):
    assert dedupe_routes(tmp_path / "nope")["collapsed"] == []


# ══════════════════════════════════════════════════════════════════
# Plan authority — the reconciler removes emitter accidents, never
# pages the plan deliberately asked for (live: /staffs and /viewers
# were replaced by Redirects to /admins, and /products/new by a
# Redirect to /suppliers/new, on 5u9du8jt).
# ══════════════════════════════════════════════════════════════════

def _persona_list(name: str) -> dict:
    """Three persona-scoped views over the SAME entity — identical
    signature (users/list), three deliberate pages."""
    return {"dataSources": [{"name": "users", "entity": "User", "op": "list"}],
            "root": {"type": "Stack", "children": [
                {"type": "Heading", "props": {"content": name}},
                {"type": "Table", "props": {"rows": "{{users}}", "columns": []}}]}}


def test_plan_declared_peers_never_collapse(tmp_path):
    """Two routes the plan asked for stay two routes, even with the
    same (entity, job) signature."""
    root = _mk_app(
        tmp_path,
        tables=["users"],
        schemas={"admins.json": {"route": "/admins", **_persona_list("Admins")},
                 "staffs.json": {"route": "/staffs", **_persona_list("Staff")},
                 "viewers.json": {"route": "/viewers", **_persona_list("Viewers")}},
        plan={"pages": [{"route": "/admins"}, {"route": "/staffs"},
                        {"route": "/viewers"}]},
    )
    report = dedupe_routes(root)
    assert report["collapsed"] == []
    for rel in ("admins.json", "staffs.json", "viewers.json"):
        doc = json.loads((root / "src" / "schemas" / rel).read_text())
        assert "Redirect" not in json.dumps(doc), f"{rel} was collapsed"


def test_undeclared_duplicate_still_collapses_into_plan_route(tmp_path):
    """The pass keeps its teeth: an emitter-invented twin of a planned
    page is still collapsed, and the planned route wins."""
    root = _mk_app(
        tmp_path,
        tables=["users"],
        schemas={"admins.json": {"route": "/admins", **_persona_list("Admins")},
                 "users-list.json": {"route": "/users-list", **_persona_list("Users")}},
        plan={"pages": [{"route": "/admins"}]},
    )
    report = dedupe_routes(root)
    assert [(c["loser"], c["winner"]) for c in report["collapsed"]] == \
        [("/users-list", "/admins")]
    kept = json.loads((root / "src" / "schemas" / "admins.json").read_text())
    assert "Redirect" not in json.dumps(kept)


def test_create_page_entity_is_its_own_subject_not_dropdown_feeds(tmp_path):
    """A Product create form loads suppliers+categories to populate its
    FK selects. Those dataSources describe the DROPDOWNS, not the page's
    subject — signature must be (product, create), never (supplier, …)."""
    root = _mk_app(
        tmp_path,
        tables=["products", "suppliers", "categories"],
        schemas={"products/new.json": {
            "route": "/products/new",
            "dataSources": [
                {"name": "suppliers", "entity": "Supplier", "op": "list"},
                {"name": "categories", "entity": "Category", "op": "list"}],
            "root": {"type": "Stack", "children": [
                {"type": "Form", "props": {"entity": "Product", "fields": []}}]}}},
    )
    sig = page_signature("/products/new", json.loads(
        (root / "src" / "schemas" / "products" / "new.json").read_text()), _resolver(root))
    assert sig is not None and sig[1] == "create"
    assert sig[0] == "products", f"create page attributed to {sig[0]!r}"


def test_distinct_entity_create_pages_never_group(tmp_path):
    """/products/new and /suppliers/new are different jobs for different
    entities — they must never share a signature (live: both collapsed
    into /suppliers/new, so 'Add Product' opened the supplier form)."""
    prod = {"route": "/products/new",
            "dataSources": [{"name": "suppliers", "entity": "Supplier", "op": "list"}],
            "root": {"type": "Stack", "children": [
                {"type": "Form", "props": {"entity": "Product", "fields": []}}]}}
    supp = {"route": "/suppliers/new",
            "root": {"type": "Stack", "children": [
                {"type": "Form", "props": {"entity": "Supplier", "fields": []}}]}}
    root = _mk_app(tmp_path, tables=["products", "suppliers"],
                   schemas={"products/new.json": prod, "suppliers/new.json": supp},
                   plan={"pages": []})
    report = dedupe_routes(root)
    assert report["collapsed"] == []
    doc = json.loads((root / "src" / "schemas" / "products" / "new.json").read_text())
    assert "Redirect" not in json.dumps(doc)
