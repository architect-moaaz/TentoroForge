"""“Here's our customer spreadsheet, load it in.”

The first dead end an owner reaches, usually inside the first hour, because
every owner arrives with an existing business and existing data. There was no
import of any kind, so the first real use of an application Forge built was
typing everything in again.

What these prove, in the order an import has to satisfy them:

  * the dry run WRITES NOTHING and says what it would do;
  * a column the record has no field for is REFUSED, with the two things that
    do work — never guessed at, never silently dropped;
  * a value the declared type cannot hold turns that ROW away, and the rest
    still land;
  * a date nobody can read without guessing which half is the month is
    refused rather than guessed;
  * the yes applies the mapping that was SHOWN, the rows go to the app's own
    database (not the Blueprint), and the Blueprint records that it happened;
  * the same file twice is the same import, not twice the customers;
  * an entity holding real records stops being given demo rows.
"""

from __future__ import annotations

import json

import pytest

from services.blueprint.projection import SEED_ROWS, project_seed
from services.blueprint.service import BlueprintService
from services.smith import data_import as di


CSV = (
    "Full Name,Email,Phone No.,Joined,Credit\n"
    "Annika Rahman,annika@rahman.co,+8801711000111,2026-01-04,1500\n"
    "Boris Vale,boris@vale.io,+441632960111,2026-02-11,900\n"
)


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Ledger",
                                domain="retail")
    s.doc["data"] = {"entities": [{
        "id": "ENTITY-001", "name": "Customer", "table": "customers",
        "fields": [
            {"name": "id", "type": "uuid", "primaryKey": True},
            {"name": "fullName", "type": "string", "required": True},
            {"name": "email", "type": "email"},
            {"name": "phoneNumber", "type": "string"},
            {"name": "joined", "type": "date"},
        ]}]}
    s.save()
    return s


def _attach(output_dir, body: str = CSV, name: str = "customers.csv") -> dict:
    return di.accept(output_dir, name, body.encode("utf-8"))


def _mapping(pairs: dict):
    """The proposal seam, without a model. `Phone No.` is the column no
    normalised-name match can reach, and it is the whole reason the seam
    exists."""
    return lambda _prompt: json.dumps(pairs)


# --------------------------------------------------------------------------- #
# the dry run
# --------------------------------------------------------------------------- #

def test_the_dry_run_counts_the_rows_and_writes_nothing(svc, tmp_path):
    _attach(tmp_path)
    report = di.plan(svc.doc, tmp_path, "customers",
                     ignore_columns=["Credit"],
                     provider=_mapping({"Phone No.": "phoneNumber"}))

    assert len(report["rows"]) == 2 and not report["rejects"]
    assert report["table"] == "customers"
    assert dict((c["column"], c["field"]) for c in report["columns"]) == {
        "Full Name": "fullName", "Email": "email",
        "Phone No.": "phoneNumber", "Joined": "joined"}
    # NOTHING WRITTEN: no payload, no declaration, no new version.
    assert not (tmp_path / "app" / "src" / "db" / "imports").exists()
    assert di.imports_of(svc.doc) == []
    summary = di.summary_of_plan(report)
    assert "2 row(s)" in summary and "Full Name → `fullName`" in summary
    assert di.GO_LABEL in summary


def test_a_column_with_no_field_is_refused_with_the_way_round_it(svc, tmp_path):
    _attach(tmp_path)
    report = di.plan(svc.doc, tmp_path, "customers",
                     provider=_mapping({"Phone No.": "phoneNumber"}))

    assert report["unmapped"] == ["Credit"]
    refusal = di.blocked(report)
    assert "**Credit**" in refusal and "no field" in refusal
    # The two things that DO work, both offered.
    assert "add a credit field to customers" in refusal
    assert di.ignore_label(report) == "Import without Credit"
    assert di.ignore_label(report) in refusal


def test_the_model_cannot_invent_a_field_or_take_a_used_one(svc, tmp_path):
    """CONSTRAIN, DON'T CORRECT. A proposal naming a field that does not
    exist, or one another column already holds, is DROPPED — so the column
    stays unmapped and is reported, rather than writing into a column nobody
    declared."""
    _attach(tmp_path)
    report = di.plan(svc.doc, tmp_path, "customers", ignore_columns=["Credit"],
                     provider=_mapping({"Phone No.": "creditLimit",
                                        "Joined": "fullName"}))

    assert report["unmapped"] == ["Phone No."]
    assert dict((c["column"], c["field"]) for c in report["columns"])["Joined"] == "joined"


def test_a_required_field_no_column_supplies_is_refused_before_any_row(svc, tmp_path):
    _attach(tmp_path, "Email,Joined\nannika@rahman.co,2026-01-04\n")
    report = di.plan(svc.doc, tmp_path, "customers", provider=_mapping({}))

    assert report["required_missing"] == ["fullName"]
    refusal = di.blocked(report)
    assert "**fullName**" in refusal and "every row would be turned away" in refusal


# --------------------------------------------------------------------------- #
# values against the declared types
# --------------------------------------------------------------------------- #

def test_a_value_the_type_cannot_hold_turns_that_row_away_and_keeps_the_rest(svc, tmp_path):
    svc.doc["data"]["entities"][0]["fields"].append(
        {"name": "creditLimit", "type": "decimal"})
    _attach(tmp_path,
            "Full Name,Credit\nAnnika Rahman,1500\nBoris Vale,ask accounts\n")
    report = di.plan(svc.doc, tmp_path, "customers",
                     provider=_mapping({"Credit": "creditLimit"}))

    assert [r["fullName"] for r in report["rows"]] == ["Annika Rahman"]
    assert len(report["rejects"]) == 1
    assert "row 3" in report["rejects"][0]["why"]
    assert "creditLimit is a number" in report["rejects"][0]["why"]


def test_an_ambiguous_date_is_refused_rather_than_guessed(svc, tmp_path):
    """03/04/2026 is the third of April to the owner who typed it and the
    fourth of March to half the world. An import that guesses puts wrong
    dates on real records and says nothing."""
    _attach(tmp_path, "Full Name,Joined\nAnnika Rahman,03/04/2026\n")
    report = di.plan(svc.doc, tmp_path, "customers", provider=_mapping({}))

    assert not report["rows"] and len(report["rejects"]) == 1
    why = report["rejects"][0]["why"]
    assert "without guessing" in why and "2026-09-18" in why
    assert "Not one of the 1 rows" in di.blocked(report)


def test_the_declared_types_are_one_table_with_no_exceptions(svc):
    assert di.coerce("12", {"name": "n", "type": "int"}) == 12
    assert di.coerce("1,500.50", {"name": "n", "type": "decimal"}) == 1500.5
    assert di.coerce("£1,500", {"name": "n", "type": "money"}) == 1500.0
    assert di.coerce("yes", {"name": "n", "type": "boolean"}) is True
    assert di.coerce("2026-01-04", {"name": "n", "type": "date"}) == "2026-01-04"
    # A type the table does not name is text. A RULE, not a special case.
    assert di.coerce(" Annika ", {"name": "n", "type": "citext"}) == "Annika"
    # An empty optional column is nothing, not "".
    assert di.coerce("", {"name": "n", "type": "string"}) is None
    with pytest.raises(di.Rejected):
        di.coerce("", {"name": "n", "type": "string", "required": True})
    with pytest.raises(di.Rejected):
        di.coerce("maybe", {"name": "n", "type": "boolean"})
    with pytest.raises(di.Rejected):
        di.coerce("Platinum", {"name": "tier", "type": "string",
                               "enumValues": ["Gold", "Silver"]})
    assert di.coerce("gold", {"name": "tier", "type": "string",
                              "enumValues": ["Gold", "Silver"]}) == "Gold"


def test_the_three_kinds_of_field_a_spreadsheet_may_not_write(svc):
    entity = {"fields": [
        {"name": "id", "type": "uuid", "primaryKey": True},
        {"name": "fullName", "type": "string"},
        {"name": "regionId", "type": "uuid", "references": "ENTITY-009"},
        {"name": "passwordHash", "type": "string", "sensitive": True},
    ]}
    assert [f["name"] for f in di.loadable_fields(entity)] == ["fullName"]


# --------------------------------------------------------------------------- #
# the yes
# --------------------------------------------------------------------------- #

def test_the_yes_loads_the_rows_into_the_app_and_records_the_import(svc, tmp_path):
    _attach(tmp_path)
    report = di.plan(svc.doc, tmp_path, "customers", ignore_columns=["Credit"],
                     provider=_mapping({"Phone No.": "phoneNumber"}))
    out = di.apply(svc, report, app_root=str(tmp_path / "app"))

    # THE ROWS ARE IN THE APP, NOT THE BLUEPRINT.
    payload = json.loads(di.payload_path(tmp_path / "app", report["import_id"]).read_text())
    assert payload["table"] == "customers"
    assert [r["fullName"] for r in payload["rows"]] == ["Annika Rahman", "Boris Vale"]
    assert payload["rows"][0]["phoneNumber"] == "+8801711000111"
    assert payload["rows"][0]["joined"] == "2026-01-04"
    assert json.dumps(svc.doc).count("Annika Rahman") == 0

    # The Blueprint records that it HAPPENED, and under what mapping.
    fresh = BlueprintService.load(output_dir=str(tmp_path))
    declared = di.imports_of(fresh.doc)
    assert len(declared) == 1
    assert declared[0]["entity"] == "ENTITY-001"
    assert declared[0]["rowCount"] == 2
    assert declared[0]["ignoredColumns"] == ["Credit"]
    assert {"column": "Phone No.", "field": "phoneNumber"} in declared[0]["columns"]
    assert fresh.doc["changeHistory"][-1]["userRequest"] == \
        "load customers.csv into Customer"
    assert "Loaded **2 customers**" in di.summary_of(out)


def test_an_imported_entity_stops_being_given_demo_rows(svc, tmp_path):
    app = tmp_path / "app"
    svc.doc["data"]["entities"].append(
        {"id": "ENTITY-002", "name": "Supplier", "table": "suppliers",
         "fields": [{"name": "id", "type": "uuid", "primaryKey": True},
                    {"name": "name", "type": "string"}]})
    project_seed(svc.doc, app)
    before = json.loads((app / "src" / "db" / "seed.json").read_text())
    assert len(before["customers"]) == SEED_ROWS   # the demo rows a preview needs

    _attach(tmp_path)
    report = di.plan(svc.doc, tmp_path, "customers", ignore_columns=["Credit"],
                     provider=_mapping({"Phone No.": "phoneNumber"}))
    di.apply(svc, report, app_root=str(app))

    after = json.loads((app / "src" / "db" / "seed.json").read_text())
    assert "customers" not in after, "an entity holding real records wants no Customer 1"
    assert len(after["suppliers"]) == SEED_ROWS, "an entity nobody imported into keeps its demo rows"


def test_the_same_file_twice_is_the_same_import(svc, tmp_path):
    _attach(tmp_path)
    report = di.plan(svc.doc, tmp_path, "customers", ignore_columns=["Credit"],
                     provider=_mapping({"Phone No.": "phoneNumber"}))
    di.apply(svc, report, app_root=str(tmp_path / "app"))

    _attach(tmp_path)                            # attached again, same bytes
    with pytest.raises(di.ImportRefused) as exc:
        di.plan(svc.doc, tmp_path, "customers", provider=_mapping({}))
    assert "already loaded" in str(exc.value)
    assert "every record twice" in str(exc.value)


def test_a_yes_is_a_yes_to_the_import_that_was_shown(svc, tmp_path):
    _attach(tmp_path)
    report = di.plan(svc.doc, tmp_path, "customers", ignore_columns=["Credit"],
                     provider=_mapping({"Phone No.": "phoneNumber"}))
    di.remember(tmp_path, report)

    assert not di.wants(di.peek(tmp_path), "actually make it green")
    assert di.wants(di.peek(tmp_path), di.GO_LABEL)
    taken = di.agreed(tmp_path, "go ahead")
    assert taken["import_id"] == report["import_id"]
    # TAKEN AS IT IS READ: a yes cannot apply the same import twice.
    assert di.agreed(tmp_path, "go ahead") == {}


def test_the_chip_that_leaves_a_column_out_is_the_yes_for_that_import(svc, tmp_path):
    _attach(tmp_path)
    report = di.plan(svc.doc, tmp_path, "customers",
                     provider=_mapping({"Phone No.": "phoneNumber"}))
    di.remember(tmp_path, report)
    assert di.wants(di.peek(tmp_path), "Import without Credit")


# --------------------------------------------------------------------------- #
# both turns, through the handler the tools and the session share
# --------------------------------------------------------------------------- #

def test_the_two_turns_end_to_end(svc, tmp_path, monkeypatch):
    monkeypatch.setattr(di, "_propose",
                        lambda *a, **k: {"Phone No.": "phoneNumber"})
    _attach(tmp_path)

    first = di.run(str(tmp_path), "customers", ignore_columns=["Credit"])
    assert first["asked"] and not first["applied"]
    assert first["options"] == [di.GO_LABEL, di.NO_LABEL]
    assert "2 row(s)" in first["reason"]
    assert not (tmp_path / "app" / "src" / "db" / "imports").exists()

    second = di.run(str(tmp_path), message="Load them in")
    assert second["applied"] and second["rows"] == 2
    assert di.payload_path(tmp_path / "app", first["report"]["import_id"]).is_file()
    # The plan is gone: a third "go ahead" is not a second import.
    assert di.peek(tmp_path) == {}


def test_with_no_spreadsheet_it_says_so_rather_than_failing(svc, tmp_path):
    out = di.run(str(tmp_path), "customers")
    assert not out["applied"] and not out.get("asked")
    assert "Attach it to your message" in out["reason"]


def test_an_unknown_kind_of_record_names_the_ones_that_exist(svc, tmp_path):
    _attach(tmp_path)
    out = di.run(str(tmp_path), "invoices")
    assert not out["applied"]
    assert "Customer" in out["reason"]


# --------------------------------------------------------------------------- #
# the file formats an owner actually has
# --------------------------------------------------------------------------- #

def test_a_semicolon_export_is_read_as_columns_not_as_one(tmp_path):
    rec = di.accept(tmp_path, "eu.csv",
                    "Full Name;Email\nAnnika Rahman;annika@rahman.co\n".encode())
    columns, rows, how = di.read_sheet(rec and (di.inbox_dir(tmp_path) / rec["id"] / "source.csv"))
    assert columns == ["Full Name", "Email"]
    assert rows[0]["Email"] == "annika@rahman.co"
    assert how == "semicolon-separated"


def test_an_xlsx_is_read_because_that_is_what_a_spreadsheet_is(svc, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Customers"
    ws.append(["Full Name", "Email"])
    ws.append(["Annika Rahman", "annika@rahman.co"])
    path = tmp_path / "customers.xlsx"
    wb.save(path)

    di.accept(tmp_path, "customers.xlsx", path.read_bytes())
    report = di.plan(svc.doc, tmp_path, "customers", provider=_mapping({}))
    assert len(report["rows"]) == 1
    assert report["rows"][0]["fullName"] == "Annika Rahman"
    assert "Customers" in report["how"]


def test_the_id_is_the_file_so_a_rename_is_not_a_new_import(tmp_path):
    a = di.accept(tmp_path, "customers.csv", CSV.encode())
    b = di.accept(tmp_path, "customers-final.csv", CSV.encode())
    assert a["id"] == b["id"]


# --------------------------------------------------------------------------- #
# undo
# --------------------------------------------------------------------------- #

def test_undoing_an_import_stops_it_being_loaded(svc, tmp_path):
    """An import undone before the app next boots must not still be waiting in
    the tree: the seeder would apply it and the undo would have undone
    nothing. What an undo does NOT do is delete rows already in the owner's
    database, and the summary says so rather than leaving them to find out."""
    from services.smith import revert as rv

    app = tmp_path / "app"
    _attach(tmp_path)
    report = di.plan(svc.doc, tmp_path, "customers", ignore_columns=["Credit"],
                     provider=_mapping({"Phone No.": "phoneNumber"}))
    out = di.apply(svc, report, app_root=str(app))
    payload = di.payload_path(app, report["import_id"])
    assert payload.is_file()
    assert "does not delete rows already in your database" in di.summary_of(out)

    rv.revert(svc, app_root=str(app))
    assert di.imports_of(svc.doc) == []
    assert not payload.exists(), "the payload outlived the declaration"
    # And the demo rows come back, because the entity holds nothing again.
    seed = json.loads((app / "src" / "db" / "seed.json").read_text())
    assert len(seed["customers"]) == SEED_ROWS


def test_what_it_says_about_a_second_attempt_is_true(svc, tmp_path):
    """An import is recognised by the CONTENTS of the file, so a corrected
    spreadsheet is a different spreadsheet and the rows that already landed
    would land again. The summary must not promise otherwise — row identity
    is not something this can invent."""
    _attach(tmp_path, "Full Name,Joined\nAnnika Rahman,2026-01-04\nBoris Vale,04/02/2026\n")
    report = di.plan(svc.doc, tmp_path, "customers", provider=_mapping({}))
    out = di.apply(svc, report, app_root=str(tmp_path / "app"))
    said = di.summary_of(out)

    assert "row 3: joined is a date" in said, "the reason is named, not just counted"
    assert "only them in it" in said
    assert "a second time" in said
    assert "only the new ones will be added" not in said
