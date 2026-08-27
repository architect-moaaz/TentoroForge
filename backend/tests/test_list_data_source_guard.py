"""Tests for list_data_source_guard.reconcile_list_sources.

Covers both drift classes the guard heals:
  1. binding ↔ dataSource-name drift (the real wj83u270 empty-table bug):
     a Table binds `{{drives}}` while the sole list dataSource is named
     `recruitmentDrives` → the binding is repointed to the real name.
  2. source ↔ registered-slug drift: an explicit `source` naming
     `recruitment-drives` is rewritten to the registered `recruitmentDrives`;
     an exact match is untouched; an unknown source is flagged, not rewritten.
"""
import json
import os

from services.list_data_source_guard import reconcile_list_sources


def _write(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)


def _schema_dir(root: str) -> str:
    """A drizzle schema dir registering `recruitmentDrives` (+ friends)."""
    sdir = os.path.join(root, "src", "db", "schema")
    os.makedirs(sdir, exist_ok=True)
    with open(os.path.join(sdir, "recruitment-drives.ts"), "w", encoding="utf-8") as fh:
        fh.write(
            'import { pgTable, uuid, varchar } from "drizzle-orm/pg-core";\n'
            'export const recruitmentDrives = pgTable("recruitmentDrives", {\n'
            '  id: uuid("id").primaryKey(),\n'
            '  title: varchar("title", { length: 255 }),\n'
            "});\n"
        )
    with open(os.path.join(sdir, "applications.ts"), "w", encoding="utf-8") as fh:
        fh.write(
            'import { pgTable, uuid } from "drizzle-orm/pg-core";\n'
            'export const applications = pgTable("applications", {\n'
            '  id: uuid("id").primaryKey(),\n'
            "});\n"
        )
    return os.path.join(root, "src", "schemas")


def _page(name: str, entity: str, op: str, rows_token: str, extra: dict | None = None) -> dict:
    ds = {"name": name, "entity": entity, "op": op}
    if extra:
        ds.update(extra)
    return {
        "schemaVersion": "2",
        "id": f"{name}-list",
        "route": "/drives",
        "dataSources": [ds],
        "root": {
            "type": "Stack",
            "children": [
                {"type": "Table", "props": {
                    "columns": [{"key": "title", "label": "Title"}],
                    "rows": "{{" + rows_token + "}}",
                }},
            ],
        },
    }


# ── 1. binding ↔ name drift (the real bug) ──────────────────────────────────

def test_rebinds_rows_to_sole_list_source(tmp_path):
    """Table rows `{{drives}}` with only a `recruitmentDrives` list source →
    the binding is repointed to `{{recruitmentDrives}}` so the table populates."""
    schemas = _schema_dir(str(tmp_path))
    _write(os.path.join(schemas, "drives.json"),
           _page("recruitmentDrives", "RecruitmentDrive", "list", "drives"))

    res = reconcile_list_sources(str(tmp_path))

    page = json.load(open(os.path.join(schemas, "drives.json")))
    rows = page["root"]["children"][0]["props"]["rows"]
    assert rows == "{{recruitmentDrives}}"
    assert ("drives.json", "rows", "drives", "recruitmentDrives") in res["binding_remapped"]


def test_matching_binding_untouched(tmp_path):
    """A binding that already matches its dataSource name is left alone."""
    schemas = _schema_dir(str(tmp_path))
    _write(os.path.join(schemas, "applications.json"),
           _page("applications", "Application", "list", "applications"))

    res = reconcile_list_sources(str(tmp_path))

    page = json.load(open(os.path.join(schemas, "applications.json")))
    assert page["root"]["children"][0]["props"]["rows"] == "{{applications}}"
    assert res["binding_remapped"] == []
    assert res["files_changed"] == 0


def test_ambiguous_binding_flagged_not_rewritten(tmp_path):
    """A rows-binding matching no dataSource, on a page with >1 list source and
    no canonical match, is flagged — never guessed."""
    schemas = _schema_dir(str(tmp_path))
    page = {
        "dataSources": [
            {"name": "applications", "entity": "Application", "op": "list"},
            {"name": "candidates", "entity": "Candidate", "op": "list"},
        ],
        "root": {"type": "Table", "props": {"rows": "{{mystery}}"}},
    }
    _write(os.path.join(schemas, "mixed.json"), page)

    res = reconcile_list_sources(str(tmp_path))

    out = json.load(open(os.path.join(schemas, "mixed.json")))
    assert out["root"]["props"]["rows"] == "{{mystery}}"  # untouched
    assert ("mixed.json", "rows", "mystery") in res["binding_unresolved"]


def test_idempotent(tmp_path):
    """Running twice makes no further change."""
    schemas = _schema_dir(str(tmp_path))
    _write(os.path.join(schemas, "drives.json"),
           _page("recruitmentDrives", "RecruitmentDrive", "list", "drives"))

    reconcile_list_sources(str(tmp_path))
    res2 = reconcile_list_sources(str(tmp_path))
    assert res2["files_changed"] == 0
    assert res2["binding_remapped"] == []


# ── 2. source ↔ registered-slug drift ───────────────────────────────────────

def test_rewrites_mismatched_source_slug(tmp_path):
    """A list dataSource `source: recruitment-drives` is rewritten to the real
    registered slug `recruitmentDrives`."""
    schemas = _schema_dir(str(tmp_path))
    _write(os.path.join(schemas, "drives.json"),
           _page("recruitmentDrives", "RecruitmentDrive", "list", "recruitmentDrives",
                 extra={"source": "recruitment-drives"}))

    res = reconcile_list_sources(str(tmp_path))

    page = json.load(open(os.path.join(schemas, "drives.json")))
    assert page["dataSources"][0]["source"] == "recruitmentDrives"
    assert ("drives.json", "source", "recruitment-drives", "recruitmentDrives") \
        in res["source_remapped"]


def test_exact_source_untouched(tmp_path):
    """An exact-match source is not rewritten."""
    schemas = _schema_dir(str(tmp_path))
    _write(os.path.join(schemas, "drives.json"),
           _page("recruitmentDrives", "RecruitmentDrive", "list", "recruitmentDrives",
                 extra={"source": "recruitmentDrives"}))

    res = reconcile_list_sources(str(tmp_path))

    page = json.load(open(os.path.join(schemas, "drives.json")))
    assert page["dataSources"][0]["source"] == "recruitmentDrives"
    assert res["source_remapped"] == []


def test_unknown_source_flagged_not_rewritten(tmp_path):
    """A source naming no registered table is flagged, left as-is."""
    schemas = _schema_dir(str(tmp_path))
    _write(os.path.join(schemas, "widgets.json"),
           _page("widgets", "Widget", "list", "widgets",
                 extra={"source": "gizmos"}))

    res = reconcile_list_sources(str(tmp_path))

    page = json.load(open(os.path.join(schemas, "widgets.json")))
    assert page["dataSources"][0]["source"] == "gizmos"  # untouched
    assert ("widgets.json", "source", "gizmos") in res["source_unresolved"]


# ── 3. ordering regression: schema_references renames the source AFTER the first
#       reconcile, orphaning the rows-binding (the real output/afwn8nya bug) ──────

def _schema_ts(sdir: str, const: str, table: str, extra_col: str = "title") -> None:
    os.makedirs(sdir, exist_ok=True)
    with open(os.path.join(sdir, f"{const}.ts"), "w", encoding="utf-8") as fh:
        fh.write(
            'import { pgTable, uuid, varchar } from "drizzle-orm/pg-core";\n'
            f'export const {const} = pgTable("{table}", {{\n'
            '  id: uuid("id").primaryKey(),\n'
            f'  {extra_col}: varchar("{extra_col}", {{ length: 255 }}),\n'
            "});\n"
        )


def test_apply_post_generate_fixes_heals_binding_orphaned_by_rename(tmp_path):
    """End-to-end ordering regression for the `output/afwn8nya` /drives + /inbox bug.

    The deterministic list builder ships an internally-CONSISTENT page — dataSource
    name and rows-binding share the route-slug token (`drives` ↔ `{{drives}}`), so
    the early reconcile pass correctly sees no mismatch. `schema_references` then
    canonicalises the dataSource NAME to the entity slug (`drives` → `recruitmentDrives`)
    but does NOT rewrite the rows-binding, leaving `{{drives}}` dangling → empty table.
    `apply_post_generate_fixes` must heal it (the FINAL reconcile pass), leaving the
    binding pointed at the renamed source.
    """
    from services.post_generate_fixes import apply_post_generate_fixes

    root = str(tmp_path)
    sdir = os.path.join(root, "src", "db", "schema")
    _schema_ts(sdir, "recruitmentDrives", "recruitmentDrives")
    _schema_ts(sdir, "applicants", "applicants", extra_col="name")

    # Registry (reality) — resolve_entity/slug drive the rename in schema_references.
    with open(os.path.join(root, "registry.json"), "w", encoding="utf-8") as fh:
        json.dump({"entities": {
            "RecruitmentDrive": {"fields": {"id": {"type": "uuid"}, "title": {"type": "text"}}},
            "Applicant": {"fields": {"id": {"type": "uuid"}, "name": {"type": "text"}}},
        }, "relations": []}, fh)

    schemas = os.path.join(root, "src", "schemas")
    # Builder-original state: name == route slug, rows == {{route slug}} (consistent).
    _write(os.path.join(schemas, "drives.json"),
           {"schemaVersion": "2", "id": "drives-list", "route": "/drives",
            "dataSources": [{"name": "drives", "entity": "RecruitmentDrive", "op": "list"}],
            "root": {"type": "Stack", "children": [
                {"type": "Table", "props": {
                    "columns": [{"key": "title", "label": "Title"}],
                    "rows": "{{drives}}"}}]}})
    _write(os.path.join(schemas, "inbox.json"),
           {"schemaVersion": "2", "id": "inbox-list", "route": "/inbox",
            "dataSources": [{"name": "inbox", "entity": "Applicant", "op": "list"}],
            "root": {"type": "Stack", "children": [
                {"type": "Table", "props": {
                    "columns": [{"key": "name", "label": "Name"}],
                    "rows": "{{inbox}}"}}]}})

    apply_post_generate_fixes(root)

    drives = json.load(open(os.path.join(schemas, "drives.json")))
    inbox = json.load(open(os.path.join(schemas, "inbox.json")))

    # dataSource was canonicalised by schema_references ...
    assert drives["dataSources"][0]["name"] == "recruitmentDrives"
    assert inbox["dataSources"][0]["name"] == "applicants"

    def _first_table_rows(page):
        for node in _iter_all(page.get("root")):
            if isinstance(node, dict) and node.get("type") == "Table":
                return (node.get("props") or {}).get("rows")
        return None

    # ... and the FINAL reconcile healed the orphaned rows-binding to match.
    assert _first_table_rows(drives) == "{{recruitmentDrives}}"
    assert _first_table_rows(inbox) == "{{applicants}}"


def _iter_all(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _iter_all(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_all(v)
