"""Slice 3 — coverage/shadow proof for deterministic-first workflows.

Feeds representative plan shapes through the deterministic generator and asserts
each workflow comes out EXECUTABLE (passes the same executability contract the
guard uses). This is the evidence that the deterministic path covers the common
patterns, so making it primary (slice 2, default on) is safe — anything it can't
make executable falls through to the LLM executability guard at runtime.
"""
from services.workflow_generator import _generate_from_step_dicts, _generate_from_step_names
from services.workflow_executability import is_executable_workflow, action_node_executable


_MODELS = {
    "Applicant": {
        "name": "Applicant",
        "fields": [
            {"name": "id", "primaryKey": True},
            {"name": "fullName"}, {"name": "email"}, {"name": "status"},
            {"name": "recruiterId"},
        ],
    },
    "RecruitmentDrive": {
        "name": "RecruitmentDrive",
        "fields": [
            {"name": "id", "primaryKey": True},
            {"name": "title"}, {"name": "location"}, {"name": "status"},
        ],
    },
}
_TABLES = {"applicants", "recruitment_drives", "users"}
_WF = {"name": "Applicant Intake", "description": "process new applicants"}


def _action_nodes(defn):
    return [n for n in defn["nodes"] if n.get("type") == "action"]


def test_declared_crud_and_notify_workflow_is_executable():
    # A status-transition step must name the target state ("... to Hired") so the
    # generator emits a real literal — a self-referential {{status}} with no trigger
    # input resolves to NULL and wipes the column (the "button does nothing" defect,
    # now flagged non-executable by the mutation-resolvability gate).
    steps = [
        {"name": "Create applicant record", "node_type": "db_insert"},
        {"name": "Mark applicant as Hired", "node_type": "db_update"},
        {"name": "Notify recruiter of new applicant", "node_type": "send_notification"},
    ]
    wf = _generate_from_step_dicts(_WF, steps, _MODELS, table_names=_TABLES)
    assert is_executable_workflow(wf)                      # every action node has real params
    acts = [(n["data"]["config"].get("actionType")) for n in _action_nodes(wf["definition"])]
    assert acts == ["db_insert", "db_update", "send_notification"]
    upd = next(n for n in _action_nodes(wf["definition"])
               if n["data"]["config"].get("actionType") == "db_update")
    assert upd["data"]["config"]["values"]["status"] == "Hired"  # literal, not {{status}}


def test_keyword_classified_plain_names_are_executable():
    """No declared node_type — steps are just names → keyword-classified, still executable."""
    names = ["Create applicant record", "Set the applicant status to Hired", "Send confirmation email"]
    wf = _generate_from_step_names(_WF, names, _MODELS, table_names=_TABLES)
    assert is_executable_workflow(wf)
    for n in _action_nodes(wf["definition"]):
        assert action_node_executable(n), n["data"]["config"]


def test_no_dead_db_query_comment_stubs():
    """Regression: the old builder emitted `db_query` with a SQL comment (a no-op).
    Deterministic output must never contain that."""
    names = ["Create drive", "Update drive status", "Schedule reminder", "Do the thing"]
    wf = _generate_from_step_dicts(
        {"name": "Drive Flow", "description": "recruitment drive"},
        [{"name": n} for n in names], _MODELS, table_names=_TABLES,
    )
    blob = str(wf)
    assert "-- " not in blob                               # no SQL-comment stub
    assert '"db_query"' not in blob or all(                # if any db_query, it has a real query
        c["data"]["config"].get("query", "").strip().startswith("--") is False
        for c in _action_nodes(wf["definition"])
    )


def test_unresolvable_entity_degrades_to_executable_marker():
    """A workflow with no matching entity still produces executable nodes (progress
    markers), never prose/no-ops."""
    wf = _generate_from_step_dicts(
        {"name": "Mystery", "description": ""},
        [{"name": "Frobnicate the widget"}, {"name": "Reticulate splines"}],
        {}, table_names=set(),
    )
    assert is_executable_workflow(wf)
    for n in _action_nodes(wf["definition"]):
        assert n["data"]["config"].get("actionType") == "set_variable"


def test_generate_definitions_overwrites_noop_stub(tmp_path):
    """A pre-existing non-executable stub (as the early sync used to write) must be
    replaced by generate_workflow_definitions, not skipped for having nodes."""
    import json
    from services.workflow_generator import generate_workflow_definitions
    from services.workflow_executability import is_executable_workflow
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    # a no-op stub with non-empty nodes + the same name the plan will use
    (wf_dir / "stub.json").write_text(json.dumps({
        "id": "stub", "name": "Intake",
        "definition": {"trigger": {"type": "api_event"},
                       "nodes": [{"id": "trigger", "type": "trigger", "data": {"config": {}}},
                                 {"id": "s1", "type": "action",
                                  "data": {"config": {"actionType": "custom", "nodeType": "custom"}}}],
                       "edges": []}}), encoding="utf-8")
    plan = {"workflows": [{
        "name": "Intake",
        "steps": [{"id": "trigger", "type": "trigger", "next": "ins"},
                  {"id": "ins", "type": "action", "next": "end",
                   "config": {"actionType": "db_insert", "table": "applicants",
                              "fields": ["email"]}},
                  {"id": "end", "type": "end"}]}]}
    generate_workflow_definitions(str(tmp_path), plan)
    # find the Intake file and assert it's now executable
    ok = False
    for f in wf_dir.glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("name") == "Intake" and is_executable_workflow(d):
            ok = True
    assert ok, "generate_workflow_definitions left the no-op stub in place"


def test_generate_definitions_preserves_executable_and_makes_no_duplicate(tmp_path):
    """The load-bearing new behavior: an already-EXECUTABLE same-name file must be
    left byte-for-byte untouched — not clobbered, and no duplicate file created.
    (Guards against reintroducing the old node-count skip-guard, which overwrote
    good definitions.)"""
    import json
    from services.workflow_generator import generate_workflow_definitions
    from services.workflow_step_translator import translate_workflow
    from services.workflow_executability import is_executable_workflow
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    # A genuinely executable "Intake" definition (real db_insert action + trigger + end).
    good = translate_workflow(
        {"name": "Intake", "steps": [
            {"id": "trigger", "type": "trigger", "next": "ins"},
            {"id": "ins", "type": "action", "next": "end",
             "config": {"actionType": "db_insert", "table": "applicants", "fields": ["email"]}},
            {"id": "end", "type": "end"}]},
        {}, set())
    assert is_executable_workflow(good), "fixture must be executable for this test to mean anything"
    good_file = wf_dir / "good.json"
    good_file.write_text(json.dumps(good, indent=2), encoding="utf-8")
    before = good_file.read_text(encoding="utf-8")

    # A DIFFERENT but also-valid rich step list for the same workflow name.
    plan = {"workflows": [{
        "name": "Intake",
        "steps": [{"id": "trigger", "type": "trigger", "next": "upd"},
                  {"id": "upd", "type": "action", "next": "end",
                   "config": {"actionType": "db_update", "table": "applicants",
                              "fields": ["status"]}},
                  {"id": "end", "type": "end"}]}]}
    count = generate_workflow_definitions(str(tmp_path), plan)

    # Nothing written: return count is 0.
    assert count == 0, "an already-executable workflow should not be regenerated"
    # Existing bytes untouched.
    assert good_file.read_text(encoding="utf-8") == before, "executable definition was clobbered"
    # No duplicate Intake-named file created — exactly one file with name=='Intake'.
    intake_files = [f for f in wf_dir.glob("*.json")
                    if json.loads(f.read_text(encoding="utf-8")).get("name") == "Intake"]
    assert len(intake_files) == 1, f"expected 1 Intake file, found {len(intake_files)}"
