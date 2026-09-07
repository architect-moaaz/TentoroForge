"""The Recall assembler builds a per-app "generation dossier": the context
engine recalling WHY an app is the way it is (original prompt, plan, entities,
roles, contracts, recent changes) so a later fix-chat diagnoses against intent.

Tests never touch a real database — the DB overlay is exercised with a tiny
chainable stub session that returns canned Conversation rows.
"""
import json

from services.app_recall import (
    RecallContext,
    assemble_recall,
    emit_generation_dossier,
)


# ---------------------------------------------------------------------------
# Fixtures on disk
# ---------------------------------------------------------------------------

def _write_contracts(tmp_path, *, dossier=True, registry=True):
    contracts = tmp_path / "contracts"
    contracts.mkdir(parents=True, exist_ok=True)
    if dossier:
        (contracts / "generation-dossier.json").write_text(json.dumps({
            "prompt": "Build an applicant tracking system for recruiters.",
            "plan": {"description": "ATS", "workflows": [{"id": "CreateCandidate"}]},
            "generatedAt": "2026-07-15T00:00:00Z",
        }), encoding="utf-8")
    if registry:
        (contracts / "resource-registry.json").write_text(json.dumps({
            "entities": {
                "Candidate": {
                    "name": "Candidate", "slug": "candidates", "table": "candidates",
                    "columns": [
                        {"name": "id", "type": "uuid", "fk": None, "notNull": True},
                        {"name": "fullName", "type": "varchar", "fk": None, "notNull": True},
                        {"name": "cvUrl", "type": "text", "fk": None, "notNull": False},
                    ],
                },
                "Assessment": {
                    "name": "Assessment", "slug": "assessments", "table": "assessments",
                    "columns": [
                        {"name": "id", "type": "uuid", "fk": None, "notNull": True},
                        {"name": "candidateId", "type": "uuid", "fk": "candidate", "notNull": False},
                        {"name": "scheduledAt", "type": "timestamp", "fk": None, "notNull": False},
                    ],
                },
            },
            "roles": ["admin", "recruiter"],
            "relationships": [
                {"from": "assessment", "to": "candidate", "fkColumn": "candidateId", "type": "many-to-one"},
            ],
            "interactions": [
                {"id": "schedule", "label": "Schedule Assessment", "sourcePage": "/assessments",
                 "workflowId": "assessmentschedulingworkflow", "targetEntityId": "assessment"},
            ],
        }), encoding="utf-8")
        # a couple of the other contracts so the summary has counts
        (contracts / "fk-semantics.json").write_text(json.dumps({"Assessment": {}, "Candidate": {}}), encoding="utf-8")
        (contracts / "action-contract.json").write_text(json.dumps(
            {"version": 1, "actions": [{"id": "a1"}, {"id": "a2"}]}), encoding="utf-8")
        (contracts / "binding-contract.json").write_text(json.dumps({"Candidate": {}, "Assessment": {}}), encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# emit_generation_dossier
# ---------------------------------------------------------------------------

def test_emit_generation_dossier_writes_file(tmp_path):
    plan = {"description": "ATS", "workflows": []}
    path = emit_generation_dossier(str(tmp_path), plan, prompt="Track applicants",
                                   generated_at="2026-07-15T12:00:00Z")
    on_disk = json.loads((tmp_path / "contracts" / "generation-dossier.json").read_text(encoding="utf-8"))
    assert on_disk["prompt"] == "Track applicants"
    assert on_disk["plan"] == plan
    assert on_disk["generatedAt"] == "2026-07-15T12:00:00Z"
    assert path.endswith("generation-dossier.json")


def test_emit_generation_dossier_no_timestamp_is_null(tmp_path):
    emit_generation_dossier(str(tmp_path), {"x": 1})
    on_disk = json.loads((tmp_path / "contracts" / "generation-dossier.json").read_text(encoding="utf-8"))
    assert on_disk["generatedAt"] is None
    assert on_disk["prompt"] is None


# ---------------------------------------------------------------------------
# assemble_recall — on disk only (no DB)
# ---------------------------------------------------------------------------

def test_assemble_from_disk_no_db(tmp_path):
    _write_contracts(tmp_path)
    ctx = assemble_recall(str(tmp_path))
    assert isinstance(ctx, RecallContext)
    assert ctx.prompt == "Build an applicant tracking system for recruiters."
    assert ctx.plan["description"] == "ATS"
    names = {e["name"] for e in ctx.entities}
    assert names == {"Candidate", "Assessment"}
    assert ctx.roles == ["admin", "recruiter"]
    assert len(ctx.relationships) == 1
    # contract summary counts
    assert ctx.contracts["fkSemantics"]["present"] is True
    assert ctx.contracts["actionContract"]["actions"] == 2
    assert ctx.contracts["bindingContract"]["entities"] == 2

    block = ctx.to_prompt_block()
    assert block
    assert "applicant tracking system" in block
    assert "Candidate" in block and "Assessment" in block


# ---------------------------------------------------------------------------
# assemble_recall — DB overlay wins over on-disk snapshot
# ---------------------------------------------------------------------------

class _StubConv:
    def __init__(self, role, content, metadata=None, created_at=None):
        self.role = role
        self.content = content
        self.metadata_ = metadata or {}
        self.created_at = created_at


class _StubQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *a, **k):
        return self

    def filter_by(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def all(self):
        return self._rows


class _StubSession:
    """Returns canned Conversation rows for any .query(); AgentJob queries get
    the same rows (their instruction attr is absent → skipped by the assembler)."""

    def __init__(self, rows):
        self._rows = rows

    def query(self, model):
        return _StubQuery(self._rows)


def test_db_plan_overlays_disk_snapshot(tmp_path):
    _write_contracts(tmp_path)
    live_plan = {"description": "LIVE ATS", "workflows": [{"id": "CreateCandidate"}]}
    rows = [
        _StubConv("assistant", "here is the plan", metadata={"plan": live_plan}, created_at=2),
        _StubConv("user", "Original: build me a recruiting tool", created_at=1),
    ]
    ctx = assemble_recall(str(tmp_path), project_id="p1", db_session=_StubSession(rows))
    # live plan wins over the on-disk snapshot
    assert ctx.plan["description"] == "LIVE ATS"
    # original prompt taken from the earliest user turn
    assert ctx.prompt == "Original: build me a recruiting tool"
    # registry-derived fields still present
    assert {e["name"] for e in ctx.entities} == {"Candidate", "Assessment"}


# ---------------------------------------------------------------------------
# assemble_recall — nothing on disk → empty but valid
# ---------------------------------------------------------------------------

def test_missing_everything_is_empty_but_valid(tmp_path):
    ctx = assemble_recall(str(tmp_path))
    assert isinstance(ctx, RecallContext)
    assert ctx.prompt is None
    assert ctx.plan is None
    assert ctx.entities == []
    assert ctx.roles == []
    block = ctx.to_prompt_block()
    assert isinstance(block, str)
    assert len(block) < 120
    assert "recall" in block.lower()
