"""Tests for seed_synthesizer.synthesize_seed_rows.

The shipped seed.ts reads demo rows from seed-plan.json (t.seed_data /
plan.sample_data[name] / plan.seed_data[name]) — a dict no generator populated,
so every domain table shipped EMPTY. The synthesizer fills those slots with
type-valid, FK-consistent sample rows derived from the real Drizzle schema.

These tests assert, against a tmp output dir holding a parent+child(+grandchild)
schema and a seed-plan declaring row_count:
  * N rows synthesized per table (row_count, default 8);
  * child FK values are ids that exist among the parent rows (referential
    integrity) — for BOTH inline `.references` and `foreignKey({...})` blocks;
  * enum column values come from the real pgEnum value list;
  * every NOT NULL column is populated;
  * the reserved `users` table is skipped (auth seeds admin separately);
  * output is deterministic (two runs byte-identical);
  * pre-existing seed-plan keys are preserved.
Plus a full apply_post_generate_fixes smoke that the seed-plan gains rows.
"""
import json
import os

from services.seed_synthesizer import synthesize_seed_rows


UUID_RE = __import__("re").compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", __import__("re").I
)


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _build_app(root: str) -> None:
    """A schema with users (reserved), authors (parent, enum), books (child,
    inline .references FK) and reviews (grandchild, foreignKey({...}) block)."""
    sdir = os.path.join(root, "src", "db", "schema")

    _write(os.path.join(sdir, "user.ts"),
        'import { pgTable, uuid, varchar } from "drizzle-orm/pg-core";\n'
        'export const users = pgTable("users", {\n'
        '  id: uuid("id").primaryKey().defaultRandom(),\n'
        '  email: varchar("email", { length: 255 }).notNull(),\n'
        "});\n")

    _write(os.path.join(sdir, "author.ts"),
        'import { pgTable, pgEnum, uuid, varchar, text, integer, timestamp }'
        ' from "drizzle-orm/pg-core";\n'
        "export const authorStatusEnum = pgEnum('author_status', [\n"
        "  'active',\n  'retired',\n  'banned',\n]);\n"
        'export const authors = pgTable("authors", {\n'
        '  id: uuid("id").defaultRandom().primaryKey(),\n'
        '  name: varchar("name", { length: 255 }).notNull(),\n'
        '  email: varchar("email", { length: 255 }).notNull().unique(),\n'
        "  status: authorStatusEnum('status').notNull().default('active'),\n"
        '  bio: text("bio"),\n'
        '  bookCount: integer("book_count").notNull(),\n'
        '  createdAt: timestamp("created_at").defaultNow().notNull(),\n'
        "});\n")

    _write(os.path.join(sdir, "book.ts"),
        'import { pgTable, uuid, varchar, integer, boolean, timestamp }'
        ' from "drizzle-orm/pg-core";\n'
        'import { authors } from "./author";\n'
        'export const books = pgTable("books", {\n'
        '  id: uuid("id").defaultRandom().primaryKey(),\n'
        '  authorId: uuid("author_id").references(() => authors.id).notNull(),\n'
        '  title: varchar("title", { length: 255 }).notNull().unique(),\n'
        '  pages: integer("pages").notNull(),\n'
        '  inPrint: boolean("in_print").notNull().default(true),\n'
        '  createdAt: timestamp("created_at").defaultNow().notNull(),\n'
        "});\n")

    _write(os.path.join(sdir, "review.ts"),
        'import { pgTable, uuid, varchar, integer, foreignKey }'
        ' from "drizzle-orm/pg-core";\n'
        'import { books } from "./book";\n'
        'export const reviews = pgTable(\n  "reviews",\n  {\n'
        '    id: uuid("id").defaultRandom().primaryKey(),\n'
        '    bookId: uuid("book_id").notNull(),\n'
        '    rating: integer("rating").notNull(),\n'
        '    body: varchar("body", { length: 500 }),\n'
        "  },\n  (table) => [\n"
        "    foreignKey({\n"
        "      columns: [table.bookId],\n"
        "      foreignColumns: [books.id],\n"
        "    }).onDelete(\"cascade\"),\n"
        "  ]\n);\n")


def _seed_plan(root: str) -> str:
    plan = {
        "tables": [
            {"name": "users", "order": 0, "row_count": 3, "has_admin": True},
            {"name": "authors", "order": 1, "row_count": 5},
            {"name": "books", "order": 2, "row_count": 7, "references": ["authors"]},
            {"name": "reviews", "order": 3, "row_count": 6, "references": ["books"]},
        ],
        "cross_references": {"books.author_id": "authors.id"},
        "constraints": {"foo": "bar"},
    }
    path = os.path.join(root, "contracts", "seed-plan.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    return path


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _rows(plan: dict, name: str) -> list:
    """Rows the way seed.ts reads them (sample_data bag)."""
    return plan.get("sample_data", {}).get(name, [])


def test_row_counts_per_table(tmp_path):
    root = str(tmp_path)
    _build_app(root)
    plan_path = _seed_plan(root)

    res = synthesize_seed_rows(root)
    plan = _load(plan_path)

    assert len(_rows(plan, "authors")) == 5
    assert len(_rows(plan, "books")) == 7
    assert len(_rows(plan, "reviews")) == 6
    assert res["rows_total"] == 5 + 7 + 6
    assert res["tables"] == 3  # users excluded


def test_reserved_users_skipped(tmp_path):
    root = str(tmp_path)
    _build_app(root)
    plan_path = _seed_plan(root)
    synthesize_seed_rows(root)
    plan = _load(plan_path)
    assert not _rows(plan, "users")


def test_child_fk_values_reference_real_parent_ids(tmp_path):
    root = str(tmp_path)
    _build_app(root)
    plan_path = _seed_plan(root)
    synthesize_seed_rows(root)
    plan = _load(plan_path)

    author_ids = {r["id"] for r in _rows(plan, "authors")}
    assert author_ids and all(UUID_RE.match(i) for i in author_ids)
    for book in _rows(plan, "books"):
        assert book["authorId"] in author_ids  # inline .references FK

    book_ids = {r["id"] for r in _rows(plan, "books")}
    for review in _rows(plan, "reviews"):
        assert review["bookId"] in book_ids  # foreignKey({...}) block FK


def test_enum_values_from_real_enum(tmp_path):
    root = str(tmp_path)
    _build_app(root)
    plan_path = _seed_plan(root)
    synthesize_seed_rows(root)
    plan = _load(plan_path)
    allowed = {"active", "retired", "banned"}
    statuses = {r["status"] for r in _rows(plan, "authors")}
    assert statuses and statuses <= allowed
    assert len(statuses) > 1  # cycled, not a single constant


def test_not_null_columns_populated(tmp_path):
    root = str(tmp_path)
    _build_app(root)
    plan_path = _seed_plan(root)
    synthesize_seed_rows(root)
    plan = _load(plan_path)
    for a in _rows(plan, "authors"):
        for col in ("name", "email", "status", "bookCount"):
            assert col in a and a[col] not in (None, "")
    for b in _rows(plan, "books"):
        for col in ("authorId", "title", "pages"):
            assert col in b and b[col] not in (None, "")


def test_default_columns_omitted(tmp_path):
    root = str(tmp_path)
    _build_app(root)
    plan_path = _seed_plan(root)
    synthesize_seed_rows(root)
    plan = _load(plan_path)
    # createdAt has defaultNow() → let the DB fill it, don't emit.
    for a in _rows(plan, "authors"):
        assert "createdAt" not in a
    for b in _rows(plan, "books"):
        assert "inPrint" not in b  # boolean with .default(true)


def test_deterministic_byte_identical(tmp_path):
    root = str(tmp_path)
    _build_app(root)
    plan_path = _seed_plan(root)

    synthesize_seed_rows(root)
    with open(plan_path, "rb") as fh:
        first = fh.read()
    synthesize_seed_rows(root)
    with open(plan_path, "rb") as fh:
        second = fh.read()
    assert first == second


def test_preserves_existing_plan_keys(tmp_path):
    root = str(tmp_path)
    _build_app(root)
    plan_path = _seed_plan(root)
    synthesize_seed_rows(root)
    plan = _load(plan_path)
    assert plan["cross_references"] == {"books.author_id": "authors.id"}
    assert plan["constraints"] == {"foo": "bar"}
    assert [t["name"] for t in plan["tables"]] == ["users", "authors", "books", "reviews"]


def test_seed_data_per_table_entry_also_written(tmp_path):
    """seed.ts reads t.seed_data FIRST — it must carry the rows too."""
    root = str(tmp_path)
    _build_app(root)
    plan_path = _seed_plan(root)
    synthesize_seed_rows(root)
    plan = _load(plan_path)
    by_name = {t["name"]: t for t in plan["tables"]}
    assert len(by_name["authors"].get("seed_data", [])) == 5
    assert len(by_name["books"].get("seed_data", [])) == 7


def test_never_raises_on_missing_plan(tmp_path):
    root = str(tmp_path)
    _build_app(root)  # schema but no seed-plan
    res = synthesize_seed_rows(root)
    assert res == {"tables": 0, "rows_total": 0}


def test_default_row_count_is_eight(tmp_path):
    root = str(tmp_path)
    _build_app(root)
    path = os.path.join(root, "contracts", "seed-plan.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"tables": [{"name": "authors", "order": 1}]}, fh)
    synthesize_seed_rows(root)
    plan = _load(path)
    assert len(_rows(plan, "authors")) == 8


def test_post_generate_fixes_smoke(tmp_path):
    """apply_post_generate_fixes wires the synthesizer — seed-plan gains rows."""
    from services.post_generate_fixes import apply_post_generate_fixes

    root = str(tmp_path)
    _build_app(root)
    plan_path = _seed_plan(root)
    apply_post_generate_fixes(root)
    plan = _load(plan_path)
    assert len(_rows(plan, "authors")) == 5
    assert len(_rows(plan, "books")) == 7
