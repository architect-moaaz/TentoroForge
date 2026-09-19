"""Image vector search — a record found by what its picture looks like.

A Blueprint field ``{"type": "vector", "embedding": {"of": "photo"}}`` is the
whole declaration. From it:

* the data layer emits a pgvector column with an HNSW index, and a manifest
  that tells the Data Engine which column to fill from which field;
* the pages ask for the picture with an upload, never for the vector, and a
  collection page gains a "Find similar" whose upload writes the page's query;
* a page source ``op: "similar"`` is refused when there is nothing to rank by
  or nothing to ask with, saying which.

The runtime half — filling on write and ranking on read against a real
pgvector — is ``templates/runtime/__tests__/resolve-similar.test.mts``.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from services.blueprint import projection
from services.blueprint.embeddings import (
    EMBEDDING_DIMENSIONS, embedding_columns, unfillable_embeddings,
)
from services.blueprint.functional_completeness import functional_findings, similar_findings
from services.blueprint.page_planner import form_fields_for
from services.blueprint.template_page import template_layout
from services.blueprint.verification import check_api_database

BACKEND = Path(__file__).resolve().parents[2]
CONTRACT = json.loads((BACKEND / "contracts" / "blueprint.schema.json").read_text())
CATALOG = json.loads((BACKEND / "contracts" / "component-catalog.json").read_text())


def _product(**extra_fields) -> dict:
    fields = [
        {"name": "id", "type": "uuid", "primaryKey": True},
        {"name": "name", "type": "text", "required": True},
        {"name": "photo", "type": "image", "required": True},
        {"name": "photoEmbedding", "type": "vector", "embedding": {"of": "photo"}},
    ]
    return {"id": "ENTITY-001", "name": "Product", "table": "products",
            "labelField": "name", "fields": fields, **extra_fields}


def _doc(entity: dict | None = None) -> dict:
    entity = entity or _product()
    create = {"id": "WF-001", "name": "Add product", "trigger": {"kind": "manual"},
              "inputs": [{"name": "name", "type": "text"}, {"name": "photo", "type": "image"}],
              "steps": [{"key": "insert", "name": "Insert", "type": "action", "entity": "ENTITY-001",
                         "config": {"actionType": "db_insert", "table": "products",
                                    "values": {"name": "{{name}}", "photo": "{{photo}}"}}}]}
    pages = [
        {"id": "PAGE-001", "route": "/products", "name": "Products", "pattern": "entity_list",
         "data": {"primaryEntity": "ENTITY-001"}, "requirements": [], "users": []},
        {"id": "PAGE-002", "route": "/products/new", "name": "New product", "pattern": "entity_form",
         "data": {"primaryEntity": "ENTITY-001"}, "requirements": [], "users": []},
    ]
    return {"data": {"entities": [entity], "relationships": []}, "workflows": [create],
            "pages": pages, "roles": [], "requirements": [], "widgets": []}


def _errors(instance, schema) -> list:
    """Validate against a sub-schema whose `$ref`s point into the whole contract."""
    return list(jsonschema.Draft202012Validator(CONTRACT).descend(instance, schema))


def _walk(node):
    if isinstance(node, dict):
        yield node
        for child in node.get("children") or []:
            yield from _walk(child)


# --------------------------------------------------------------------------- contract

def test_the_contract_declares_an_embedding_field():
    entity = CONTRACT["properties"]["data"]["properties"]["entities"]["items"]
    assert _errors(_product(), entity) == []


def test_an_embedding_carries_its_source_and_nothing_else():
    field = CONTRACT["properties"]["data"]["properties"]["entities"]["items"]["properties"]["fields"]["items"]
    assert _errors({"name": "v", "type": "vector", "embedding": {}}, field)
    # The length is the platform model's; a Blueprint cannot be asked for it.
    assert _errors({"name": "v", "type": "vector",
                    "embedding": {"of": "photo", "dimensions": 768}}, field)


def test_a_page_may_rank_by_similarity():
    source = CONTRACT["properties"]["pageLayouts"]["items"]["properties"]["dataSources"]["items"]
    assert _errors({"name": "productSimilar", "entity": "Product", "op": "similar",
                    "field": "photoEmbedding", "limit": 12}, source) == []


def test_the_catalog_knows_the_image_search_box_and_the_upload_field():
    comps = CATALOG.get("components") or CATALOG
    upload = comps["FileUpload"] if isinstance(comps, dict) else next(
        c for c in comps if (c.get("type") or c.get("name")) == "FileUpload")
    assert upload["props"]["properties"]["search"]["type"] == "boolean"
    form = comps["Form"] if isinstance(comps, dict) else next(
        c for c in comps if (c.get("type") or c.get("name")) == "Form")
    kinds = json.dumps(form["props"]["properties"]["fields"])
    assert '"const": "file"' in kinds


# --------------------------------------------------------------------------- data layer

def test_the_column_is_a_nullable_vector_of_the_platforms_length():
    line, builder = projection.drizzle_column({"name": "photoEmbedding", "type": "vector",
                                               "required": True, "embedding": {"of": "photo"}})
    assert builder == "vector"
    assert line == f'photoEmbedding: vector("photo_embedding", {{ dimensions: {EMBEDDING_DIMENSIONS} }}),'


def test_the_table_carries_an_hnsw_cosine_index():
    module = projection.emit_entity_module(_product(), _doc())
    assert "import { pgTable, index, text, uuid, vector }" in module
    assert ('index("products_photo_embedding_hnsw")'
            '.using("hnsw", t.photoEmbedding.op("vector_cosine_ops"))') in module
    assert module.rstrip().endswith("]);")


def test_a_table_without_an_embedding_is_emitted_as_before():
    plain = {"id": "ENTITY-002", "name": "Note", "table": "notes",
             "fields": [{"name": "id", "type": "uuid", "primaryKey": True},
                        {"name": "body", "type": "text"}]}
    module = projection.emit_entity_module(plain, {"data": {"entities": [plain]}})
    assert "index" not in module and module.rstrip().endswith("});")


def test_a_required_image_is_required_of_the_form_not_the_column():
    line, _ = projection.drizzle_column({"name": "photo", "type": "image", "required": True})
    assert line == 'photo: text("photo"),'
    fields = form_fields_for(_product(), creating=True)
    assert {"kind": "file", "name": "photo", "label": "Photo", "required": True,
            "accept": "image/*"} in fields


def test_the_manifest_names_the_column_its_source_and_the_kind(tmp_path):
    out = projection.project_embedding_columns(_doc(), tmp_path)
    assert out["files"] == ["src/lib/embedding-columns.ts"]
    text = (tmp_path / "src/lib/embedding-columns.ts").read_text()
    assert f"export const EMBEDDING_DIMENSIONS = {EMBEDDING_DIMENSIONS};" in text
    manifest = embedding_columns(_doc())
    assert manifest["products"] == manifest["Product"] == [
        {"property": "photoEmbedding", "column": "photo_embedding", "of": "photo", "source": "image"}]


def test_the_manifest_is_written_when_nothing_is_embedded(tmp_path):
    projection.project_embedding_columns({"data": {"entities": []}}, tmp_path)
    assert "EMBEDDING_COLUMNS: Record<string, EmbeddingColumn[]> = {}" in (
        tmp_path / "src/lib/embedding-columns.ts").read_text()


def test_a_text_field_can_be_embedded_too():
    entity = _product()
    entity["fields"].append({"name": "notesEmbedding", "type": "vector", "embedding": {"of": "name"}})
    kinds = {c["property"]: c["source"] for c in embedding_columns(_doc(entity))["products"]}
    assert kinds == {"photoEmbedding": "image", "notesEmbedding": "text"}


def test_the_seed_writes_neither_a_picture_nor_a_vector(tmp_path):
    projection.project_seed(_doc(), tmp_path)
    rows = json.loads((tmp_path / "src/db/seed.json").read_text())["products"]
    assert rows and all("photo" not in r and "photoEmbedding" not in r for r in rows)


# --------------------------------------------------------------------------- pages

def test_nobody_is_shown_or_asked_for_a_vector():
    doc = _doc()
    layouts = [template_layout(doc, p) for p in doc["pages"]]
    for layout in layouts:
        text = json.dumps(layout["root"])
        assert '"photoEmbedding"' not in text or '"field": "photoEmbedding"' in json.dumps(layout["dataSources"])
        for node in _walk(layout["root"]):
            if node["type"] == "Table":
                assert "photoEmbedding" not in [c["key"] for c in node["props"]["columns"]]
            if node["type"] == "Form":
                assert "photoEmbedding" not in [f["name"] for f in node["props"]["fields"]]


def test_the_create_form_uploads_the_picture():
    doc = _doc()
    form = next(n for n in _walk(template_layout(doc, doc["pages"][1])["root"]) if n["type"] == "Form")
    photo = next(f for f in form["props"]["fields"] if f["name"] == "photo")
    assert photo["kind"] == "file" and photo["accept"] == "image/*"


def test_the_list_finds_similar_records_by_an_uploaded_image():
    doc = _doc()
    layout = template_layout(doc, doc["pages"][0])
    assert {"name": "productSimilar", "entity": "Product", "op": "similar",
            "field": "photoEmbedding", "limit": 12} in layout["dataSources"]
    box = next(n for n in _walk(layout["root"]) if n["type"] == "FileUpload")
    assert box["props"]["search"] is True and box["props"]["accept"] == "image/*"
    results = [n for n in _walk(layout["root"])
               if n["type"] == "Table" and n["props"]["data"] == "{{productSimilar}}"]
    assert len(results) == 1
    cols = results[0]["props"]["columns"]
    # Ranked, not scored: a CLIP text match near 0.3 would read as a poor one.
    assert "similarity" not in [c["key"] for c in cols]
    assert {"key": "photo", "label": "Photo", "format": "image"} in cols


def test_an_entity_without_an_embedding_gets_no_find_similar():
    entity = _product()
    entity["fields"] = [f for f in entity["fields"] if f["name"] != "photoEmbedding"]
    doc = _doc(entity)
    layout = template_layout(doc, doc["pages"][0])
    assert not [s for s in layout["dataSources"] if s["op"] == "similar"]
    assert not [n for n in _walk(layout["root"]) if n["type"] == "FileUpload"]


def test_the_composed_pages_satisfy_the_similar_rules():
    doc = _doc()
    doc["pageLayouts"] = [template_layout(doc, p) for p in doc["pages"]]
    assert not [f for f in functional_findings(doc) if f["rule"].startswith("similar-")]


# --------------------------------------------------------------------------- refusals

def _layout(root: dict, sources: list[dict]) -> dict:
    return {"page": "PAGE-001", "root": root, "dataSources": sources}


_UPLOAD = {"type": "FileUpload", "props": {"name": "image", "search": True}, "children": []}
_SIMILAR = {"name": "hits", "entity": "Product", "op": "similar", "field": "photoEmbedding"}


def test_an_image_search_box_with_nothing_to_rank_is_refused():
    found = similar_findings(_doc(), {}, _layout({"type": "Stack", "children": [_UPLOAD]}, []))
    assert [f[0] for f in found] == ["similar-without-source"]


def test_ranking_by_an_embedding_the_entity_lacks_is_refused_with_the_fix():
    entity = _product()
    entity["fields"] = [f for f in entity["fields"] if f["name"] != "photoEmbedding"]
    found = similar_findings(_doc(entity), {}, _layout({"type": "Stack", "children": [_UPLOAD]}, [_SIMILAR]))
    assert [f[0] for f in found] == ["similar-without-embedding"]
    assert '"embedding": {"of": "photo"}' in found[0][1]


def test_a_similar_source_nothing_asks_for_is_refused():
    found = similar_findings(_doc(), {}, _layout({"type": "Stack", "children": []}, [_SIMILAR]))
    assert [f[0] for f in found] == ["similar-without-query"]


def test_a_text_search_box_may_ask_a_similar_source():
    box = {"type": "Input", "props": {"type": "search", "name": "q"}, "children": []}
    doc = _doc()
    doc["pageLayouts"] = [_layout({"type": "Stack", "children": [box]}, [_SIMILAR])]
    rules = {f["rule"] for f in functional_findings(doc)}
    assert not rules & {"search-without-source", "similar-without-query"}


def test_an_embedding_of_nothing_embeddable_is_a_finding():
    entity = _product()
    entity["fields"].append({"name": "idEmbedding", "type": "vector", "embedding": {"of": "id"}})
    entity["fields"].append({"name": "ghostEmbedding", "type": "vector", "embedding": {"of": "ghost"}})
    problems = unfillable_embeddings(entity)
    assert len(problems) == 2
    assert "'ghost', which is not a field of Product" in problems[1]
    assert "only an image or a text field can be embedded" in problems[0]
    details = [f.detail for f in check_api_database(_doc(entity))]
    assert problems[0] in details and problems[1] in details
    # ...and the manifest leaves them out: nothing would ever fill them.
    assert [c["property"] for c in embedding_columns(_doc(entity))["products"]] == ["photoEmbedding"]


# --------------------------------------------------------------------------- runtime wiring

RUNTIME = BACKEND / "templates" / "runtime"
FOUNDATION = BACKEND / "templates" / "app-foundation"


def test_every_write_path_fills_embeddings():
    engine = (RUNTIME / "data-engine.ts").read_text()
    assert engine.count("await embedWrittenRow(entity.table, record") == 2       # create + update
    workflows = (RUNTIME / "workflows" / "index.ts").read_text()
    assert workflows.count("embedWrittenRow(table, ") == 3                      # insert, fan-out, update


def test_the_page_resolves_a_similar_source_from_the_url():
    page = (FOUNDATION / "src" / "lib" / "schema-page.tsx").read_text()
    assert 's.op === "similar"' in page
    assert '{ image: first("image"), text: first("q") }' in page
    # Refreshed into older apps whose bridge lacks it: looked up, not imported.
    assert "resolveSimilar" not in page.split("export async function renderSchemaPage")[0]


def test_pgvector_is_installed_before_every_push():
    reset = (FOUNDATION / "src" / "db" / "reset-schema.ts").read_text()
    assert 'import { ensureExtensions } from "./extensions";' in reset
    assert "await ensureExtensions(sql);" in reset
    from services.deploy.vercel_provider import _PLATFORM_REFRESH_FOUNDATION_FILES
    assert "src/db/extensions.ts" in _PLATFORM_REFRESH_FOUNDATION_FILES
    compose = (FOUNDATION / "docker-compose.yml").read_text()
    assert "image: pgvector/pgvector:pg16" in compose


def test_the_injector_ships_the_embedder_and_an_empty_manifest(tmp_path):
    from services.runtime_injector import inject_runtime
    inject_runtime(str(tmp_path))
    lib = tmp_path / "src" / "lib"
    assert (lib / "embeddings.ts").read_text() == (RUNTIME / "embeddings.ts").read_text()
    assert "embeddingColumnsFor(_entity: string): EmbeddingColumn[]" in (lib / "embedding-columns.ts").read_text()


def test_the_injector_keeps_a_projected_manifest(tmp_path):
    from services.runtime_injector import inject_runtime
    projection.project_embedding_columns(_doc(), tmp_path)
    inject_runtime(str(tmp_path))
    assert '"photoEmbedding"' in (tmp_path / "src/lib/embedding-columns.ts").read_text()


def test_the_embedding_service_is_a_platform_integration():
    from services.node_config_specs import keys_for_provider
    assert [k.key for k in keys_for_provider("embeddings")] == ["EMBEDDINGS_URL", "EMBEDDINGS_API_KEY"]


# --------------------------------------------------------------------------- code pages

SDK = FOUNDATION / "src" / "sdk"


def test_a_code_page_reads_no_vector_and_is_told_the_entity_is_findable():
    from services.blueprint.app_sdk import emit_schema
    schema = emit_schema(_doc())
    product = schema[schema.index("/** Product"):schema.index("/** Every entity")]
    body = product[product.index("export interface Product"):]
    assert "photoEmbedding" not in body                       # no column for it...
    assert 'Findable by likeness: similar("Product", { image | text })' in product   # ...but named as the ranking
    assert "show it with <img src={fileUrl(row.photo)} />" in product
    assert "photoEmbedding" not in schema.split("READABLE_FIELDS")[1].split("};")[0]


def test_the_sdk_ranks_by_likeness_and_says_when_it_cannot():
    server = (SDK / "server.ts").read_text()
    assert "export async function similar<E extends EntityName>(" in server
    assert 'if (e?.name === "EmbeddingUnavailable") return { rows: [], error: e.message };' in server
    client = (SDK / "client.tsx").read_text()
    assert "export function ImageSearch(" in client
    assert 'kind === "image"' in client
    assert "export function fileUrl(" in (SDK / "files.ts").read_text()
    from services.blueprint.app_sdk import emit_index
    assert 'export * from "./files";' in emit_index()


def test_the_ui_engineer_is_told_how_to_search_by_image():
    from services.blueprint.ui_engineer import DESIGN_PRINCIPLES, SDK_GUIDE, TECH_RULES
    assert "similar(entity, { image?: ctx.searchParams.image" in SDK_GUIDE
    assert "<ImageSearch" in SDK_GUIDE and "fileUrl(row.photo)" in SDK_GUIDE
    assert 'an image field → "image"' in SDK_GUIDE
    assert "similar, currentUser" in TECH_RULES and "ImageSearch" in TECH_RULES
    assert "Findable by likeness" in DESIGN_PRINCIPLES
