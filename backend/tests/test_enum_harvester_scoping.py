"""HAR-1: enum harvester must be entity-scoped and reject noise.

Before this fix a Drive's Status dropdown showed 17 garbage values pulled
from every workflow across the app (entity names, action-verb labels,
mixed statuses across entities). The fix has two parts:

1. Priority-order fix in ``ensure_enum_selects._values_for``: the
   per-entity ``status_idx`` (from workflow_action_mapper) now runs
   BEFORE the global ``harvest_workflow_statuses``. Before, the global
   dict always won for status columns because it was checked first.

2. Garbage filter in the global fallback: values that look like entity
   names, workflow names, or section headers (``"Status"``, ``"Foo Status"``)
   are dropped so a poorly-authored workflow can't pollute unrelated
   status dropdowns.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.form_scaffold import _is_status_value_garbage


# --------------------------------------------------------------------------- #
# _is_status_value_garbage — the noise filter
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("value,entity_names,workflow_names,expected", [
    # (a) Entity names are never status values.
    ("CandidateProfile", {"CandidateProfile", "RecruitmentDrive"}, set(), True),
    ("RecruitmentDrive", {"CandidateProfile", "RecruitmentDrive"}, set(), True),
    # (b) Workflow names are never status values.
    ("Create Assignment",
     set(), {"CreateAssignment", "InsertProfile"}, True),
    ("Insert Profile",
     set(), {"CreateAssignment", "InsertProfile"}, True),
    # (c) Section-header patterns — "Status", "X Status", "Status X".
    ("Status", set(), set(), True),
    ("Candidate Status", set(), set(), True),
    ("Assignment Status", set(), set(), True),
    ("Status Screened", set(), set(), True),
    ("Status Offer", set(), set(), True),
    # (d) Real status values — MUST pass through.
    ("Hired", set(), set(), False),
    ("Rejected", set(), set(), False),
    ("Shortlisted", set(), set(), False),
    ("cv_screened", set(), set(), False),
    ("interview_completed", set(), set(), False),
    ("offer_accepted", set(), set(), False),
    ("Draft", set(), set(), False),
    ("Open", set(), set(), False),
    ("Closed", set(), set(), False),
])
def test_is_status_value_garbage_classifies_correctly(
    value, entity_names, workflow_names, expected,
):
    assert _is_status_value_garbage(
        value, entity_names, workflow_names,
    ) is expected


def test_case_insensitive_entity_match():
    """A workflow value ``"candidateprofile"`` (lowercased) still matches the
    entity ``"CandidateProfile"``."""
    assert _is_status_value_garbage(
        "candidateprofile", {"CandidateProfile"}, set(),
    ) is True


# --------------------------------------------------------------------------- #
# ensure_enum_selects — priority-order integration
# --------------------------------------------------------------------------- #

def _mk_registry(tmp_path: Path, entities: dict) -> None:
    reg = {"entities": entities}
    (tmp_path / "registry.json").write_text(json.dumps(reg))


def _mk_workflow(tmp_path: Path, name: str, doc: dict) -> None:
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir(exist_ok=True)
    (wf_dir / f"{name}.json").write_text(json.dumps(doc))


def _mk_form_schema(tmp_path: Path, route: str, workflow: str, field: str) -> Path:
    """Minimal create-form schema with one status Input Smith would upgrade."""
    sdir = tmp_path / "src" / "schemas"
    sdir.mkdir(parents=True, exist_ok=True)
    fp = sdir / f"{route}.json"
    fp.write_text(json.dumps({
        "route": f"/{route}",
        "root": {
            "type": "Form",
            "props": {
                "action": {"workflow": workflow, "kind": "submit"},
                "onSuccess": {"kind": "navigate"},
            },
            "children": [
                {"type": "Input", "props": {"name": field, "label": "Status"}},
            ],
        },
    }))
    return fp


def test_per_entity_status_workflow_beats_polluted_global(tmp_path):
    """Per-entity ``status_idx`` (from workflow_action_mapper) must be
    consulted BEFORE the global ``wf_statuses`` for status columns. This
    is the priority-order half of HAR-1."""
    from services.form_scaffold import ensure_enum_selects

    # Registry with two entities.
    _mk_registry(tmp_path, {
        "RecruitmentDrive": {
            "table": "recruitment_drives",
            "columns": [{"name": "status", "type": "varchar"}],
        },
        "CandidateProfile": {
            "table": "candidate_profiles",
            "columns": [{"name": "status", "type": "varchar"}],
        },
    })

    # A CandidateProfile workflow with real statuses — but ALSO garbage
    # (entity names). The GLOBAL harvester would leak these across
    # entities; the per-entity path must scope them out.
    _mk_workflow(tmp_path, "candidate-status", {
        "name": "UpdateCandidateStatus",
        "processVariables": [{"name": "targetStatus"}],
        "definition": {
            "nodes": [
                {
                    "id": "n1",
                    "data": {
                        "config": {
                            "actionType": "db_update",
                            "entity": "candidate_profiles",
                            "where": {"id": "candidateId"},
                            "values": {"status": "{{targetStatus}}"},
                        },
                    },
                },
                {
                    "id": "n2",
                    "data": {
                        "config": {
                            "actionType": "gateway",
                            "expression": "targetStatus == 'Hired'",
                        },
                    },
                },
                {
                    "id": "n3",
                    "data": {
                        "config": {
                            "actionType": "gateway",
                            "expression": "targetStatus == 'Rejected'",
                        },
                    },
                },
            ],
        },
    })

    # A form that submits a RecruitmentDrive create — its Status dropdown
    # must NOT be populated with Candidate's Hired/Rejected. It should get
    # NOTHING from the harvester (workflow doesn't target it) and fall
    # through to curated_enum_options → returns None → Input stays Input.
    _mk_form_schema(tmp_path, "recruitment-drive-new",
                    "CreateRecruitmentDrive", "status")

    ensure_enum_selects(str(tmp_path))

    schema = json.loads(
        (tmp_path / "src" / "schemas" / "recruitment-drive-new.json").read_text()
    )
    inputs = _find_all_typed(schema, ("Input", "Select"))
    status_node = next(n for n in inputs if n["props"].get("name") == "status")
    # No cross-entity pollution → node stays as Input (harvester found
    # nothing scoped to RecruitmentDrive). It's OK for the field to stay
    # a text Input in this test — the point is that Hired/Rejected did
    # NOT leak in.
    if status_node.get("type") == "Select":
        opts = status_node["props"].get("options") or []
        vals = [o.get("value") for o in opts if isinstance(o, dict)]
        assert "Hired" not in vals, "Candidate's Hired leaked into Drive's Status"
        assert "Rejected" not in vals, "Candidate's Rejected leaked into Drive's Status"


def _find_all_typed(schema, types):
    """Recursively find every node of given types."""
    out = []
    def walk(n):
        if isinstance(n, dict):
            if n.get("type") in types:
                out.append(n)
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(schema)
    return out
