"""An owner asks for their records, and gets a file.

Two asks under "Can I trust this?" reached nothing. "Can I get all this out as
a spreadsheet?" reached the `export` command, which hands over a Dockerfile and
the source — the DEFINITION, never a single row. "Back it up somewhere" reached
no verb at all.

What is pinned here is the part that would be easy to get quietly wrong: the
CSV has to carry the columns the DATABASE has (not the ones a second walk over
the Blueprint would infer), the credential column must never leave, the
scoping the application enforces has to be SAID rather than silently flattened,
and "backed up" must not turn into a promise of something scheduled.
"""
import json
import zipfile
from pathlib import Path

import pytest

from services import project_exports
from services.smith import records_out
from services.smith.section_change import SectionChangeError


NURSES = '''
import { pgTable, uuid, text, timestamp } from "drizzle-orm/pg-core";
export const nurses = pgTable("nurses", {
  id: uuid("id").primaryKey().defaultRandom(),
  fullName: text("full_name").notNull(),
  ownerId: uuid("owner_id").references(() => users.id),
  createdAt: timestamp("created_at").defaultNow(),
});
'''

USERS = '''
import { pgTable, uuid, text, boolean } from "drizzle-orm/pg-core";
export const users = pgTable("users", {
  id: uuid("id").primaryKey().defaultRandom(),
  email: text("email").notNull().unique(),
  password: text("password").notNull(),
  isActive: boolean("is_active").default(true),
});
'''

DOC = {
    "application": {"name": "Nurse Roster"},
    "data": {"entities": [
        {"id": "ENT-1", "name": "Nurse", "table": "nurses", "fields": []},
        {"id": "ENT-2", "name": "UserAccount", "table": "users", "fields": []},
    ]},
    "security": {"ownershipRules": [
        {"entity": "Nurse", "column": "ownerId", "kind": "scope",
         "scope": "user", "unscopedRoles": ["Admin"]},
    ]},
}


@pytest.fixture
def project(tmp_path):
    """A project directory shaped like one a build leaves behind."""
    app = tmp_path / "app" / "src" / "db" / "schema"
    app.mkdir(parents=True)
    (app / "nurse.ts").write_text(NURSES, "utf-8")
    (app / "user.ts").write_text(USERS, "utf-8")
    (app / "index.ts").write_text('export * from "./nurse";\n', "utf-8")
    (tmp_path / "app" / ".env.local").write_text(
        "DATABASE_URL=postgres://postgres:postgres@localhost:5432/app_wzja848q\n", "utf-8")
    bp = tmp_path / ".forge" / "blueprint"
    bp.mkdir(parents=True)
    (bp / "current.json").write_text(json.dumps(DOC), "utf-8")
    return tmp_path


@pytest.fixture
def reader():
    """Rows in the order the columns were asked for, and what was asked."""
    asked: list[tuple[str, str, tuple[str, ...]]] = []

    def read(url, table, columns):
        asked.append((url, table, tuple(columns)))
        if table == "nurses":
            yield ("n1", "Ada Lovelace", "u1", None)
            yield ("n2", "Grace Hopper", "u2", None)
        else:
            yield ("u1", "ada@example.com", True)

    read.asked = asked                     # type: ignore[attr-defined]
    return read


# ------------------------------------------------- the columns are the app's

def test_the_columns_come_off_the_application_not_a_second_derivation(project, reader):
    """`fullName` is the header; `full_name` is what the SELECT says.

    The entities in the Blueprint declare NO fields at all here — a second walk
    over them would produce an empty spreadsheet. The schema module drizzle-kit
    pushed is the only thing that knows what is in the database.
    """
    records_out.export_records(str(project), "p1", entity="Nurse", reader=reader)

    _url, table, columns = reader.asked[0]
    assert table == "nurses"
    assert columns == ("id", "full_name", "owner_id", "created_at")


def test_the_header_is_the_word_the_owner_sees(project, reader):
    out = records_out.export_records(str(project), "p1", entity="Nurse", reader=reader)
    data, _media, _name = project_exports.read_export(
        str(project), out["url"].rsplit("/", 1)[-1])
    assert data.decode("utf-8-sig").splitlines()[0] == "id,fullName,ownerId,createdAt"


def test_the_database_read_is_the_one_the_application_opens(project, reader):
    """Not `default_database_url`. `run.sh` rewrites the port in this file, and
    reading the wrong database is reading somebody else's records."""
    records_out.export_records(str(project), "p1", reader=reader)
    assert reader.asked[0][0].endswith("/app_wzja848q")


# ---------------------------------------------------- credentials never leave

def test_the_password_column_is_never_selected(project, reader):
    records_out.export_records(str(project), "p1", reader=reader)
    for _url, table, columns in reader.asked:
        assert "password" not in columns, table


def test_the_omission_is_stated_rather_than_silent(project, reader):
    out = records_out.export_records(str(project), "p1", reader=reader)
    assert out["credentials_omitted"] == ["users"]
    assert "password" in records_out.summary_of(out) or \
        "credentials" in records_out.summary_of(out)


# --------------------------------------------------------- whose rows these are

def test_a_scoped_entity_is_named_as_scoped(project, reader):
    """The application gives each user only their own nurses. The owner gets
    all of them — and is told that is what they are holding."""
    out = records_out.export_records(str(project), "p1", reader=reader)
    said = out["scoped"]["Nurse"]
    assert "ownerId" in said and "one user" in said
    assert "Admin" in said
    assert "every one of them" in records_out.summary_of(out)


def test_an_unscoped_entity_claims_nothing(project, reader):
    out = records_out.export_records(str(project), "p1", reader=reader)
    assert "UserAccount" not in out["scoped"]


# ------------------------------------------------------------ what comes back

def test_one_entity_is_one_csv(project, reader):
    out = records_out.export_records(str(project), "p1", entity="Nurse", reader=reader)
    assert out["filename"] == "nurses.csv"
    assert out["counts"] == {"Nurse": 2}


def test_the_whole_application_is_a_zip_of_them(project, reader):
    out = records_out.export_records(str(project), "p1", reader=reader)
    assert out["filename"].endswith(".zip")
    data, media, _name = project_exports.read_export(
        str(project), out["url"].rsplit("/", 1)[-1])
    assert media == "application/zip"
    with zipfile.ZipFile(_written(project, out)) as zf:
        assert sorted(zf.namelist()) == ["nurses.csv", "users.csv"]


def test_an_entity_spelled_any_of_its_ways_finds_the_same_one(project, reader):
    for spelling in ("Nurse", "nurses", "nurse"):
        out = records_out.export_records(str(project), "p1", entity=spelling,
                                         reader=reader)
        assert out["counts"] == {"Nurse": 2}


def test_an_entity_that_does_not_exist_is_refused_by_name(project, reader):
    with pytest.raises(SectionChangeError) as exc:
        records_out.export_records(str(project), "p1", entity="Doctor", reader=reader)
    assert "Doctor" in str(exc.value)


def test_an_entity_with_no_table_is_reported_not_dropped(project, reader):
    """A declared entity the build never made a table for must be NAMED as
    missing. An export that quietly contains three of four kinds of record is
    worse than one that says which is absent."""
    doc = json.loads((project / ".forge" / "blueprint" / "current.json").read_text())
    doc["data"]["entities"].append({"id": "ENT-3", "name": "Ward", "table": "wards",
                                    "fields": []})
    (project / ".forge" / "blueprint" / "current.json").write_text(json.dumps(doc))

    out = records_out.export_records(str(project), "p1", reader=reader)
    assert any("Ward" in line for line in out["skipped"])
    assert "Ward" in records_out.summary_of(out)


def test_an_empty_table_still_gets_its_file(project):
    """"There are no nurses yet" and "nurses were left out" are different
    facts, and an absent file states the wrong one."""
    out = records_out.export_records(str(project), "p1", entity="Nurse",
                                     reader=lambda u, t, c: iter(()))
    assert out["counts"] == {"Nurse": 0}
    assert _written(project, out).read_text("utf-8-sig").strip() == \
        "id,fullName,ownerId,createdAt"


# ------------------------------------------------------------------ the values

@pytest.mark.parametrize("value,written", [
    (None, ""),
    (True, "true"),
    (False, "false"),
    ({"b": 1, "a": 2}, '{"a": 2, "b": 1}'),
    (["x", "y"], '["x", "y"]'),
])
def test_a_value_is_written_as_a_spreadsheet_reads_it(value, written):
    assert records_out.cell(value) == written


def test_a_timestamp_is_written_as_a_date_not_a_python_repr():
    import datetime

    assert records_out.cell(datetime.datetime(2026, 9, 18, 9, 30)) == "2026-09-18T09:30:00"


# --------------------------------------------------------------- the backup

def test_a_backup_carries_the_records_and_the_definition(project, reader):
    out = records_out.back_up(str(project), "p1", reader=reader)
    with zipfile.ZipFile(_written(project, out)) as zf:
        names = set(zf.namelist())
        assert "records/nurses.csv" in names
        assert "definition/blueprint.json" in names
        assert "definition/schema/nurse.ts" in names
        assert "README.md" in names


def test_the_archive_says_what_it_is_not(project, reader):
    """The whole point. A zip found on a drive in two years has no chat around
    it, so the limits have to be inside the file."""
    out = records_out.back_up(str(project), "p1", reader=reader)
    with zipfile.ZipFile(_written(project, out)) as zf:
        readme = zf.read("README.md").decode("utf-8")
    assert "Nothing is scheduled" in readme
    assert "no restore button" in readme
    assert "credentials are not in here" in readme


def test_the_reply_promises_nothing_scheduled(project, reader):
    said = records_out.summary_of(records_out.back_up(str(project), "p1", reader=reader))
    assert "Nothing is scheduled" in said
    assert "no restore button" in said.lower() or "restore button" in said


def test_neither_verb_writes_anything_to_the_blueprint(project, reader):
    """Taking a copy of an application is not a change to it. A change history
    entry here would put an undo in front of somebody's export."""
    before = (project / ".forge" / "blueprint" / "current.json").read_text()
    records_out.export_records(str(project), "p1", reader=reader)
    records_out.back_up(str(project), "p1", reader=reader)
    assert (project / ".forge" / "blueprint" / "current.json").read_text() == before


# ------------------------------------------------------------- honest refusals

def test_a_project_with_no_application_is_told_why(tmp_path):
    out = records_out.run(str(tmp_path), "p1", reader=lambda u, t, c: iter(()))
    assert out["applied"] is False
    assert "no built application" in out["reason"]


def test_an_application_with_no_database_url_is_told_why(project, reader):
    (project / "app" / ".env.local").write_text("NEXTAUTH_SECRET=x\n", "utf-8")
    out = records_out.run(str(project), "p1", reader=reader)
    assert out["applied"] is False
    assert "database" in out["reason"]


def test_a_read_that_fails_sends_nothing_rather_than_half(project):
    def broken(url, table, columns):
        raise RuntimeError("connection refused")
        yield  # pragma: no cover

    out = records_out.run(str(project), "p1", reader=broken)
    assert out["applied"] is False
    assert "connection refused" in out["reason"]
    assert "nothing rather than a partial copy" in out["reason"]


def test_a_column_name_that_is_not_an_identifier_is_refused(project):
    with pytest.raises(SectionChangeError):
        records_out._quote('id"; DROP TABLE nurses; --')


# --------------------------------------------------------------- the transport

def test_an_export_lands_in_its_own_projects_directory(project, reader):
    out = records_out.export_records(str(project), "p1", entity="Nurse", reader=reader)
    assert _written(project, out).parent == project / ".forge" / "exports"


def test_a_traversing_id_reads_nothing(project, reader):
    records_out.export_records(str(project), "p1", entity="Nurse", reader=reader)
    assert project_exports.read_export(str(project), "../../etc/passwd") is None
    assert project_exports.read_export(str(project), "nope") is None


def test_the_download_name_cannot_break_out_of_a_header(project):
    rec = project_exports.save_export(
        str(project), 'ev"il\nname.csv', b"a,b\n", "text/csv")
    assert '"' not in rec["filename"] and "\n" not in rec["filename"]


def test_the_url_is_relative_to_the_platform(project, reader):
    out = records_out.export_records(str(project), "p1", entity="Nurse", reader=reader)
    assert out["url"] == f"/api/projects/p1/exports/{_id(out)}"


def _id(out: dict) -> str:
    return out["url"].rsplit("/", 1)[-1]


def _written(project: Path, out: dict) -> Path:
    return project / ".forge" / "exports" / _id(out)


# ------------------------------------------------------------- the turn itself

def _session(project, verb, monkeypatch, reader):
    from tests.services._front_door import SmithSession

    monkeypatch.setattr(records_out, "postgres_reader", reader)
    return SmithSession(
        project_id="p1", output_dir=str(project),
        guards_fn=lambda *a, **kw: [],
        understand_ask_fn=lambda m, ctx, **kw: {"verb": verb},
        iteration_move_fn=lambda *a, **kw: None)


# The spreadsheet turn is `export_data` (services.smith.data_export, tested in
# test_smith_exports_a_spreadsheet.py); both branches built one, and the merge
# kept that one. This module's verb is the backup.

def test_a_turn_asking_for_a_backup_hands_over_a_link(project, reader, monkeypatch):
    session = _session(project, "back_up", monkeypatch, reader)
    result = session.run_iteration(user_message="can I take a backup?")
    assert result.status == "resolved"
    assert "/api/projects/p1/exports/" in result.answer


def test_a_turn_asking_for_a_backup_says_what_it_is_not(project, reader, monkeypatch):
    session = _session(project, "back_up", monkeypatch, reader)
    result = session.run_iteration(user_message="back it up somewhere")
    assert result.status == "resolved"
    assert "Nothing is scheduled" in result.answer
    assert "no restore button" in result.answer


def test_a_turn_touches_no_files(project, reader, monkeypatch):
    """`touched_paths` drives the re-index and the diff view. An export is not
    an edit, and reporting one as an edit would put it in both."""
    session = _session(project, "back_up", monkeypatch, reader)
    assert session.run_iteration(user_message="back it up").touched_paths == []


def test_neither_verb_needs_a_field_before_it_can_run():
    """"Can I get all this out?" names nothing. A required slot would answer
    the question with a question."""
    from services.smith.verbs import missing_fields

    assert missing_fields({"verb": "export_data"}) == []
    assert missing_fields({"verb": "back_up"}) == []


def test_both_verbs_are_in_the_capability_list():
    from services.smith.capabilities import summary, unaccounted

    assert unaccounted() == frozenset()
    assert "spreadsheet" in summary()
    assert "backup" in summary()


def test_the_capability_list_separates_the_source_from_the_records():
    """`export` has meant the SOURCE here since before there were records to
    confuse it with, and an owner who types "export" means their data."""
    from services.smith.capabilities import summary

    assert "the SOURCE away as a zip" in summary()


# ------------------------------------------------------- the agent's tool path

def _canned(steps: list[dict]):
    """A `query_fn` matching Smith's stream boundary, capturing the catalog."""
    captured: dict = {"tool_catalog": None}

    def _fn(system_prompt, messages, tool_catalog):
        captured["tool_catalog"] = tool_catalog
        for step in steps:
            yield step

    _fn.captured = captured                # type: ignore[attr-defined]
    return _fn


def test_the_agent_is_offered_both_tools():
    """A tool the model is never told about is a tool it never calls — which
    is how `revert` came to have a handler nothing could reach."""
    from services import smith_tools

    names = {t["name"] for t in smith_tools.TOOL_CATALOG}
    assert {"export_data", "back_up"} <= names


def test_the_agent_gets_a_link_when_it_calls_the_tool(project, reader, monkeypatch):
    from agents.smith_agent import run_smith_agent

    monkeypatch.setattr(records_out, "postgres_reader", reader)
    calls: list[dict] = []

    def _fn(system_prompt, messages, tool_catalog):
        yield {"tool": "back_up", "args": {}}
        calls.append(messages[-1] if messages else {})
        yield {"tool": "answer", "args": {"text": "sent"}}

    run_smith_agent(user_message="back it up somewhere",
                    output_dir=str(project), recall_block="",
                    query_fn=_fn, project_id="p1")

    assert calls, "the tool result never reached the model"
    result = calls[0]["content"]
    assert "/api/projects/p1/exports/" in result
    # The sentence the model must relay travels WITH the result, because a
    # model summarising `{"applied": true}` in its own words promises a
    # backup service nobody built.
    assert "Nothing entered from now on" in result or "not a live one" in result


def test_the_agent_tool_is_told_no_when_there_is_no_project(project, reader, monkeypatch):
    """A link with no project in it reaches nobody's records, so the tool
    refuses with the reason instead of writing `/api/projects//exports/…`."""
    from services import smith_tools

    monkeypatch.setattr(records_out, "postgres_reader", reader)
    out = smith_tools.PROJECT_HANDLERS["back_up"](str(project), {}, "")
    assert out["applied"] is False
    assert "without a project" in out["reason"]


def test_the_backup_tool_carries_its_limits_into_the_result(project, reader, monkeypatch):
    from services import smith_tools

    monkeypatch.setattr(records_out, "postgres_reader", reader)
    out = smith_tools.PROJECT_HANDLERS["back_up"](str(project), {}, "p1")
    assert out["applied"] is True
    assert "Nothing is scheduled" in out["summary"]
    assert "no restore button" in out["summary"]


def test_the_project_id_is_not_threaded_through_the_tool_args(project, reader, monkeypatch):
    """Several handlers copy `args` straight into a recorded patch. An id
    injected into every call would ride into payloads that have no business
    holding one, which is why it is bound at the dispatch instead."""
    from agents.smith_agent import run_smith_agent

    monkeypatch.setattr(records_out, "postgres_reader", reader)
    seen: list[dict] = []

    def _fn(system_prompt, messages, tool_catalog):
        yield {"tool": "export_records", "args": {"entity": "Nurse"}}
        yield {"tool": "answer", "args": {"text": "sent"}}

    out = run_smith_agent(user_message="export the nurses",
                          output_dir=str(project), recall_block="",
                          query_fn=_fn, project_id="p1")
    args = [e.get("args") or {} for e in out["trace"] if e.get("tool") == "export_records"]
    assert args and all("_project_id" not in a for a in args), args


def test_the_orchestrator_hands_its_project_id_to_the_agent():
    """`smith_orchestrator.run` accepted a `project_id` and read it with
    nothing. It is the id these tools need, and the seam its tests inject
    still takes exactly the five arguments it always did."""
    import inspect

    from services import smith_orchestrator

    seam = inspect.signature(smith_orchestrator._default_smith).parameters
    assert "project_id" in seam and seam["project_id"].default == ""
