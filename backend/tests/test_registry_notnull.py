"""Registry extraction must capture NOT NULL / primary-key columns as
``nullable: False`` so the form builder can emit `validators.required` (the `*`),
and reconcile_entities must never downgrade a NOT-NULL column back to nullable."""
import json

from services.registry_extractor import extract_entities_from_schema
from services.registry import reconcile_entities


_SCHEMA_TS = """\
import { pgTable, uuid, varchar, text, integer, timestamp } from "drizzle-orm/pg-core";

export const widgets = pgTable("widgets", {
  id: uuid("id").primaryKey().defaultRandom(),
  title: varchar("title", { length: 255 }).notNull(),
  ownerId: uuid("owner_id")
    .references(() => users.id)
    .notNull(),
  quantity: integer("quantity").notNull().default(0),
  notes: text("notes"),
  createdAt: timestamp("created_at").defaultNow(),
});
"""


def _extract(tmp_path):
    sdir = tmp_path / "src" / "db" / "schema"
    sdir.mkdir(parents=True)
    (sdir / "widgets.ts").write_text(_SCHEMA_TS, encoding="utf-8")
    return extract_entities_from_schema(str(tmp_path))


def test_extractor_captures_notnull_as_not_nullable(tmp_path):
    ents = _extract(tmp_path)
    fields = ents["Widgets"]["fields"]
    # NOT NULL columns → nullable False (single-line and multi-line chains).
    assert fields["title"]["nullable"] is False
    assert fields["ownerId"]["nullable"] is False        # .notNull() on a wrapped line
    assert fields["quantity"]["nullable"] is False
    # Primary key → nullable False too.
    assert fields["id"]["nullable"] is False
    assert fields["id"]["primaryKey"] is True
    # Plain column (no .notNull()) → nullable True.
    assert fields["notes"]["nullable"] is True


def test_extractor_marks_default_columns(tmp_path):
    ents = _extract(tmp_path)
    fields = ents["Widgets"]["fields"]
    # A NOT NULL column WITH a default is still not-required on a create form.
    assert fields["quantity"]["hasDefault"] is True
    assert fields["createdAt"].get("hasDefault") is True


def test_reconcile_applies_schema_notnull_over_plan(tmp_path):
    ents = _extract(tmp_path)
    # The plan seeds fields nullable (its default is unreliable); the extractor read
    # the real `.notNull()` from the schema. Reconcile folds the ACCURATE extracted
    # metadata onto the singular plan key so `title`/`ownerId` become required and the
    # genuinely-nullable `notes` stays nullable.
    registry = {"entities": {"Widget": {"fields": {
        "title": {"type": "varchar", "nullable": True},
        "ownerId": {"type": "uuid", "nullable": True},
        "notes": {"type": "text", "nullable": True},
    }, "indexes": []}}}
    out = reconcile_entities(registry, ents)
    merged = out["entities"]["Widget"]["fields"]
    assert "Widgets" not in out["entities"]          # no duplicate plural key
    assert merged["title"]["nullable"] is False       # schema .notNull() wins
    assert merged["ownerId"]["nullable"] is False
    assert merged["notes"]["nullable"] is True        # genuinely nullable
