"""The build repairs what it finds instead of ending the run.

A failure at `assemble` came after thirty minutes of generation and threw all
of it away: 0l133sp2 stopped on one form the dry run said would refuse its
first click, with fourteen pages written and compiled. What the build proves
at the end — every control runs, the data model stands up in a real database —
is owned by a step that ran long before, so the finding goes back to THAT
step's author, with the proof's own words, for up to `REPAIR_ROUNDS` rounds;
the affected files are projected again and the proof re-run. What is still
wrong after that is recorded as an issue of the application — the app ships,
it says what is wrong, and a person or Smith can act on it. Only an app that
does not compile or does not start is no app, and that stays a failure.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: Rounds of send-back-and-re-prove per kind of finding.
REPAIR_ROUNDS = 2


def repair(svc: Any, node: str, feedback_by_subject: dict[str, str], *, usage: Any = None) -> list[str]:
    """Ask `node`'s author again about each subject, with what the build
    proved; apply what it returns through the Blueprint's own checks. Returns
    the subjects whose repair was accepted."""
    from services.blueprint.agent_contract import AuthorRefusal, ContractViolation, apply_agent_result
    from services.blueprint.executors import make_executor, tiered_router
    from services.blueprint.orchestrator import DAG, TaskSpec
    from services.blueprint.service import BlueprintInvalid

    execute = make_executor(svc, tiered_router(), usage=usage)
    repaired: list[str] = []
    for subject, feedback in feedback_by_subject.items():
        spec = TaskSpec(task_id=f"TASK-{node}-build-repair-{subject or 'all'}", node=node,
                        agent=DAG[node].agent, subject=subject, attempt=2, feedback=feedback)
        try:
            result = execute(spec)
            application = apply_agent_result(svc, result, commit=True)
            if application.applied:
                repaired.append(subject)
        except (AuthorRefusal, ContractViolation, BlueprintInvalid) as exc:
            logger.warning("[build-repair] %s:%s refused: %s", node, subject, exc)
        except Exception as exc:  # noqa: BLE001 — a repair that breaks leaves the issue recorded
            logger.warning("[build-repair] %s:%s failed: %s", node, subject, exc)
    return repaired


# ---------------------------------------------------------------------------
# Controls that would refuse their first click
# ---------------------------------------------------------------------------

def dispatch_feedback(problems: list[dict]) -> dict[str, str]:
    """`{workflow id: what the dry run proved}` — the step author's brief."""
    by_wf: dict[str, list[str]] = {}
    for p in problems:
        by_wf.setdefault(str(p.get("workflow") or ""), []).append(
            f"- {p.get('route')}: {p.get('control')} \"{p.get('label')}\" sends {p.get('input')!r}; "
            f"step '{p.get('node')}' ({p.get('actionType')}): {p.get('problem')}")
    return {wf: ("The build ran every control through the engine with the input it sends, and "
                 "these would refuse their first click:\n" + "\n".join(lines)
                 + "\nFix the steps so the input these controls send is enough to run them — read a "
                   "record the control names by its id, and do not read a value no control sends.")
            for wf, lines in by_wf.items() if wf}


def dispatches_with_repair(svc: Any, app_root: str, issues: list[dict], *, usage: Any = None) -> int:
    """The first-click dry run, with repair rounds. Returns controls checked."""
    from services.blueprint.assembly import BuildFailed, DispatchesRefused, verify_dispatches
    from services.blueprint.orchestrator import _project_integration
    from services.blueprint.projection import project_dispatches

    for round_ in range(REPAIR_ROUNDS + 1):
        try:
            return verify_dispatches(app_root)
        except DispatchesRefused as exc:
            if round_ == REPAIR_ROUNDS or not repair(svc, "workflow_steps", dispatch_feedback(exc.problems),
                                                     usage=usage):
                issues.extend({"kind": "control", **p} for p in exc.problems)
                logger.warning("[assemble] %d control(s) would refuse their first click; recorded",
                               len(exc.problems))
                return 0
            _project_integration(svc, app_root)
            project_dispatches(svc.doc, app_root)
        except BuildFailed as exc:
            # The dry run itself could not start — a tool, not a control. The
            # app compiled and will be started; the look is recorded as not
            # taken rather than ending the run.
            issues.append({"kind": "check", "check": "dispatch dry run", "detail": str(exc)[:600]})
            logger.warning("[assemble] the dispatch dry run could not run: %s", str(exc)[:300])
            return 0
    return 0


# ---------------------------------------------------------------------------
# The data model in a real database
# ---------------------------------------------------------------------------

def database_with_repair(svc: Any, app_root: str, issues: list[dict], *, usage: Any = None) -> dict:
    """Tables and demo rows in a throwaway database, with repair rounds.
    Returns the last gate result; ``rebuilt`` when a repair changed the
    schema and the app was compiled again."""
    from services.blueprint import data_gate
    from services.blueprint.assembly import verify_build
    from services.blueprint.orchestrator import _project_data_layer
    from services.blueprint.projection import project_seed

    rebuilt = False
    result: dict = {}
    for round_ in range(REPAIR_ROUNDS + 1):
        result = data_gate.run(app_root, seed=True)
        if result.get("skipped") or result.get("ok"):
            break
        found = data_gate.findings(svc.doc, result, app_root)
        feedback: dict[str, str] = {}
        for f in found:
            if f.artifact_id:
                feedback.setdefault(f.artifact_id, "The build created this application's tables and demo "
                                    "rows in a real database, and it refused:")
                feedback[f.artifact_id] += "\n- " + f.detail
        if round_ == REPAIR_ROUNDS or not feedback or not repair(svc, "entity_fields", feedback, usage=usage):
            issues.extend({"kind": "database", "entity": f.artifact_id, "detail": f.detail} for f in found)
            logger.warning("[assemble] the database refused %d thing(s); recorded", len(found))
            break
        _project_data_layer(svc, app_root)
        project_seed(svc.doc, app_root)
        verify_build(app_root, install=False, dispatches=False)
        rebuilt = True
    return {**result, "rebuilt": rebuilt}


__all__ = ["REPAIR_ROUNDS", "database_with_repair", "dispatch_feedback", "dispatches_with_repair", "repair"]
