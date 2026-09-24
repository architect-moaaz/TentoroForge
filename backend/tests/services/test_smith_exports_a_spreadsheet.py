"""“Can I get all this out as a spreadsheet?” — and “back it up somewhere”.

Two dead ends on the same phrasebook page as the import, and the same
sentence underneath both: an application that will not hand an owner's data
back is one they cannot audit, cannot send to their accountant and cannot
leave.

The route was half-built — `templates/runtime/api-export/route.ts` has
shipped in every app — and answered anybody: no session, no role, every
column including the password hash. What these prove:

  * the file carries the DECLARED fields, key first, in the words the
    application declares them in, so it is the shape `import_data` reads;
  * a sensitive field is left out and SAID to be left out;
  * a column the database writes itself — the key, a foreign key — is
    ignored by the import with the reason printed, not refused, so the app's
    own export is not the one file it will not read;
  * no reachable database means the verb says so, not that it invents a file;
  * a name in the download URL cannot walk out of the exports directory;
  * an export changes nothing: no Blueprint write, no change-history entry.
"""

from __future__ import annotations

import csv
import io
import zipfile

import pytest

from services.blueprint.service import BlueprintService
from services.smith import data_export as dx
from services.smith import data_import as di


ROWS = {
    "customers": [
        {"id": "11111111-1111-4111-8111-111111111111", "fullName": "Annika Rahman",
         "email": "annika@rahman.co", "joined": "2026-01-04",
         "passwordHash": "$2b$12$notareallhash", "regionId": "22222222-2222-4222-8222-222222222222"},
        {"id": "33333333-3333-4333-8333-333333333333", "fullName": "Boris Vale",
         "email": "boris@vale.io", "joined": "2026-02-11",
         "passwordHash": "$2b$12$alsonot", "regionId": None},
    ],
    "regions": [{"id": "22222222-2222-4222-8222-222222222222", "name": "Dhaka"}],
}


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Ledger",
                                domain="retail")
    s.doc["data"] = {"entities": [
        {"id": "ENTITY-001", "name": "Customer", "table": "customers", "fields": [
            {"name": "id", "type": "uuid", "primaryKey": True},
            {"name": "fullName", "type": "string", "required": True},
            {"name": "email", "type": "email"},
            {"name": "joined", "type": "date"},
            {"name": "passwordHash", "type": "string", "sensitive": True},
            {"name": "regionId", "type": "uuid", "references": "ENTITY-002"}]},
        {"id": "ENTITY-002", "name": "Region", "table": "regions", "fields": [
            {"name": "id", "type": "uuid", "primaryKey": True},
            {"name": "name", "type": "string"}]},
    ]}
    s.save()
    return s


@pytest.fixture()
def db(monkeypatch):
    """The application's database, without one. `read_rows` and
    `existing_columns` are the only two places this seam touches Postgres,
    which is what makes them the seam to stand in for."""
    monkeypatch.setattr(dx, "database_url", lambda _out: "postgresql://x/y")
    monkeypatch.setattr(dx, "existing_columns",
                        lambda _url, table: set(ROWS.get(table, [{}])[0]))
    monkeypatch.setattr(dx, "read_rows",
                        lambda _url, table, cols, limit=0:
                        [{c: r.get(c) for c in cols} for r in ROWS.get(table, [])])


def _read(csv_text: str) -> tuple[list[str], list[dict]]:
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    return list(csv.reader(io.StringIO(csv_text)))[0], rows


# --------------------------------------------------------------------------- #
# what comes out
# --------------------------------------------------------------------------- #

def test_the_sheet_carries_the_declared_fields_key_first(svc, tmp_path, db):
    out = dx.run(str(tmp_path), "customers", project_id="proj1")
    assert out["applied"]

    path = dx.path_of(tmp_path, out["file"])
    header, rows = _read(path.read_text())
    assert header[0] == "id", "a row you cannot point at is not an export"
    assert header == ["id", "fullName", "email", "joined", "regionId"]
    assert rows[0]["fullName"] == "Annika Rahman"
    assert len(rows) == 2


def test_a_sensitive_field_is_left_out_and_said_to_be(svc, tmp_path, db):
    out = dx.run(str(tmp_path), "customers", project_id="proj1")
    header, _ = _read(dx.path_of(tmp_path, out["file"]).read_text())

    assert "passwordHash" not in header
    said = dx.summary_of(out)
    assert "`passwordHash`" in said
    assert "not somewhere they should come to rest" in said


def test_the_answer_is_a_link_the_platform_can_serve(svc, tmp_path, db):
    out = dx.run(str(tmp_path), "customers", project_id="proj1")
    assert out["href"] == f"/api/projects/proj1/exports/{out['file']}"
    assert f"]({out['href']})" in dx.summary_of(out)


def test_an_empty_table_exports_its_headings_and_says_so(svc, tmp_path, monkeypatch):
    monkeypatch.setattr(dx, "database_url", lambda _out: "postgresql://x/y")
    monkeypatch.setattr(dx, "existing_columns",
                        lambda _url, _t: {"id", "fullName", "email", "joined", "regionId"})
    monkeypatch.setattr(dx, "read_rows", lambda *a, **k: [])

    out = dx.run(str(tmp_path), "customers", project_id="proj1")
    header, rows = _read(dx.path_of(tmp_path, out["file"]).read_text())
    assert header[0] == "id" and rows == []
    assert "The table is empty" in dx.summary_of(out)


def test_naming_nothing_backs_up_every_kind_of_record_in_one_file(svc, tmp_path, db):
    """"Back it up somewhere" means ONE thing to put somewhere."""
    out = dx.run(str(tmp_path), "", project_id="proj1")
    assert out["backup"] and out["file"].endswith(".zip")

    with zipfile.ZipFile(dx.path_of(tmp_path, out["file"])) as zf:
        assert sorted(zf.namelist()) == ["customers.csv", "regions.csv"]
        assert "Dhaka" in zf.read("regions.csv").decode()
    said = dx.summary_of(out)
    assert "Backed up **2** kind(s) of record" in said and "3 row(s) in total" in said


def test_a_column_the_database_has_not_grown_yet_is_named_not_fatal(svc, tmp_path, monkeypatch):
    """A field renamed in the document and not yet pushed must not fail the
    whole export — the other columns are still the owner's data."""
    monkeypatch.setattr(dx, "database_url", lambda _out: "postgresql://x/y")
    monkeypatch.setattr(dx, "existing_columns", lambda _url, _t: {"id", "full_name"})
    monkeypatch.setattr(dx, "read_rows", lambda _url, _t, cols, limit=0:
                        [{c: "x" for c in cols}])

    out = dx.run(str(tmp_path), "customers", project_id="proj1")
    header, _ = _read(dx.path_of(tmp_path, out["file"]).read_text())
    # THE HEADER IS THE DECLARED NAME even though the column is snake_case,
    # because that is what makes the file importable.
    assert header == ["id", "fullName"]
    assert "`joined`" in dx.summary_of(out)
    assert "arrive when the app next starts" in dx.summary_of(out)


# --------------------------------------------------------------------------- #
# refusals
# --------------------------------------------------------------------------- #

def test_with_no_database_it_says_so_and_names_the_in_app_route(svc, tmp_path, monkeypatch):
    monkeypatch.setattr(dx, "database_url", lambda _out: "")
    out = dx.run(str(tmp_path), "customers", project_id="proj1")

    assert not out["applied"]
    assert "making the file up" in out["reason"]
    assert "`/api/export/customers`" in out["reason"]


def test_an_unknown_kind_of_record_names_the_ones_that_exist(svc, tmp_path, db):
    out = dx.run(str(tmp_path), "invoices", project_id="proj1")
    assert not out["applied"]
    assert "Customer" in out["reason"] and "back it up" in out["reason"]


def test_an_export_changes_nothing(svc, tmp_path, db):
    before = BlueprintService.load(output_dir=str(tmp_path)).doc
    dx.run(str(tmp_path), "customers", project_id="proj1")
    after = BlueprintService.load(output_dir=str(tmp_path)).doc

    assert after == before, "an export reads; nothing about the app may move"
    assert len(after.get("changeHistory") or []) == len(before.get("changeHistory") or [])


def test_a_name_from_a_url_cannot_walk_out_of_the_exports_directory(tmp_path):
    (tmp_path / ".env").write_text("SECRET=1")
    dx.exports_dir(tmp_path)

    assert dx.path_of(tmp_path, "../.env") is None
    assert dx.path_of(tmp_path, "../../etc/passwd") is None
    assert dx.path_of(tmp_path, "nothing-here.csv") is None


def test_what_has_been_produced_is_listed_newest_first(svc, tmp_path, db):
    first = dx.run(str(tmp_path), "customers", project_id="proj1")
    listed = dx.produced(tmp_path)
    assert [r["name"] for r in listed] == [first["file"]]
    assert listed[0]["bytes"] > 0


# --------------------------------------------------------------------------- #
# the loop: what comes out can go back in
# --------------------------------------------------------------------------- #

def test_the_exported_file_is_one_the_import_will_read(svc, tmp_path, db):
    """The header row is the declared field names, so the import binds every
    column by name with no model involved — and the two columns the DATABASE
    writes (the key, the foreign key) are ignored WITH THE REASON PRINTED
    rather than refused, or the app's own export would be the one file it
    will not read."""
    out = dx.run(str(tmp_path), "customers", project_id="proj1")
    sheet = dx.path_of(tmp_path, out["file"]).read_bytes()

    di.accept(tmp_path, out["file"], sheet)
    report = di.plan(svc.doc, tmp_path, "customers",
                     provider=lambda _p: pytest.fail("no model should be needed"))

    assert not report["unmapped"], report["unmapped"]
    assert sorted(report["ignored"]) == ["id", "regionId"]
    assert sorted(report["db_owned"]) == ["id", "regionId"]
    assert [r["fullName"] for r in report["rows"]] == ["Annika Rahman", "Boris Vale"]
    assert report["rows"][0]["joined"] == "2026-01-04"
    said = di.summary_of_plan(report)
    assert "the database writes" in said


# --------------------------------------------------------------------------- #
# the verb
# --------------------------------------------------------------------------- #

def test_the_verb_needs_nothing_because_all_of_them_names_no_entity():
    from services.smith.verbs import REQUIRED_BY_VERB, VERB_HELP, missing_fields

    assert REQUIRED_BY_VERB["export_data"] == set()
    assert missing_fields({"verb": "export_data"}) == []
    # "back it up somewhere" is `back_up` — records AND definition — not a
    # spreadsheet; the two helps must not both claim it.
    assert "back it up somewhere" not in VERB_HELP["export_data"]
    assert "back it up somewhere" in VERB_HELP["back_up"]
    assert "Changes nothing" in VERB_HELP["export_data"]


def test_it_is_in_the_list_smith_gives_when_asked_what_it_can_do():
    from services.smith import capabilities

    groups = [g for g in capabilities.GROUPS if "export_data" in g[2]]
    assert len(groups) == 1
    assert "import_data" in groups[0][2], "in and out are one capability"


def test_the_turn_hands_back_the_file_and_reports_no_change(svc, tmp_path, db):
    from tests.services._front_door import SmithSession

    session = SmithSession(project_id="proj1", output_dir=str(tmp_path),
                           guards_fn=lambda *a, **kw: [],
                           understand_ask_fn=lambda m, ctx, **kw: {
                               "verb": "export_data", "entity": "customers"},
                           iteration_move_fn=lambda *a, **kw: None)
    result = session.run_iteration(
        user_message="can I get all this out as a spreadsheet?")

    # `no_op` — read, nothing needed changing. Not `resolved`, which would
    # report a change that did not happen.
    assert result.status == "no_op"
    assert "/api/projects/proj1/exports/" in result.answer
    assert result.touched_paths == []
