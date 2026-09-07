"""CHECK-constraint guard: plain-string conditions → sql`` (else drizzle push dies)."""
from services.drizzle_check_guard import guard_check_constraints

_BAD = '''import {
  pgTable,
  varchar,
  check,
} from "drizzle-orm/pg-core";

export const reservations = pgTable(
  "reservations",
  {
    status: varchar("status", { length: 50 }).notNull().default("confirmed"),
  },
  (table) => ({
    statusCheck: check(
      "status_check",
      "status IN ('confirmed', 'cancelled')"
    ),
    dateCheck: check("date_check", "check_out > check_in"),
  })
);
'''


def _write(tmp_path, name, text):
    d = tmp_path / "src" / "db" / "schema"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text, encoding="utf-8")


def test_wraps_string_conditions_and_adds_import(tmp_path):
    _write(tmp_path, "reservations.ts", _BAD)
    res = guard_check_constraints(str(tmp_path))
    assert res == {"fixed": 2, "files": 1}
    out = (tmp_path / "src" / "db" / "schema" / "reservations.ts").read_text(encoding="utf-8")
    assert out.startswith('import { sql } from "drizzle-orm";')
    assert "sql`status IN ('confirmed', 'cancelled')`" in out
    assert "sql`check_out > check_in`" in out
    # no bare string condition left
    assert '"status IN' not in out


def test_leaves_sql_template_conditions_untouched(tmp_path):
    good = (
        'import { sql } from "drizzle-orm";\n'
        'import { pgTable, check } from "drizzle-orm/pg-core";\n'
        'export const t = pgTable("t", {}, (x) => ({\n'
        '  c: check("c", sql`status IN (\'a\')`),\n'
        '}));\n'
    )
    _write(tmp_path, "t.ts", good)
    assert guard_check_constraints(str(tmp_path)) == {"fixed": 0, "files": 0}


def test_idempotent(tmp_path):
    _write(tmp_path, "reservations.ts", _BAD)
    assert guard_check_constraints(str(tmp_path))["fixed"] == 2
    assert guard_check_constraints(str(tmp_path))["fixed"] == 0


def test_does_not_add_duplicate_sql_import(tmp_path):
    text = 'import { sql } from "drizzle-orm";\n' + _BAD
    _write(tmp_path, "reservations.ts", text)
    guard_check_constraints(str(tmp_path))
    out = (tmp_path / "src" / "db" / "schema" / "reservations.ts").read_text(encoding="utf-8")
    assert out.count('import { sql } from "drizzle-orm"') == 1
