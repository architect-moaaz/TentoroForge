"""Unit tests for the ``add_field`` seam (DEFECT-FIELD-ADD-NOT-INCREMENTAL / F-01).

Adding a column to an existing entity must be a surgical two-file change — the
registry field list and the entity's own Drizzle module — never a rebuild, and
never a byte-change to a column that already works.
"""
import json
from pathlib import Path

import pytest

from services.add_field_seam import build_add_field_bundle, AddFieldError


DRIZZLE = '''import { pgTable, uuid, varchar, timestamp } from "drizzle-orm/pg-core";

export const offer = pgTable("offers", {
  id: uuid("id").primaryKey().defaultRandom(),
  title: varchar("title"),
  createdAt: timestamp("created_at").defaultNow(),
  updatedAt: timestamp("updated_at").defaultNow(),
});
'''


def _app(tmp_path: Path, *, drizzle: str = DRIZZLE, slug: str = "offer") -> Path:
    (tmp_path / "contracts").mkdir()
    (tmp_path / "src" / "db" / "schema").mkdir(parents=True)
    registry = {"entities": [
        {"name": "Offer", "table": "offers", "slug": slug, "fields": [
            {"name": "id", "type": "uuid"},
            {"name": "title", "type": "varchar"},
        ]},
        {"name": "Customer", "table": "customers", "slug": "customer", "fields": [
            {"name": "id", "type": "uuid"}]},
    ]}
    (tmp_path / "contracts" / "resource-registry.json").write_text(
        json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    (tmp_path / "src" / "db" / "schema" / f"{slug}.ts").write_text(drizzle, encoding="utf-8")
    return tmp_path


def _by_kind(ops, kind):
    return next(o for o in ops if o.kind == kind)


def test_adds_column_to_registry_and_drizzle(tmp_path):
    root = _app(tmp_path)
    ops = build_add_field_bundle(str(root), entity="Offer",
                                 field={"name": "discount", "type": "decimal"})
    # Registry: the Offer entity gained the field; Customer untouched.
    reg = json.loads(_by_kind(ops, "registry").content)
    offer = next(e for e in reg["entities"] if e["name"] == "Offer")
    assert [f["name"] for f in offer["fields"]] == ["id", "title", "discount"]
    assert next(f for f in offer["fields"] if f["name"] == "discount")["type"] == "decimal"
    cust = next(e for e in reg["entities"] if e["name"] == "Customer")
    assert [f["name"] for f in cust["fields"]] == ["id"]

    # Drizzle: the column line landed inside the table body, before the close.
    dz = _by_kind(ops, "drizzle").content
    assert 'discount: decimal("discount", { precision: 12, scale: 2 })' in dz
    body = dz[dz.index("pgTable"):]
    assert body.index("discount:") < body.index("});")
    # decimal is imported now; the untouched columns are still exactly as before.
    assert 'import { pgTable, decimal, timestamp, uuid, varchar }' in dz
    assert '  id: uuid("id").primaryKey().defaultRandom(),' in dz
    assert '  title: varchar("title"),' in dz


def test_new_column_is_always_nullable(tmp_path):
    """A non-destructive push needs the column nullable — a caller's notNull is
    ignored so an existing row is never left violating a new constraint."""
    root = _app(tmp_path)
    ops = build_add_field_bundle(str(root), entity="Offer",
                                 field={"name": "code", "type": "varchar", "notNull": True})
    dz = _by_kind(ops, "drizzle").content
    code_line = next(ln for ln in dz.splitlines() if ln.strip().startswith("code:"))
    assert code_line == '  code: varchar("code", { length: 255 }),'
    assert ".notNull()" not in code_line
    reg = json.loads(_by_kind(ops, "registry").content)
    offer = next(e for e in reg["entities"] if e["name"] == "Offer")
    # notNull is not recorded on the registry field either.
    assert "notNull" not in next(f for f in offer["fields"] if f["name"] == "code")


def test_case_insensitive_entity_match(tmp_path):
    root = _app(tmp_path)
    ops = build_add_field_bundle(str(root), entity="offer",
                                 field={"name": "notes", "type": "text"})
    assert any(o.kind == "drizzle" for o in ops)


def test_duplicate_field_is_refused(tmp_path):
    root = _app(tmp_path)
    with pytest.raises(AddFieldError, match="already exists"):
        build_add_field_bundle(str(root), entity="Offer",
                               field={"name": "title", "type": "varchar"})


def test_unknown_entity_is_refused_with_a_helpful_message(tmp_path):
    root = _app(tmp_path)
    with pytest.raises(AddFieldError, match="not found"):
        build_add_field_bundle(str(root), entity="Nope",
                               field={"name": "x", "type": "varchar"})


def test_missing_drizzle_module_is_refused(tmp_path):
    root = _app(tmp_path)
    (root / "src" / "db" / "schema" / "offer.ts").unlink()
    with pytest.raises(AddFieldError, match="drizzle module not found"):
        build_add_field_bundle(str(root), entity="Offer",
                               field={"name": "x", "type": "varchar"})


def test_bad_field_name_is_refused(tmp_path):
    root = _app(tmp_path)
    with pytest.raises(AddFieldError, match="identifier"):
        build_add_field_bundle(str(root), entity="Offer",
                               field={"name": "1bad", "type": "varchar"})


def test_import_not_duplicated_when_builder_already_present(tmp_path):
    """Adding a second varchar must not add a second `varchar` to the import."""
    root = _app(tmp_path)
    ops = build_add_field_bundle(str(root), entity="Offer",
                                 field={"name": "sku", "type": "varchar"})
    dz = _by_kind(ops, "drizzle").content
    assert dz.count("varchar") == dz.split("export const")[0].count("varchar") + 2 \
        or dz.split('from "drizzle-orm/pg-core"')[0].count("varchar") == 1
    # Precisely: exactly one `varchar` token in the import list.
    import_line = dz.splitlines()[0]
    assert import_line.count("varchar") == 1


def test_result_bundle_only_touches_two_files(tmp_path):
    root = _app(tmp_path)
    ops = build_add_field_bundle(str(root), entity="Offer",
                                 field={"name": "discount", "type": "decimal"})
    assert {o.path for o in ops} == {
        "contracts/resource-registry.json", "src/db/schema/offer.ts"}


# --------------------------------------------------------------------------- #
# End-to-end through the tool wrapper + atomic apply_bundle (writes real files)
# --------------------------------------------------------------------------- #

def test_smith_add_field_writes_files_end_to_end(tmp_path):
    """_smith_add_field -> _apply_add_field -> build_add_field_bundle ->
    apply_bundle: the column lands on disk, committed atomically, and the app's
    other entity module is untouched."""
    from services.smith_tools import _smith_add_field
    root = _app(tmp_path)
    before_cust = (root / "src/db/schema/customer.ts") if (root / "src/db/schema/customer.ts").exists() else None

    res = _smith_add_field(str(root), {"entity": "Offer",
                                       "field": {"name": "discount", "type": "decimal"}})
    assert res["applied"] is True, res
    assert set(res["edited_paths"]) == {
        "contracts/resource-registry.json", "src/db/schema/offer.ts"}

    reg = json.loads((root / "contracts/resource-registry.json").read_text())
    offer = next(e for e in reg["entities"] if e["name"] == "Offer")
    assert "discount" in [f["name"] for f in offer["fields"]]
    dz = (root / "src/db/schema/offer.ts").read_text()
    assert 'discount: decimal(' in dz and 'import { pgTable, decimal,' in dz


def test_smith_add_field_flat_shorthand(tmp_path):
    """Accepts {entity, name, type} as well as {entity, field:{...}}."""
    from services.smith_tools import _smith_add_field
    root = _app(tmp_path)
    res = _smith_add_field(str(root), {"entity": "Offer", "name": "notes", "type": "text"})
    assert res["applied"] is True, res
    dz = (root / "src/db/schema/offer.ts").read_text()
    assert 'notes: text("notes")' in dz


def test_smith_add_field_duplicate_returns_noop_not_crash(tmp_path):
    from services.smith_tools import _smith_add_field
    root = _app(tmp_path)
    res = _smith_add_field(str(root), {"entity": "Offer", "name": "title", "type": "varchar"})
    assert res["applied"] is False
    assert "already exists" in (res.get("reason") or "")
