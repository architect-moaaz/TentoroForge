"""SmithSession — the architect's per-turn service.

Spec §10 (architecture), §11 (verification), §5 (lifecycle), §9
(change_log update).

The session is the class the (future) POST /chat/message handler
instantiates. Every branch uses injectable seams so tests never
touch the model, git, or disk except where they explicitly want to.

The tests cover the shapes each flow returns, that the change_log
gets written correctly, that verification is executed against
ground truth (never against Smith's self-report), and that failure
semantics match the spec (report + options, no silent rollback).
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from services.smith_blueprint import Blueprint
from services.smith_session import (
    SmithSession,
    TurnResult,
    IterationMove,
)
from services.narrator_artifacts import (
    DiscoveryArtifact,
    PlannerArtifact,
    GeneratorArtifact,
)


# --------------------------------------------------------------------------- #
# Fixtures / seams
# --------------------------------------------------------------------------- #

def _init_repo(tmp_path: Path) -> Path:
    subprocess.check_call(["git", "init", "-q", str(tmp_path)])
    subprocess.check_call(["git", "-C", str(tmp_path),
                           "config", "user.email", "t@t.t"])
    subprocess.check_call(["git", "-C", str(tmp_path),
                           "config", "user.name", "T"])
    (tmp_path / "seed.txt").write_text("seed")
    subprocess.check_call(["git", "-C", str(tmp_path), "add", "seed.txt"])
    subprocess.check_call(["git", "-C", str(tmp_path),
                           "commit", "-qm", "seed"])
    return tmp_path


@dataclass
class _StubDiscovery:
    dossier: dict

    def __call__(self, message: str, blueprint_ctx: str) -> DiscoveryArtifact:
        return DiscoveryArtifact.from_dict(self.dossier)


@dataclass
class _StubPlanner:
    plan: dict

    def __call__(self, discovery: DiscoveryArtifact) -> PlannerArtifact:
        return PlannerArtifact.from_dict(self.plan)


@dataclass
class _StubGenerator:
    payload: dict

    def __call__(self, plan: PlannerArtifact, output_dir: str) -> GeneratorArtifact:
        return GeneratorArtifact.from_dict(self.payload)


def _no_op_guards(_out: str) -> list[dict[str, Any]]:
    return []


# --------------------------------------------------------------------------- #
# Bootstrap flow (§5.1, S6)
# --------------------------------------------------------------------------- #

def test_bootstrap_writes_domain_entities_workflows_pages_into_blueprint(tmp_path):
    _init_repo(tmp_path)
    session = SmithSession(
        project_id="p1", output_dir=str(tmp_path),
        discovery_fn=_StubDiscovery({
            "domain_name": "ATS", "actors": ["recruiter"],
            "verbs": ["apply"], "distinctive_shape": "kanban",
            "proposed_entities": [{"name": "Candidate", "why": ""}],
            "open_questions": [],
        }),
        planner_fn=_StubPlanner({
            "entities": [{"name": "Candidate", "table": "candidates",
                          "purpose": "applicant", "key_fields": ["email"],
                          "why_shaped_this_way": "MVP"}],
            "workflows": [{"name": "CreateCandidate", "purpose": "capture",
                           "trigger": "form", "why": "manual"}],
            "pages": [{"route": "/candidates", "schema_path": "src/schemas/candidates/index.json",
                       "role": "list"}],
        }),
        generator_fn=_StubGenerator({
            "generated_files": ["src/schemas/candidates/index.json"],
            "warnings": [], "notes": [],
        }),
        guards_fn=_no_op_guards,
    )

    result = session.run_bootstrap(user_message="build an ATS")

    assert result.status == "resolved"
    # Blueprint now reflects everything.
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    assert bp.domain and bp.domain["name"] == "ATS"
    assert [e["name"] for e in bp.entities] == ["Candidate"]
    assert [w["name"] for w in bp.workflows] == ["CreateCandidate"]
    assert [p["route"] for p in bp.pages] == ["/candidates"]
    # change_log recorded the bootstrap under source=smith.
    assert bp.change_log
    assert bp.change_log[-1]["source"] == "smith"
    assert "bootstrap" in bp.change_log[-1]["smith_move"].lower()


def test_bootstrap_answer_uses_generator_and_discovery_narrator_summaries(tmp_path):
    _init_repo(tmp_path)
    session = SmithSession(
        project_id="p1", output_dir=str(tmp_path),
        discovery_fn=_StubDiscovery({
            "domain_name": "ATS", "actors": ["recruiter"],
            "verbs": ["apply"], "distinctive_shape": "kanban pipeline",
            "proposed_entities": [], "open_questions": [],
        }),
        planner_fn=_StubPlanner({
            "entities": [{"name": "Candidate", "table": "c", "purpose": "",
                          "key_fields": [], "why_shaped_this_way": ""}],
            "workflows": [], "pages": [],
        }),
        generator_fn=_StubGenerator({
            "generated_files": ["src/schemas/candidates/index.json"],
            "warnings": [], "notes": [],
        }),
        guards_fn=_no_op_guards,
    )
    result = session.run_bootstrap(user_message="build ATS")
    # The final answer references both the domain (from discovery) and
    # the fact that files were generated (from generator).
    assert "ATS" in result.answer
    assert "1 file" in result.answer or "1 file(s)" in result.answer


# --------------------------------------------------------------------------- #
# Iteration flow (§5.2, S7) — ground truth is the arbiter
# --------------------------------------------------------------------------- #

def test_iteration_marks_resolved_when_diff_touches_expected_element(tmp_path):
    """The failure mode from the live session: guards green +
    architect self-review pass = resolved. Here we simulate a Smith
    move that changed the target element by writing the file."""
    _init_repo(tmp_path)
    # Baseline: an already-generated schema in the repo.
    schema_dir = tmp_path / "src" / "schemas" / "candidates"
    schema_dir.mkdir(parents=True)
    (schema_dir / "new.json").write_text(
        '{"root":{"children":[{"type":"Select",'
        '"props":{"name":"cv","label":"Upload CV"}}]}}'
    )
    subprocess.check_call(["git", "-C", str(tmp_path), "add", "."])
    subprocess.check_call(["git", "-C", str(tmp_path),
                           "commit", "-qm", "baseline schema"])

    # Seed the blueprint with a domain so we're past bootstrap.
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    bp.set_domain(name="ATS", primary_actors=[], core_verbs=[],
                  distinctive_shape="", why="")
    bp.save()

    def _move(understanding, output_dir):
        """Real edit: replace Select with FileUpload."""
        p = Path(output_dir) / "src" / "schemas" / "candidates" / "new.json"
        p.write_text(
            '{"root":{"children":[{"type":"FileUpload",'
            '"props":{"name":"cv","label":"Upload CV"}}]}}'
        )
        return IterationMove(
            move_name="edit_page(candidates/new.json)",
            touched_paths=["src/schemas/candidates/new.json"],
        )

    def _understand(user_message, ctx):
        return {
            "screen": "Add Candidate",
            "element_label": "Upload CV",
            "current_behavior": "Select",
            "desired_behavior": "FileUpload",
            "target_file": "src/schemas/candidates/new.json",
        }

    session = SmithSession(
        project_id="p1", output_dir=str(tmp_path),
        guards_fn=_no_op_guards,
        understand_ask_fn=_understand,
        iteration_move_fn=_move,
    )
    result = session.run_iteration(
        user_message="In Add Candidate, upload CV is the dropdown"
    )

    assert result.status == "resolved"
    # change_log recorded the move with verified_by containing
    # the ground-truth checks that ran.
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    last = bp.change_log[-1]
    assert last["source"] == "smith"
    assert "git diff" in " ".join(last["verified_by"]).lower()


def test_iteration_refuses_resolved_when_diff_does_not_mention_target(tmp_path):
    """The bug we hit today: Smith changed unrelated files but the
    orchestrator marked resolved. Now the ground-truth check on the
    actual line diff must catch it."""
    _init_repo(tmp_path)
    schema_dir = tmp_path / "src" / "schemas" / "candidates"
    schema_dir.mkdir(parents=True)
    (schema_dir / "new.json").write_text('{"root":{"children":[]}}')
    subprocess.check_call(["git", "-C", str(tmp_path), "add", "."])
    subprocess.check_call(["git", "-C", str(tmp_path),
                           "commit", "-qm", "baseline"])

    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    bp.set_domain(name="ATS", primary_actors=[], core_verbs=[],
                  distinctive_shape="", why="")
    bp.save()

    def _move(understanding, output_dir):
        """Smith edits an UNRELATED file — the wrong-file scenario."""
        p = Path(output_dir) / "some_other.txt"
        p.write_text("unrelated change")
        return IterationMove(
            move_name="edit_file(some_other.txt)",
            touched_paths=["some_other.txt"],
        )

    def _understand(user_message, ctx):
        return {
            "screen": "Add Candidate",
            "element_label": "Upload CV",
            "current_behavior": "Select",
            "desired_behavior": "FileUpload",
            "target_file": "src/schemas/candidates/new.json",
        }

    session = SmithSession(
        project_id="p1", output_dir=str(tmp_path),
        guards_fn=_no_op_guards,
        understand_ask_fn=_understand,
        iteration_move_fn=_move,
    )
    result = session.run_iteration(user_message="fix the CV field")

    assert result.status == "needs_user"
    # The failure message must be architect-voice, naming the specific
    # mismatch (not a canned template).
    ans = result.answer.lower()
    assert (
        "upload cv" in ans
        or "target" in ans
        or "wrong file" in ans
        or "candidates/new.json" in ans
    )
    assert result.options  # the "retry / roll back / abandon / leave" choices


def test_iteration_refuses_when_guard_delta_is_red(tmp_path):
    """Even if the diff touched the right file, a NEW guard failure
    that Smith's edit introduced blocks the resolved verdict."""
    _init_repo(tmp_path)
    schema_dir = tmp_path / "src" / "schemas" / "candidates"
    schema_dir.mkdir(parents=True)
    (schema_dir / "new.json").write_text(
        '{"root":{"children":[{"type":"Select","props":{"label":"Upload CV"}}]}}'
    )
    subprocess.check_call(["git", "-C", str(tmp_path), "add", "."])
    subprocess.check_call(["git", "-C", str(tmp_path), "commit", "-qm", "baseline"])
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    bp.set_domain(name="ATS", primary_actors=[], core_verbs=[],
                  distinctive_shape="", why="")
    bp.save()

    def _move(u, output_dir):
        p = Path(output_dir) / "src" / "schemas" / "candidates" / "new.json"
        p.write_text(
            '{"root":{"children":[{"type":"FileUpload","props":{"label":"Upload CV"}}]}}'
        )
        return IterationMove(
            move_name="edit_page", touched_paths=["src/schemas/candidates/new.json"],
        )

    calls = {"n": 0}
    def _guards(_out):
        calls["n"] += 1
        if calls["n"] == 1:
            return []  # baseline: clean
        return [{"guard": "read_binding_guard",
                 "message": "1 unresolved binding after Smith edit"}]

    session = SmithSession(
        project_id="p1", output_dir=str(tmp_path),
        guards_fn=_guards,
        understand_ask_fn=lambda m, ctx: {
            "screen": "x", "element_label": "Upload CV",
            "current_behavior": "y", "desired_behavior": "z",
            "target_file": "src/schemas/candidates/new.json",
        },
        iteration_move_fn=_move,
    )
    result = session.run_iteration(user_message="fix CV")
    assert result.status == "needs_user"
    # The failure message references the specific guard that broke.
    assert "read_binding_guard" in result.answer or "unresolved binding" in result.answer


def test_iteration_ask_user_when_understand_returns_low_confidence(tmp_path):
    _init_repo(tmp_path)
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    bp.set_domain(name="ATS", primary_actors=[], core_verbs=[],
                  distinctive_shape="", why="")
    bp.save()

    def _understand(m, ctx):
        return {
            "screen": "", "element_label": "", "current_behavior": "",
            "desired_behavior": "", "target_file": "",
            "clarification_needed": "which page are you on?",
        }

    session = SmithSession(
        project_id="p1", output_dir=str(tmp_path),
        guards_fn=_no_op_guards,
        understand_ask_fn=_understand,
        iteration_move_fn=lambda *a, **kw: None,  # never called
    )
    result = session.run_iteration(user_message="it's broken")
    assert result.status == "asked"
    assert "which page" in result.answer.lower()


# --------------------------------------------------------------------------- #
# change_log semantics (§9)
# --------------------------------------------------------------------------- #

def test_change_log_entry_records_ask_move_diff_and_verification(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.json").write_text('{"before": true}')
    subprocess.check_call(["git", "-C", str(tmp_path), "add", "."])
    subprocess.check_call(["git", "-C", str(tmp_path), "commit", "-qm", "b"])
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    bp.set_domain(name="ATS", primary_actors=[], core_verbs=[],
                  distinctive_shape="", why="")
    bp.save()

    def _move(u, output_dir):
        (Path(output_dir) / "a.json").write_text('{"before":false, "label":"MARK"}')
        return IterationMove(move_name="edit_file(a.json)", touched_paths=["a.json"])

    session = SmithSession(
        project_id="p1", output_dir=str(tmp_path),
        guards_fn=_no_op_guards,
        understand_ask_fn=lambda m, ctx: {
            "screen": "x", "element_label": "MARK",
            "current_behavior": "y", "desired_behavior": "z",
            "target_file": "a.json",
        },
        iteration_move_fn=_move,
    )
    result = session.run_iteration(user_message="do the thing")
    assert result.status == "resolved"

    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    entry = bp.change_log[-1]
    assert entry["user_ask"] == "do the thing"
    assert entry["smith_move"] == "edit_file(a.json)"
    assert "a.json" in entry["diff_summary"]
    assert any("git" in v.lower() for v in entry["verified_by"])
