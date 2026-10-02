"""A question about what the app shows is answered by looking at the rows.

Test2, 2026-09-28: "Why do some areas have a Country like Nepal with a State
like Uttar Pradesh?" was first answered by a keyword quote of REQ-010, then
from the definition alone ("both are plain text"). The rows showed the cause:
the sample data paired a country list with a state list of another length,
and Nepal was not one of the app's countries at all.
"""
from services.blueprint.executors import NODE_TASKS
from services.smith import data_export, reads

DOC = {"data": {"entities": [
    {"id": "ENT-002", "name": "Area", "table": "areas", "fields": [
        {"name": "id", "type": "uuid", "primaryKey": True},
        {"name": "country", "type": "string"},
        {"name": "state", "type": "string"},
        {"name": "secret", "type": "string", "sensitive": True},
    ]},
]}}


def test_the_loop_can_read_rows():
    assert "read_rows" in reads.READ_NAMES
    desc = next(d for n, d, _a in reads.READS if n == "read_rows")
    assert "before explaining what a screen shows" in desc


def test_rows_come_back_with_declared_fields_and_no_sensitive_ones(monkeypatch):
    monkeypatch.setattr("services.smith.data_import.database_url", lambda o: "postgresql://x/y")
    monkeypatch.setattr(data_export, "existing_columns", lambda url, t: {"id", "country", "state", "secret"})
    seen = {}

    def rows(url, table, cols, limit):
        seen.update(table=table, cols=cols, limit=limit)
        return [{"id": "1", "country": "Nepal", "state": "Uttar Pradesh"}]
    monkeypatch.setattr(data_export, "read_rows", rows)

    out = reads.run("read_rows", {"entity": "Area"}, output_dir="/nowhere", doc=DOC)
    assert seen == {"table": "areas", "cols": ["id", "country", "state"], "limit": reads.ROWS_SHOWN}
    assert "Nepal,Uttar Pradesh" in out
    assert "sensitive fields not shown: secret" in out


def test_an_unknown_record_type_names_the_ones_there_are():
    out = reads.run("read_rows", {"entity": "Planet"}, output_dir="/nowhere", doc=DOC)
    assert "No record type called 'Planet'" in out and "Area" in out


def test_no_database_is_said_not_guessed(monkeypatch):
    monkeypatch.setattr("services.smith.data_import.database_url", lambda o: "")
    out = reads.run("read_rows", {"entity": "Area"}, output_dir="/nowhere", doc=DOC)
    assert "not running" in out


def test_field_examples_are_asked_for_row_by_row():
    prompt = NODE_TASKS["entity_fields"]
    assert "EXAMPLES ARE READ ROW BY ROW" in prompt
    assert "same number of examples in the same order" in prompt
