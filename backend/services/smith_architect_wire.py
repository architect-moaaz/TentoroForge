"""Production wiring for SmithSession — Migration Step 3+4 (iteration path).

Bridges the running backend to the new Smith-as-architect stack.
`_handle_smith_turn` in ``routers/generate.py`` invokes
``run_iteration_via_architect``, once behind the ``FORGE_SMITH_ARCHITECT``
flag. This module supplies the real seams the SmithSession needs at
runtime:

  * :func:`_understand_ask` — one Anthropic call that reads the user's
    ask + a scoped blueprint slice and returns the structured
    ``{screen, element_label, current_behavior, desired_behavior,
    target_file}`` dict the session's iteration flow expects.

  * :func:`_iteration_move` — dispatches through
    ``services.smith_move_dispatcher.dispatch_move`` with a real
    seams table binding into ``fix_applier`` and the existing
    ``edit_workflow_seam`` / seam wrappers.

  * :func:`_guards` — wraps ``post_generate_fixes.
    apply_post_generate_fixes_with_result`` and hands the failure
    list to the session's baseline-diff.

Bootstrap is deferred — the discovery / planner / generator adapters
land in a follow-up (they involve stream accumulation). This slice
supports iteration-only, which is the class of ask the running
tactical stack fails on today (the CV-field debugging session).
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass as _dc_dataclass
from pathlib import Path
from typing import Any

from services.blueprint_backfill import backfill_project_blueprint
from services.ground_truth import git_status_modified
from services.smith_agent_adapters import (
    orchestrate_discovery,
    orchestrate_planner,
)
from services.smith_blueprint import Blueprint
from services.smith_blueprint_context import (
    blueprint_to_context,
    pick_relevant_slice,
)
from services.smith_move_dispatcher import dispatch_move
from services.smith_session import IterationMove, SmithSession, TurnResult


logger = logging.getLogger(__name__)


_UNDERSTAND_MODEL = os.environ.get(
    "FORGE_SMITH_UNDERSTAND_MODEL", "claude-opus-4-7"
)
_UNDERSTAND_MAX_TOKENS = 1024


# --------------------------------------------------------------------------- #
# Public entry — the function _handle_smith_turn calls
# --------------------------------------------------------------------------- #

def run_iteration_via_architect(
    message: str, output_dir: str, project_id: str,
    memory_block: str = "",
) -> TurnResult:
    """Run one iteration turn as the SMITH ARCHITECT — a ReAct agent
    with real tools (``list_pages``, ``read_page``, ``list_components``,
    ``edit_page``, ``add_page``, ``add_workflow``, ``add_entity``,
    ``run_guards``, ``read_file``, ``edit_file``, ``impact_analysis``,
    ``verify_promise``, ``think``).

    Delegates to :func:`agents.smith_agent.run_smith_agent` — the real
    tool-use loop that ships in the codebase. The architect wire's job
    is to (1) ensure the Blueprint exists (backfilling on first sight),
    (2) augment the recall block with Blueprint + component-catalog
    context so Smith speaks as the architect who authored the app,
    (3) adapt the agent's ``{diagnosis, answer, question, handoff,
    trace, edited_paths}`` result into a ``TurnResult``.

    The prior form-filler shape (one LLM call → structured target →
    dispatch to a seam) was the regression; this restores the ReAct
    loop the S1-S5 tasks originally shipped."""
    # Blueprint precondition: backfill from the registry if missing.
    try:
        backfill_project_blueprint(project_id=project_id, output_dir=output_dir)
    except Exception:  # noqa: BLE001
        logger.exception("architect: blueprint backfill failed — proceeding")

    # Bootstrap detection: only when the output dir itself doesn't
    # exist at all — that's a truly fresh project. If the dir exists
    # (even with no src/ yet — legacy projects, partial builds) the
    # ReAct agent gets to decide: it can inspect, report emptiness,
    # or start planning. Overly-narrow gating here is what turned the
    # architect stack into a form-filler.
    from pathlib import Path as _P
    if not _P(output_dir).exists():
        return TurnResult(
            status="not_enabled",
            answer=(
                "Project directory doesn't exist yet — bootstrap needed."
            ),
        )

    bp = Blueprint.load(project_id=project_id, output_dir=output_dir)

    # Build the recall block (context engine — component contracts +
    # entity contracts + resource registry). ``assemble_recall`` reads
    # the project files directly and returns a prompt-ready block.
    recall_block = ""
    try:
        from services.app_recall import assemble_recall
        recall = assemble_recall(output_dir)
        recall_block = recall.to_prompt_block()
    except Exception:  # noqa: BLE001
        logger.exception("architect: assemble_recall failed — continuing without")

    # Augment with Blueprint slice + Smith-authored-this-app persona so
    # the agent behaves as the architect the vision describes.
    arch_block = _build_architect_context_block(bp)
    if arch_block:
        recall_block = f"{arch_block}\n\n{recall_block}" if recall_block else arch_block

    # Delegate to the real ReAct agent. The caller (``_handle_smith_turn``)
    # builds the DB-persisted smith_memory block and passes it in — the
    # architect needs it so multi-turn conversations don't lose the prior
    # "here's the scope, does that look right?" proposal on the user's
    # "please go ahead" reply.
    try:
        from agents.smith_agent import run_smith_agent
        result = run_smith_agent(
            user_message=message,
            output_dir=output_dir,
            recall_block=recall_block,
            memory_block=memory_block or "",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("architect: ReAct loop failed")
        return TurnResult(
            status="not_enabled",
            answer=f"Architect agent crashed ({type(exc).__name__}: {exc}).",
        )

    return _smith_agent_result_to_turn_result(result)


def _build_architect_context_block(bp: Blueprint) -> str:
    """Compose the architect-persona + Blueprint-slice context that
    goes at the top of the recall block. Smith reads this and knows
    (a) the domain he built, (b) which entities/pages/workflows he
    authored, (c) that he can and SHOULD use his tools before
    answering — no more 'matches' guesses."""
    parts: list[str] = [
        "## You are the Smith Architect",
        (
            "You authored this application — the entities, the pages, the "
            "workflows. When the user names a screen, USE `list_pages_tool` "
            "to find it and `read_page` to see what's on it BEFORE you "
            "answer. Don't guess. Don't say 'matches' without reading. "
            "When they ask for a new capability, propose the full slice "
            "(entity + page + workflow wiring) and ask ONE approval question."
        ),
    ]
    try:
        from services.smith_blueprint_context import (
            blueprint_to_context, ContextBudget,
        )
        bp_slice = blueprint_to_context(bp, budget=ContextBudget(max_chars=1200))
        if bp_slice.strip():
            parts.extend(["", "## Blueprint (your memory of what you built)", bp_slice])
    except Exception:  # noqa: BLE001
        logger.exception("architect: blueprint_to_context failed")

    try:
        from services.component_catalog import format_component_context
        cat = format_component_context(budget_chars=1200)
        if cat.strip():
            parts.extend(["", cat])
    except Exception:  # noqa: BLE001
        logger.exception("architect: format_component_context failed")

    return "\n".join(parts)


def _smith_agent_result_to_turn_result(result: dict) -> TurnResult:
    """Adapt ``agents.smith_agent.run_smith_agent``'s
    ``{diagnosis, answer, question, handoff, trace, edited_paths}``
    into the ``TurnResult`` shape the caller expects."""
    if not isinstance(result, dict):
        return TurnResult(
            status="not_enabled",
            answer="Architect returned an unrecognized result shape.",
        )
    touched = [str(p) for p in (result.get("edited_paths") or [])]
    trace = list(result.get("trace") or [])
    if result.get("answer"):
        return TurnResult(
            status="resolved",
            answer=str(result["answer"]),
            touched_paths=touched,
            trace=trace,
        )
    if result.get("question"):
        return TurnResult(
            status="asked", answer=str(result["question"]), trace=trace,
        )
    if result.get("handoff"):
        h = result["handoff"] or {}
        return TurnResult(
            status="handoff",
            answer=str(h.get("message") or "Handing off."),
            trace=trace,
        )
    if result.get("diagnosis"):
        return TurnResult(
            status="resolved",
            answer="I have a diagnosis prepared.",
            touched_paths=touched,
            trace=trace,
        )
    return TurnResult(
        status="no_op", answer="No change needed.",
        touched_paths=touched, trace=trace,
    )


# --------------------------------------------------------------------------- #
# Guards seam — wraps the existing post_generate_fixes suite
# --------------------------------------------------------------------------- #

def _guards(output_dir: str) -> list[dict[str, Any]]:
    """Return the current guard-suite failures as a list of
    ``{guard, message}`` dicts the SmithSession's baseline-diff
    can compare against.

    The suite writes files (seed synthesizer, action-contract fixer,
    etc.) as a side effect of running — that's fine, it's idempotent
    and matches what the tactical stack does today."""
    try:
        from services.post_generate_fixes import (
            apply_post_generate_fixes_with_result,
        )
        result = apply_post_generate_fixes_with_result(output_dir)
        return [
            {"guard": f.guard, "message": f.message}
            for f in (result.failures or [])
        ]
    except Exception:  # noqa: BLE001
        logger.exception("architect: guard suite crashed")
        return []


# --------------------------------------------------------------------------- #
# understand_ask seam — LLM call, returns the structured dict
# --------------------------------------------------------------------------- #

_UNDERSTAND_SYSTEM = (
    "You are the SMITH ARCHITECT — a Senior Software Engineer / DevOps / "
    "Master Technical Architect who authored the generated app you're "
    "reasoning about. The user has sent one ask about the running app. "
    "Your ONLY job right now is to EXTRACT that ask into a structured "
    "target so the orchestrator can verify your edit against the user's "
    "intent.\n\n"
    "Return JSON matching this shape EXACTLY (no code fences, no prose):\n"
    '{\n'
    '  "screen": "<the visible screen name from the ask, e.g. \'Add Candidate\'>",\n'
    '  "element_label": "<the visible element the user mentioned VERBATIM, '
    'e.g. \'Upload CV\'; MUST appear in the app for the edit to be verifiable>",\n'
    '  "current_behavior": "<what the element does today>",\n'
    '  "desired_behavior": "<what the user wants it to do>",\n'
    '  "target_file": "<repo-relative path of the file you\'ll edit; '
    'usually src/schemas/<slug>/<name>.json for pages, workflows/<Name>.json '
    'for workflows; must match a file in the blueprint context>",\n'
    '  "confidence": 0.0-1.0,\n'
    '  "clarification_needed": null OR "<a specific question to ask the '
    'user if you cannot fill the fields above confidently>"\n'
    '}\n\n'
    "If the ask is ambiguous, DO NOT guess — set clarification_needed to "
    "a targeted question and leave the other fields empty. Never invent "
    "target_file paths that aren't in the blueprint."
)


def _understand_ask(user_message: str, blueprint_ctx: str) -> dict[str, Any]:
    """Call Anthropic to extract the structured target from the ask.

    Falls back to a low-confidence ask_user payload on any error so
    the session escalates instead of guessing."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "clarification_needed": (
                "The ANTHROPIC_API_KEY isn't set on the backend — I can't "
                "understand asks in architect mode without it. Please have "
                "the operator set it, then retry."
            ),
        }

    # Component catalog — Smith looks up what exists rather than
    # guessing. Only components in this list are authorable; a
    # target_file that would use "MyCustomChart" (not in the catalog)
    # means the ask isn't achievable in-place.
    try:
        from services.component_catalog import format_component_context
        catalog_ctx = format_component_context(budget_chars=2000)
    except Exception:  # noqa: BLE001
        catalog_ctx = ""

    parts = [
        "## Blueprint context (what YOU already built)",
        blueprint_ctx,
        "",
    ]
    if catalog_ctx:
        parts.extend([catalog_ctx, ""])
    parts.extend([
        "## User ask",
        user_message,
        "",
        "Return the JSON now.",
    ])
    prompt = "\n".join(parts)
    try:
        from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim
        client = llm_client.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=_UNDERSTAND_MODEL,
            max_tokens=_UNDERSTAND_MAX_TOKENS,
            system=_UNDERSTAND_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            b.text for b in resp.content if hasattr(b, "text")
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("architect: understand_ask LLM call failed")
        return {
            "clarification_needed": (
                f"I hit an error reading your ask ({type(exc).__name__}). "
                "Please try rephrasing, or check the backend logs."
            ),
        }

    parsed = _extract_json_object(text)
    if parsed is None:
        logger.warning("architect: understand_ask returned non-JSON: %r", text[:300])
        return {
            "clarification_needed": (
                "I couldn't parse the ask into a target. Could you name "
                "the screen and the exact field label you mean?"
            ),
        }
    return parsed


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Grab the first `{...}` JSON object from a string. Handles the
    model occasionally wrapping in code fences even when told not to."""
    if not isinstance(text, str) or not text.strip():
        return None
    # Strip a code fence if present.
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    # Find the outermost object.
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- #
# iteration_move seam — routes to the right existing seam
# --------------------------------------------------------------------------- #

def _make_iteration_move(project_id: str):
    """Build an iteration_move_fn closed over ``project_id``.

    The replan seam needs to know which project to update; the other
    seams work purely from ``output_dir``. Binding ``project_id`` here
    keeps SmithSession's ``iteration_move_fn(u, output_dir)`` signature
    untouched."""
    def _iteration_move(understanding: dict, output_dir: str) -> IterationMove | None:
        seams = {
            "edit_page":     _seam_edit_page,
            "add_page":      _seam_add_page,
            "edit_workflow": _seam_edit_workflow,
            "add_workflow":  _seam_add_workflow,
            "add_entity":    _seam_add_entity,
            "edit_file":     _seam_edit_file,
            "replan":        lambda u, o: _seam_replan(u, o, project_id=project_id),
        }
        return dispatch_move(understanding, output_dir, seams)
    return _iteration_move


# --------------------------------------------------------------------------- #
# Seam callables — each wraps an existing tool
# --------------------------------------------------------------------------- #

def _seam_edit_page(u: dict, output_dir: str) -> IterationMove | None:
    """The most common seam by far: change a field's type/props on a
    page schema. Uses the same _apply_page_schema_patch as
    propose_fix(seam=page_schema_patch), but with an empty
    explanation so the coherence gate short-circuits (no prose to
    drift from). The patch itself is authored by asking the model
    for the RFC-6902 ops given the understanding."""
    from services.fix_applier import _apply_page_schema_patch

    target = str(u.get("target_file") or "").strip()
    if not target:
        return None
    patch = _author_page_patch(u, output_dir)
    if not patch:
        return None
    diagnosis = {
        "artifact": {"kind": "page_schema", "path": target},
        "explanation": "",  # empty ⇒ coherence gate no-ops
        "proposedFix": {"seam": "page_schema_patch", "patch": patch},
    }
    result = _apply_page_schema_patch(output_dir, diagnosis, git=False)
    if not result.get("applied"):
        logger.info("architect: edit_page seam failed apply: %s",
                    result.get("reason"))
        return None
    return IterationMove(
        move_name=f"edit_page({target})",
        touched_paths=[target],
    )


def _seam_edit_workflow(u: dict, output_dir: str) -> IterationMove | None:
    from services.edit_workflow_seam import edit_workflow
    target = str(u.get("target_file") or "").strip()
    if not target:
        return None
    wid = Path(target).stem
    changes = u.get("workflow_changes") or {}
    if not changes:
        return None
    result = edit_workflow(output_dir, wid, changes)
    if not result.success:
        return None
    return IterationMove(
        move_name=f"edit_workflow({wid})",
        touched_paths=[target],
    )


def _seam_add_page(u: dict, output_dir: str) -> IterationMove | None:
    from services.fix_applier import _apply_add_page
    diagnosis = {
        "artifact": {"kind": "page", "path": u.get("target_file") or ""},
        "explanation": "",
        "proposedFix": {"seam": "add_page", "patch": {
            "archetype": u.get("archetype") or "list",
            "entity":    u.get("entity")    or "",
            "route":     u.get("route")     or u.get("target_file") or "",
            "title":     u.get("title"),
        }},
    }
    r = _apply_add_page(output_dir, diagnosis, git=False)
    if not r.get("applied"):
        return None
    paths = [c["path"] for c in r.get("changes") or [] if c.get("path")]
    return IterationMove(move_name=f"add_page({u.get('route') or '?'})",
                         touched_paths=paths)


def _seam_add_workflow(u: dict, output_dir: str) -> IterationMove | None:
    from services.fix_applier import _apply_add_workflow
    diagnosis = {
        "artifact": {"kind": "workflow", "path": u.get("target_file") or ""},
        "explanation": "",
        "proposedFix": {"seam": "add_workflow", "patch": {
            "op":     u.get("op") or "create",
            "entity": u.get("entity") or "",
            "name":   u.get("name"),
        }},
    }
    r = _apply_add_workflow(output_dir, diagnosis, git=False)
    if not r.get("applied"):
        return None
    paths = [c["path"] for c in r.get("changes") or [] if c.get("path")]
    return IterationMove(move_name=f"add_workflow({u.get('name') or '?'})",
                         touched_paths=paths)


def _seam_add_entity(u: dict, output_dir: str) -> IterationMove | None:
    from services.fix_applier import _apply_add_entity
    diagnosis = {
        "artifact": {"kind": "entity", "path": u.get("target_file") or ""},
        "explanation": "",
        "proposedFix": {"seam": "add_entity", "patch": {
            "name":   u.get("name")   or "",
            "fields": u.get("fields") or [],
            "table":  u.get("table"),
        }},
    }
    r = _apply_add_entity(output_dir, diagnosis, git=False)
    if not r.get("applied"):
        return None
    paths = [c["path"] for c in r.get("changes") or [] if c.get("path")]
    return IterationMove(move_name=f"add_entity({u.get('name') or '?'})",
                         touched_paths=paths)


def _seam_edit_file(u: dict, output_dir: str) -> IterationMove | None:
    """Last-resort raw file edit. Requires ``old_string`` + ``new_string``
    on the understanding (the LLM must supply them). If they're missing
    we punt so the session bubbles up to ask_user."""
    target = str(u.get("target_file") or "").strip()
    old_string = u.get("old_string")
    new_string = u.get("new_string")
    if not target or not isinstance(old_string, str) or not isinstance(new_string, str):
        return None
    f = Path(output_dir) / target
    if not f.exists():
        return None
    try:
        content = f.read_text(encoding="utf-8")
        if old_string not in content:
            return None
        new_content = content.replace(old_string, new_string, 1)
        f.write_text(new_content, encoding="utf-8")
    except OSError:
        return None
    return IterationMove(move_name=f"edit_file({target})",
                         touched_paths=[target])


# --------------------------------------------------------------------------- #
# Replan seam — Phase D1
#
# For a "whole-capability" ask (add auth, add payments, add RBAC) the
# architect can't heal it with a field-level edit. He runs the planner
# with the existing blueprint as prior_plan + the new requirement,
# then updates the blueprint via Phase A's record_plan. Regeneration
# is a separate step the user initiates — this seam only produces the
# plan diff.
# --------------------------------------------------------------------------- #

def _seam_replan(
    u: dict, output_dir: str, *, project_id: str | None = None,
) -> IterationMove | None:
    """Run the planner against the existing blueprint + new ask.

    Returns None when the planner errors, produces nothing, or
    ``project_id`` is missing (in which case dispatch_move never
    should have routed here — belt and suspenders)."""
    pid = project_id or str(u.get("project_id") or "").strip() or None
    if not pid:
        return None

    ask = str(
        u.get("desired_behavior") or u.get("element_label")
        or u.get("screen") or ""
    ).strip()
    if not ask:
        return None

    try:
        bp = Blueprint.load(project_id=pid, output_dir=output_dir)
    except Exception:  # noqa: BLE001
        logger.exception("architect: replan couldn't load blueprint")
        return None
    prior_plan = _blueprint_to_prior_plan(bp)

    try:
        planner_art = _run_planner_from_sync(
            description=ask, prior_plan=prior_plan,
        )
    except Exception:  # noqa: BLE001
        logger.exception("architect: replan planner call failed")
        return None

    if not (planner_art.entities or planner_art.workflows or planner_art.pages):
        return None

    # Phase A hook: merge into blueprint (idempotent by name).
    from services.blueprint_pipeline_hooks import record_plan
    plan_dict = _planner_artifact_to_dict(planner_art)
    record_plan(output_dir=output_dir, project_id=pid, plan=plan_dict)

    parts: list[str] = []
    if planner_art.entities:
        preview = ", ".join(e.name for e in planner_art.entities[:3])
        parts.append(f"{len(planner_art.entities)} entities [{preview}]")
    if planner_art.workflows:
        preview = ", ".join(w.name for w in planner_art.workflows[:3])
        parts.append(f"{len(planner_art.workflows)} workflows [{preview}]")
    if planner_art.pages:
        parts.append(f"{len(planner_art.pages)} pages")
    summary = "; ".join(parts) if parts else "plan updated"

    return IterationMove(
        move_name=f"replan({summary})",
        touched_paths=[".forge/blueprint.json"],
    )


def _blueprint_to_prior_plan(bp) -> dict:
    """Reconstruct a planner-shaped plan dict from blueprint state so
    the planner sees the existing app when producing a revised plan."""
    return {
        "models": [
            {"name": e.get("name"), "table": e.get("table"),
             "fields": [{"name": f} for f in (e.get("key_fields") or [])]}
            for e in (bp.entities or []) if e.get("name")
        ],
        "workflows": [
            {"name": w.get("name"),
             "purpose": w.get("purpose"),
             "trigger": {"type": w["trigger"] if isinstance(w.get("trigger"), str) else (w.get("trigger", {}) or {}).get("type", "") or ""}}
            for w in (bp.workflows or []) if w.get("name")
        ],
        "pages": [
            {"route": p.get("route"), "role": p.get("role")}
            for p in (bp.pages or []) if p.get("route")
        ],
    }


def _run_planner_from_sync(**kwargs):
    """Bridge: run the async ``orchestrate_planner`` from sync code.

    Uses a fresh event loop in a worker thread so it works whether or
    not the caller is already inside a running loop (FastAPI is). Reads
    ``orchestrate_planner`` from this module's namespace at call time
    so tests can monkeypatch it."""
    import asyncio
    import concurrent.futures
    import sys

    mod = sys.modules[__name__]

    def _target():
        return asyncio.run(mod.orchestrate_planner(**kwargs))

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(_target).result()


# --------------------------------------------------------------------------- #
# Page-patch authoring — a second LLM call that turns understanding
# into concrete RFC-6902 ops against the actual schema file.
# --------------------------------------------------------------------------- #

_PATCH_SYSTEM = (
    "You are the SMITH ARCHITECT. Given a page schema and a specific "
    "field change to make, return the MINIMAL list of RFC-6902 JSON "
    "patch operations to apply. Output ONLY a JSON array; no prose, "
    "no code fences.\n\n"
    "Rules:\n"
    "  - Prefer `replace` on `/root/children/.../props/type` for a "
    "component-type change (e.g. Select → FileUpload).\n"
    "  - Prefer `remove` for extraneous props that the new component "
    "doesn't accept (e.g. drop `optionsFrom` when moving to FileUpload).\n"
    "  - NEVER invent a path that doesn't resolve in the given schema.\n"
    "  - Output an empty array `[]` if you can't make the change safely."
)


def _author_page_patch(u: dict, output_dir: str) -> list[dict] | None:
    """Ask the model for the RFC-6902 ops to apply to the target
    schema file, given the understood change."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    target = Path(output_dir) / str(u.get("target_file") or "")
    if not target.exists():
        return None
    try:
        schema_text = target.read_text(encoding="utf-8")
    except OSError:
        return None

    prompt = (
        f"## Schema ({target.name})\n```json\n{schema_text}\n```\n\n"
        f"## Change to make\n"
        f"- Element: {u.get('element_label')!r}\n"
        f"- Current: {u.get('current_behavior')}\n"
        f"- Desired: {u.get('desired_behavior')}\n\n"
        "Return the RFC-6902 patch array now."
    )
    try:
        from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim
        client = llm_client.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=_UNDERSTAND_MODEL,
            max_tokens=2048,
            system=_PATCH_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if hasattr(b, "text"))
    except Exception:  # noqa: BLE001
        logger.exception("architect: patch authoring LLM call failed")
        return None

    ops = _extract_json_array(text)
    if not isinstance(ops, list) or not ops:
        return None
    return ops


def _extract_json_array(text: str) -> Any | None:
    if not isinstance(text, str):
        return None
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- #
# Bootstrap wire (Phase C) — Smith owns discovery + planning stages
# for new-app creation. Generation itself stays with the existing
# pipeline (load-bearing, deliberately untouched).
# --------------------------------------------------------------------------- #

# What the caller (chat_with_project) gets back from a bootstrap
# stage run — enough to shape the SSE events already emitted today,
# plus a narrator prose summary Smith authored.
@_dc_dataclass
class BootstrapStageResult:
    """Result of running one bootstrap stage."""
    stage: str            # "discovery" | "planning" | "generation" | "await_approval" | "not_enabled"
    narrator: str = ""    # Smith's architect-voice summary
    dossier: dict | None = None    # populated when stage == "discovery"
    plan: dict | None = None       # populated when stage == "planning"
    error: str | None = None


async def run_bootstrap_stage(
    *,
    project_id: str,
    output_dir: str,
    user_message: str,
    is_discovery_approve: bool,
    is_plan_approve: bool,
    pending_dossier: dict | None,
    org_context: str | None = None,
    domain_context: dict | None = None,
    emit_fn: Any = None,
) -> BootstrapStageResult:
    """One bootstrap stage: discovery, planning, or hand-off to generator.

    Deterministic decision from state + approval signals:

      * No dossier saved AND no approval signal ⇒ run DISCOVERY.
        (Phase B `orchestrate_discovery` + Phase A `record_discovery`.)

      * `[APPROVE_DISCOVERY]` + saved dossier ⇒ run PLANNING.
        (Phase B `orchestrate_planner` + Phase A `record_plan`.)

      * `[APPROVE_PLAN]` ⇒ return stage="generation". The caller
        keeps running the existing generation pipeline — Smith
        doesn't own the build itself; he just narrates before and
        after. Blueprint's ``record_generation_complete`` fires at
        the pipeline's existing completion site (Phase A wiring).

    Never raises — all errors surface via ``result.error`` so the
    caller can fall back to the tactical path."""
    from services.blueprint_pipeline_hooks import record_discovery, record_plan
    from services.smith_narrator import narrate

    try:
        # Stage: hand-off to generation (caller runs existing pipeline)
        if is_plan_approve:
            bp = _load_blueprint_safe(project_id, output_dir)
            prose = narrate(
                stage="generation_handoff",
                fallback=(
                    "Ready to build. Handing off to the generation pipeline — "
                    "I'll narrate as pages, workflows, and schemas materialize."
                ),
                blueprint_context=_blueprint_slice_or_empty(bp),
                user_ask=user_message,
            )
            return BootstrapStageResult(
                stage="generation", narrator=prose,
            )

        # Stage: planning
        if is_discovery_approve and pending_dossier:
            # Bootstrap parity with the classic discover→convert path
            # (JT-T4 extension): synthesise a StructuredBrief from the
            # dossier + user prompt, then prepend the AUTHORITATIVE INPUTS
            # block to the planner's description. The bootstrap flow never
            # creates a DiscoverySession row, so the produce_plan-side
            # brief_lookup returns nothing here — this is the ONLY chance
            # for the bootstrap path to feed the authoritative contract
            # into the planner. On failure we just fall through to the
            # legacy prompt (no regression).
            _description = str(pending_dossier.get("user_prompt") or user_message)
            # Predeclare so a transform_discovery failure below still leaves
            # ``_bootstrap_brief`` bound when we pass it to orchestrate_planner.
            _bootstrap_brief = None
            try:
                from services.discovery_transformer import transform_discovery
                from services.planner_input_render import render_authoritative_block
                _bootstrap_brief = await transform_discovery({
                    "overview":       pending_dossier.get("summary")
                                       or pending_dossier.get("user_prompt")
                                       or user_message,
                    "domain":         pending_dossier.get("domain") or "",
                    "user_prompt":    pending_dossier.get("user_prompt") or user_message,
                    "dossier":        pending_dossier,
                })
                _block = render_authoritative_block(_bootstrap_brief)
                if _block:
                    _description = f"{_block}\n\n{_description}"
                    logger.info(
                        "[bootstrap-plan] injected AUTHORITATIVE INPUTS "
                        "block (%d actors, %d journeys)",
                        len(_bootstrap_brief.actors),
                        len(_bootstrap_brief.user_journeys),
                    )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "[bootstrap-plan] transformer / render failed — "
                    "falling back to legacy description"
                )
            planner_art = await orchestrate_planner(
                description=_description,
                domain_context=domain_context or pending_dossier,
                emit_fn=emit_fn,
                output_dir=output_dir,
                structured_brief=_bootstrap_brief,
            )
            # Blueprint hook (Phase A) — record the plan as Smith authored it.
            plan_dict = _planner_artifact_to_dict(planner_art)
            record_plan(
                output_dir=output_dir, project_id=project_id,
                plan=plan_dict,
            )
            bp = _load_blueprint_safe(project_id, output_dir)
            prose = narrate(
                stage="planning", artifact=planner_art,
                blueprint_context=_blueprint_slice_or_empty(bp),
                user_ask=str(pending_dossier.get("user_prompt") or user_message),
            )
            return BootstrapStageResult(
                stage="planning", narrator=prose, plan=plan_dict,
            )

        # Stage: discovery (default first step for a fresh project)
        discovery_art = await orchestrate_discovery(
            output_dir=output_dir,
            user_message=user_message,
            org_context=org_context,
        )
        dossier_dict = _discovery_artifact_to_dict(discovery_art, user_message)
        # Blueprint hook (Phase A) — records domain + open_questions.
        record_discovery(
            output_dir=output_dir, project_id=project_id,
            dossier=dossier_dict,
        )
        prose = narrate(
            stage="discovery", artifact=discovery_art, user_ask=user_message,
        )
        return BootstrapStageResult(
            stage="discovery", narrator=prose, dossier=dossier_dict,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("architect: bootstrap stage failed")
        return BootstrapStageResult(
            stage="not_enabled",
            error=f"{type(exc).__name__}: {exc}",
        )


def _discovery_artifact_to_dict(art, user_message: str) -> dict:
    """Convert a DiscoveryArtifact back to the dossier dict shape the
    existing SSE emission + ``_save_pending_discovery`` expect.

    Prefers the raw dossier attached by ``orchestrate_discovery``
    (domain-agent shape: personas, designPatterns, visualLanguage,
    entitySuggestions, complianceNotes, etc.) — that's the format the
    rest of the pipeline already consumes. Falls back to a synthesized
    dict when no raw dossier is present (e.g. in tests)."""
    raw = getattr(art, "_raw_dossier", None)
    if isinstance(raw, dict) and raw:
        d = dict(raw)
        d.setdefault("user_prompt", user_message)
        # domain_name is what the blueprint hook + narrator prompt read.
        # Domain-agent dossiers use `domain`; synthesize the alias for
        # consumers that expect `domain_name`.
        d.setdefault("domain_name", art.domain_name)
        return d

    return {
        "domain_name": art.domain_name,
        "actors": list(art.actors),
        "verbs": list(art.verbs),
        "distinctive_shape": art.distinctive_shape,
        "proposed_entities": [
            {"name": e.name, "why": e.why}
            for e in art.proposed_entities
        ],
        "open_questions": list(art.open_questions),
        "confidence": art.confidence,
        "user_prompt": user_message,
    }


def _load_blueprint_safe(project_id: str, output_dir: str):
    """Load the blueprint or None — never raises. Used by the
    narrator to enrich prose with what already exists."""
    try:
        return Blueprint.load(project_id=project_id, output_dir=output_dir)
    except Exception:  # noqa: BLE001
        return None


def _blueprint_slice_or_empty(bp) -> str:
    """Render a compact blueprint slice for the narrator prompt, or ""
    when the blueprint is missing / empty."""
    if bp is None:
        return ""
    try:
        return blueprint_to_context(bp, budget=1200)
    except Exception:  # noqa: BLE001
        return ""


def _planner_artifact_to_dict(art) -> dict:
    """Convert a PlannerArtifact to the plan dict shape the existing
    pipeline + ``record_plan`` + SSE `plan_ready` + frontend PlanCard
    all expect.

    Prefers the raw plan dict attached by ``orchestrate_planner``
    (full workflow ``steps``, entity ``fields`` with types, page
    ``type``, and everything the tactical pipeline downstream reads).
    Falls back to synthesizing from artifact fields when no raw plan
    is present (older callers, unit tests)."""
    raw = getattr(art, "_raw_plan", None)
    if isinstance(raw, dict) and (raw.get("models") or raw.get("pages") or raw.get("workflows")):
        return raw

    return {
        "models": [
            {
                "name": e.name, "table": e.table, "purpose": e.purpose,
                "fields": [{"name": f} for f in e.key_fields],
                "why": e.why_shaped_this_way,
            }
            for e in art.entities
        ],
        "workflows": [
            {"name": w.name, "purpose": w.purpose,
             "trigger": {"type": w.trigger}, "why": w.why}
            for w in art.workflows
        ],
        "pages": [
            {"route": p.route, "schema_path": p.schema_path, "role": p.role}
            for p in art.pages
        ],
    }


# --------------------------------------------------------------------------- #
# Adapter — TurnResult → the dict shape _handle_smith_turn expects
# --------------------------------------------------------------------------- #

def turn_result_to_legacy_dict(result: TurnResult) -> dict[str, Any]:
    """Convert a SmithSession TurnResult into the shape the existing
    ``_handle_smith_turn`` downstream code reads (answer / question /
    handoff / diagnosis / edited_paths / trace).

    ``needs_user`` becomes a question whose text is the architect's
    prose, with the options[] carried on a side-channel dict the
    caller emits as a `smith_needs_user` SSE event."""
    d: dict[str, Any] = {
        "answer":       None,
        "question":     None,
        "handoff":      None,
        "diagnosis":    None,
        "edited_paths": list(result.touched_paths),
        "trace":        list(result.trace),
        # Not part of the legacy shape — the caller peels these off.
        "_needs_user":  None,
        "_status":      result.status,
        "_diff_summary": result.diff_summary,
    }
    if result.status == "resolved":
        d["answer"] = result.answer
    elif result.status == "asked":
        d["question"] = result.answer
    elif result.status == "needs_user":
        d["question"] = result.answer  # visible message
        d["_needs_user"] = {
            "answer":        result.answer,
            "options":       list(result.options),
            "diff_summary":  result.diff_summary,
            "touched_paths": list(result.touched_paths),
        }
    elif result.status == "handoff":
        d["handoff"] = {"kind": "refine", "message": result.answer}
    elif result.status == "no_op":
        d["answer"] = result.answer
    else:  # not_enabled / rolled_back / other
        d["answer"] = result.answer
    return d
