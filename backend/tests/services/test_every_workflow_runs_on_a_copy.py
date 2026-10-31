"""Running every DITANS workflow on a copy of its data (wzml1sa6, 2026-10-31).

Each fault below was found by running all 312 processes a person starts, as
their role, on a database copy:

- a trial took 85 seconds, because every one of ~500 statements opened its
  own connection (`docker exec psql` locally);
- a record input with no `required` flag was left out by the trial, which the
  app reads as required — every job process was refused for want of its job;
- the copy reported its own crashes as the live app's, and self-heal spent
  Smith turns on them;
- a rule that starts a workflow handed it the record's fields but not the
  input it declares, so "consent withdrawn → delete-your-copies" never ran;
- `$now + duration("P30D")` as a value was stored as that text;
- the seed wrote labels into uuid columns not named `…Id` and decimals into
  integer columns, and sixteen tables — every legal entity, facility, unit,
  position, interview — stayed empty.
"""
from __future__ import annotations

from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[2] / "templates" / "runtime"


# -- the trial bench ----------------------------------------------------------

def test_a_database_is_asked_through_one_held_connection(monkeypatch):
    import psycopg2

    from services import app_databases

    opened = []

    class Cur:
        description = [("n",)]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql):
            self.sql = sql

        def fetchall(self):
            return [(1,)]

    class Con:
        closed = False
        autocommit = False

        def cursor(self):
            return Cur()

        def close(self):
            self.closed = True

    monkeypatch.setattr(psycopg2, "connect", lambda *a, **k: opened.append(a) or Con())
    app_databases._held.__dict__.pop("cons", None)
    for _ in range(50):
        assert app_databases.query_url("postgresql://x/app_copy", "select 1") == [["1"]]
    assert len(opened) == 1, "fifty statements, one connection"


def test_a_record_input_is_required_unless_it_says_it_is_not(monkeypatch):
    from services.blueprint import page_review
    from services.smith import trials

    def fake_query(_app, sql):
        if "information_schema.columns" in sql:
            return [["id"], ["title"], ["created_at"]]
        return [["11111111-1111-4111-8111-111111111111", "Staff Nurse"]]

    monkeypatch.setattr(page_review, "_query", fake_query)
    doc = {"data": {"entities": [{"id": "ENTITY-020", "name": "Job", "table": "jobs", "labelField": "title"}]}}
    flow = {"id": "FLOW-008", "inputs": [{"kind": "record", "name": "job", "entity": "ENTITY-020"},
                                         {"kind": "record", "name": "facility", "entity": "ENTITY-020",
                                          "required": False}]}
    payload: dict = {}
    trials.fill_records(object(), doc, flow, payload)
    assert payload == {"job": "11111111-1111-4111-8111-111111111111"}, "no flag is required, as the app reads it"


def test_a_copy_does_not_report_its_errors_as_the_apps():
    src = (Path(__file__).resolve().parents[2] / "services" / "blueprint" / "page_review.py").read_text()
    start = src.split("def _start_server(", 1)[1].split("\n    def ", 1)[0]
    assert '"FORGE_URL": ""' in start


# -- the app's runtime ---------------------------------------------------------

def test_a_rule_hands_its_record_to_the_input_of_that_table():
    src = (RUNTIME / "workflows" / "index.ts").read_text()
    assert "async function _ruleRecordInputs(" in src
    assert "if (ri?.table === table) out[ri.name] = id;" in src
    assert "...(await _ruleRecordInputs(key, table, rec.id))" in src
    assert src.count("_flushRuleEffects(ctx, row, (config as any).table)") == 1
    engine = (RUNTIME / "data-engine.ts").read_text()
    assert engine.count("fireRuleEffects(ruleEffects, record, ctx, entity.table)") == 2
    assert "runRuleEffects(effects, record, ctx.user, table)" in engine


def test_a_date_counted_from_now_is_a_date_and_each_uuid_is_fresh():
    resolver = (RUNTIME / "workflows" / "index.ts").read_text().split("export function _resolveRef(", 1)[1]
    resolver = resolver.split("\n}\n", 1)[0]
    assert r"/^\s*\$(now|today)\s*[-+]/.test(ref)" in resolver
    assert "evaluateExpression(ref," in resolver
    assert r'ref.replace(/\$uuid\b/g, () => crypto.randomUUID())' in resolver


def test_the_seed_keeps_keys_keys_and_whole_numbers_whole():
    prep = (RUNTIME / "seed.ts").read_text().split("function prepRow(", 1)[1].split("\n}\n", 1)[0]
    assert '/uuid/i.test(String(tcol.columnType ?? ""))' in prep
    assert 'val = prop === "id" ? mintToken(String(val)) : null;' in prep
    assert "val = Math.round(Number(val));" in prep
    assert 'const people = ids["users"] || ids["user"];' in prep
