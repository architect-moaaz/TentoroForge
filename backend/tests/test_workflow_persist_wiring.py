"""Tests for ai_extract → db_insert persist wiring (workflow_generator)."""
from services.workflow_generator import _wire_document_persist, _resolve_table


def _defn(nodes, edges):
    return {"definition": {"trigger": {"type": "api_event"}, "nodes": nodes, "edges": edges}}


def _extract(fields):
    return {"id": "ext", "type": "ai_extract",
            "data": {"nodeType": "ai_extract", "config": {"aiExtractFields": fields}}}


def test_resolve_table_prefers_real_schema_name():
    names = {"applicants", "interview_feedback"}
    assert _resolve_table("Applicant", names) == "applicants"
    assert _resolve_table("InterviewFeedback", names) == "interview_feedback"
    # unknown entity → best-effort plural
    assert _resolve_table("Widget", set()) == "widgets"


def test_converts_downstream_create_step_to_db_insert():
    d = _defn(
        [_extract(["fullName", "email"]),
         {"id": "s1", "type": "action", "data": {"label": "Create applicant record", "config": {"actionType": "db_query"}}},
         {"id": "end", "type": "end"}],
        [{"source": "ext", "target": "s1"}, {"source": "s1", "target": "end"}],
    )
    _wire_document_persist(d, {"name": "Applicant Intake", "description": "process applicant"},
                           {"Applicant": {"name": "Applicant"}}, {"applicants"})
    cfg = d["definition"]["nodes"][1]["data"]["config"]
    assert cfg["actionType"] == "db_insert"
    assert cfg["table"] == "applicants"
    assert cfg["values"] == {"fullName": "{{fullName}}", "email": "{{email}}"}


def test_splices_db_insert_when_no_persist_step():
    d = _defn(
        [_extract(["fullName"]), {"id": "end", "type": "end"}],
        [{"source": "ext", "target": "end"}],
    )
    _wire_document_persist(d, {"name": "Applicant Intake", "description": ""},
                           {"Applicant": {"name": "Applicant"}}, {"applicants"})
    nodes = d["definition"]["nodes"]
    ins = [n for n in nodes if (n.get("data") or {}).get("config", {}).get("actionType") == "db_insert"]
    assert len(ins) == 1
    assert ins[0]["data"]["config"]["table"] == "applicants"
    # spliced between extract and end
    edges = d["definition"]["edges"]
    assert any(e["source"] == "ext" and e["target"] == ins[0]["id"] for e in edges)
    assert any(e["source"] == ins[0]["id"] and e["target"] == "end" for e in edges)


def test_noop_without_extract():
    d = _defn([{"id": "s1", "type": "action", "data": {"config": {"actionType": "db_query"}}}], [])
    before = str(d)
    _wire_document_persist(d, {"name": "X"}, {}, {"applicants"})
    assert str(d) == before
