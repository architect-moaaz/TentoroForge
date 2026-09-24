"""The import is reachable by saying so, and the contract declares it first.

A seam nothing dispatches to is a feature nobody has. `import_data` has to be
in five places or the sentence an owner types reaches nothing: the verb set,
the classifier's list, the capability listing, the session's dispatch and the
tool catalog the agent loop reads. And `data.imports` has to be in the emitted
contract BEFORE anything writes it — `data` is `additionalProperties: false`,
so an undeclared field makes every generated application unmodifiable on its
next save. That has shipped three times (see
`test_every_runtime_field_is_declared_first`); this is the check for this one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.blueprint.service import BlueprintService
from services.smith import capabilities, data_import as di
from services.smith.tools import render as _catalogue
from services.smith.verbs import REQUIRED_BY_VERB, VERB_HELP, is_known, missing_fields

CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "blueprint.schema.json"


def test_the_verb_asks_for_which_records_and_nothing_else():
    """The FILE is not a slot, for the reason `revert` has none: it is always
    the one just attached, and an attachment id is a thing only Smith has
    seen."""
    assert REQUIRED_BY_VERB["import_data"] == {"entity"}
    assert is_known({"verb": "import_data"})
    assert missing_fields({"verb": "import_data", "entity": "customers"}) == []
    assert missing_fields({"verb": "import_data"}) == ["entity"]


def test_the_model_is_told_what_it_is_for():
    assert "`import_data`" in _catalogue()
    assert "spreadsheet" in _catalogue()
    help_text = VERB_HELP["import_data"]
    assert "customer spreadsheet" in help_text
    assert "writes nothing" in help_text


def test_it_is_in_the_list_smith_gives_when_asked_what_it_can_do():
    groups = [g for g in capabilities.GROUPS if "import_data" in g[2]]
    assert len(groups) == 1
    assert "spreadsheet" in groups[0][1]


def test_the_tool_loop_can_call_it_too():
    from services import smith_tools

    assert "import_data" in smith_tools.READONLY_HANDLERS
    entry = [t for t in smith_tools.TOOL_CATALOG if t["name"] == "import_data"]
    assert len(entry) == 1
    # The dry run is the thing the model must not skip past.
    assert "WRITES NOTHING" in entry[0]["desc"]
    assert "confirm=true" in entry[0]["desc"]


def test_the_contract_declares_the_import_before_anything_writes_it():
    schema = json.loads(CONTRACT.read_text(encoding="utf-8"))
    data = schema["properties"]["data"]
    assert data.get("additionalProperties") is False, (
        "if the contract stops refusing unknown keys this test proves nothing")
    assert "imports" in (data.get("properties") or {}), (
        "declare it in packages/schema/src/blueprint first, then "
        "`npm run build` and `npm run emit:blueprint-schema`")
    declared = set(data["properties"]["imports"]["items"]["properties"])
    assert {"id", "entity", "table", "source", "rowCount", "rejectedCount",
            "columns", "ignoredColumns", "importedAt"} <= declared
    # The rows are NOT a Blueprint field, and nothing should quietly add one.
    assert "rows" not in declared


def test_a_declared_import_survives_a_round_trip_through_validation(tmp_path):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="L", domain="retail")
    svc.doc["data"] = {
        "entities": [{"id": "ENTITY-001", "name": "Customer", "table": "customers",
                      "fields": [{"name": "fullName", "type": "string"}]}],
        "imports": [{"id": "IMP-0123456789", "entity": "ENTITY-001",
                     "table": "customers", "source": "customers.csv",
                     "rowCount": 412, "rejectedCount": 3,
                     "columns": [{"column": "Full Name", "field": "fullName"}],
                     "ignoredColumns": ["Credit"],
                     "importedAt": "2026-09-18T09:00:00+00:00"}]}
    svc.validate()
    svc.save()
    assert di.imports_of(BlueprintService.load(output_dir=str(tmp_path)).doc)[0]["rowCount"] == 412


# --------------------------------------------------------------------------- #
# the turn
# --------------------------------------------------------------------------- #

CSV = "Full Name,Email\nAnnika Rahman,annika@rahman.co\nBoris Vale,boris@vale.io\n"


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Ledger",
                                domain="retail")
    s.doc["data"] = {"entities": [{
        "id": "ENTITY-001", "name": "Customer", "table": "customers",
        "fields": [{"name": "id", "type": "uuid", "primaryKey": True},
                   {"name": "fullName", "type": "string", "required": True},
                   {"name": "email", "type": "email"}]}]}
    s.save()
    return s


def _session(svc, verb: dict):
    from tests.services._front_door import SmithSession

    return SmithSession(project_id="p1", output_dir=str(svc.output_dir),
                        guards_fn=lambda *a, **kw: [],
                        understand_ask_fn=lambda m, ctx, **kw: dict(verb),
                        iteration_move_fn=lambda *a, **kw: None)


def test_the_turn_describes_the_import_and_the_next_one_loads_it(svc, monkeypatch):
    monkeypatch.setattr(di, "_propose", lambda *a, **k: {})
    di.accept(svc.output_dir, "customers.csv", CSV.encode())

    session = _session(svc, {"verb": "import_data", "entity": "customers"})
    first = session.run_iteration(
        user_message="here's our customer spreadsheet, load it in")
    assert first.status == "asked"
    assert "2 row(s)" in first.answer
    assert first.options == [di.GO_LABEL, di.NO_LABEL]
    assert di.imports_of(BlueprintService.load(output_dir=str(svc.output_dir)).doc) == []

    # THE YES IS ITS OWN TURN, and it does not go back through the model:
    # an understanding that would refuse still loads what was agreed to.
    session = _session(svc, {"verb": "rename"})
    second = session.run_iteration(user_message="Load them in")
    assert second.status == "resolved"
    assert "Loaded **2 customers**" in second.answer
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    assert di.imports_of(fresh.doc)[0]["rowCount"] == 2


def test_a_spreadsheet_on_a_turn_lands_in_the_inbox_and_its_rows_stay_off_the_prompt(
        svc, tmp_path, monkeypatch):
    """The owner drags the file into chat. What reaches the model is a NOTE —
    the name, the row count, the columns and a few rows — because four hundred
    customers in a prompt is an invitation to type records into a tool call."""
    from services import chat_attachments
    from routers.generate import _sheets_to_inbox

    root = tmp_path / "_attachments"
    monkeypatch.setattr(chat_attachments, "attachments_root", lambda: root)
    rec = chat_attachments.save_attachment(root, "proj1", "customers.csv",
                                           "text/csv", CSV.encode())

    class _Project:
        id = "proj1"

    notes = _sheets_to_inbox(_Project(), str(svc.output_dir), [rec["id"]])
    assert len(notes) == 1
    note = notes[0]["note"]
    assert 'rows="2"' in note and "Full Name, Email" in note
    assert "THE REST OF THE ROWS ARE ON DISK" in note
    # And the seam can now read it, with no id threaded anywhere.
    assert di.newest(svc.output_dir)["filename"] == "customers.csv"


def test_a_spreadsheet_we_cannot_open_says_so_where_a_person_is_watching():
    """`.xls` and `.numbers` have no reader here, and the owner attaching one
    is trying to load their data — so the refusal names the one step that
    makes it work rather than listing the types we accept."""
    from services.chat_attachments import AttachmentError, classify, save_attachment

    assert classify("customers.xlsx", "") == "spreadsheet"
    with pytest.raises(AttachmentError, match="save a copy as CSV"):
        save_attachment("/tmp", "p1", "customers.numbers", "", b"x")
