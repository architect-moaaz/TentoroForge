"""The documents a user uploads are kept beside the Blueprint, not folded into
`application.description` (A-03/B-08)."""

from __future__ import annotations

from services.blueprint import documents


def test_store_keeps_order_skips_blanks_and_is_idempotent_on_resend(tmp_path):
    written = documents.store(tmp_path, ["# Spec\n1. Register a patient.", "  ", "Roles: R1"])
    assert [p.name for p in written] == ["document-1.md", "document-2.md"]
    assert documents.texts(tmp_path) == ["# Spec\n1. Register a patient.", "Roles: R1"]
    # The panel resends the same file on every clarifying turn.
    assert documents.store(tmp_path, ["# Spec\n1. Register a patient."]) == []
    assert len(documents.texts(tmp_path)) == 2
    # A new document continues the numbering — the citation stays stable.
    assert [p.name for p in documents.store(tmp_path, ["Appendix"])] == ["document-3.md"]


def test_nothing_stored_reads_as_nothing(tmp_path):
    assert documents.texts(tmp_path) == []
    assert documents.store(tmp_path, []) == []
    assert documents.labelled([]) == ""
    assert documents.addendum(tmp_path, "requirements") == ""
    assert documents.addendum(None, "requirements") == ""


def test_the_labelled_block_numbers_documents_as_the_agents_cite_them(tmp_path):
    documents.store(tmp_path, ["one", "two"])
    block = documents.addendum(tmp_path, "requirements")
    assert "SUPPLIED DOCUMENTS" in block
    assert "--- document 1 ---\none" in block and "--- document 2 ---\ntwo" in block
    # Only the nodes that turn documents into the definition are shown them.
    assert documents.addendum(tmp_path, "application_model")
    assert documents.addendum(tmp_path, "design_system") == ""
    assert documents.addendum(tmp_path, "data_model") == ""


def test_the_requirements_prompt_carries_the_stored_documents(tmp_path):
    from services.blueprint.executors import build_prompt
    from services.blueprint.service import BlueprintService

    svc = BlueprintService.create(output_dir=str(tmp_path), app_id="t1",
                                  name="Clinic", domain="unknown",
                                  description="A clinic visit tracker")
    documents.store(tmp_path, ["1. Reception registers a patient."])
    _, user = build_prompt(svc.doc, "requirements", output_dir=str(tmp_path))
    assert "--- document 1 ---\n1. Reception registers a patient." in user
    # The description stays the user's words: no scaffolding leaked into it.
    assert "SUPPLIED DOCUMENTS" not in svc.doc["application"]["description"]
    _, other = build_prompt(svc.doc, "design_system", output_dir=str(tmp_path))
    assert "SUPPLIED DOCUMENTS" not in other


def test_the_engine_adapter_hands_smith_the_requirements_with_evidence():
    from services.smith.engine_blueprint_adapter import to_smith_fields
    doc = {"application": {"description": "x"}, "requirements": [
        {"id": "REQ-001", "description": "Register a patient.",
         "evidence": [{"type": "document", "source": "document 1", "message": "1."}]},
        {"id": "REQ-009", "description": "gone", "status": "SUPERSEDED"},
    ]}
    got = to_smith_fields(doc)["requirements"]
    assert got == [{"id": "REQ-001", "description": "Register a patient.",
                    "evidence": [{"type": "document", "source": "document 1"}]}]


def test_no_designation_is_no_design_reference():
    from routers.blueprint_generate import _has_design_references
    assert _has_design_references("00000000-0000-0000-0000-000000000000") is False


def test_the_nodes_that_read_documents_are_real_nodes():
    """A node renamed in the DAG would silently stop being shown the
    documents — the list here would just never match again."""
    from services.blueprint.documents import READS_DOCUMENTS
    from services.blueprint.orchestrator import DAG

    assert READS_DOCUMENTS <= set(DAG), sorted(READS_DOCUMENTS - set(DAG))
