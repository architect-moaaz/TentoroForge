"""Self-healing orchestrator — invokes Smith on a captured runtime
exception, applies the direct edits he makes, updates the exception's
status, and persists the whole turn as a system-authored assistant
message so the user sees the outcome in chat on the next load.

Not to be confused with :mod:`services.self_heal`, which regenerates
deterministically-derivable missing artifacts at gen-time. This module
is the RUNTIME-ERROR loop that ladders on Smith + the file tools we
just added.

The design ladders on top of the tools built earlier in this session:

* :func:`agents.smith_agent.run_smith_agent` — the agent loop, now
  with ``read_file``/``edit_file``/``verify_promise`` in its palette.
* :func:`services.post_generate_fixes.apply_post_generate_fixes` —
  runs the guard suite over Smith's writes before commit.
* :func:`services.fix_applier._commit` — one commit per heal so the
  user can revert easily.

Rate limits:

* Max 5 concurrent heals per project (in-process semaphore).
* Max 20 heal attempts per project per rolling hour (DB check).
* Max 3 attempts per specific exception before we mark it
  ``unresolvable`` and stop trying.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from database import async_session
from models.project import Conversation, MessageRole, MessageType, Project
from models.runtime_exception import (
    RuntimeException,
    RuntimeExceptionStatus,
)


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Rate-limiting state (in-process; fine for single-node dev)
# --------------------------------------------------------------------------- #

_MAX_CONCURRENT_PER_PROJECT = 5
_MAX_HEALS_PER_HOUR = 20
_MAX_ATTEMPTS_PER_EXCEPTION = 3

_project_semaphores: dict[uuid.UUID, asyncio.Semaphore] = defaultdict(
    lambda: asyncio.Semaphore(_MAX_CONCURRENT_PER_PROJECT),
)


def _project_semaphore(project_id: uuid.UUID) -> asyncio.Semaphore:
    return _project_semaphores[project_id]


# --------------------------------------------------------------------------- #
# Public entrypoint
# --------------------------------------------------------------------------- #

async def invoke_smith_on_exception(
    project_id: uuid.UUID, exc_id: uuid.UUID,
) -> dict:
    """Run one heal attempt on the given exception.

    Returns a small status dict for logging / tests. Never raises —
    a failure inside the heal loop is caught and surfaced as
    ``{"status": "error", "reason": …}`` so the caller (a FastAPI
    BackgroundTasks callable) can't crash the request."""
    sem = _project_semaphore(project_id)
    if sem.locked() and sem._value <= 0:
        return {"status": "rate_limited",
                "reason": "concurrent heal cap reached for project"}
    async with sem:
        try:
            return await _run_heal_attempt(project_id, exc_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[self-heal] attempt crashed project=%s exc=%s",
                             project_id, exc_id)
            await _mark_exception(
                exc_id, status=RuntimeExceptionStatus.open,
                summary=f"heal attempt crashed: {exc!r}",
            )
            return {"status": "error", "reason": str(exc)[:400]}


# --------------------------------------------------------------------------- #
# The heal attempt
# --------------------------------------------------------------------------- #

async def _run_heal_attempt(
    project_id: uuid.UUID, exc_id: uuid.UUID,
) -> dict:
    async with async_session() as db:
        row = await db.get(RuntimeException, exc_id)
        if row is None:
            return {"status": "skipped", "reason": "exception vanished"}
        if row.status in (
            RuntimeExceptionStatus.resolved,
            RuntimeExceptionStatus.unresolvable,
            RuntimeExceptionStatus.dismissed,
        ):
            return {"status": "skipped",
                    "reason": f"already {row.status.value}"}

        if (row.heal_attempts or 0) >= _MAX_ATTEMPTS_PER_EXCEPTION:
            row.status = RuntimeExceptionStatus.unresolvable
            row.resolution_summary = (
                f"Gave up after {row.heal_attempts} attempts — Smith could "
                "not reproduce or repair this crash. Ask a human."
            )
            await db.commit()
            return {"status": "unresolvable", "attempts": row.heal_attempts,
                    "reason": "per-exception cap"}

        # Per-project rolling-hour cap.
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        recent = (await db.execute(
            select(func.count(RuntimeException.id)).where(
                RuntimeException.project_id == project_id,
                RuntimeException.last_seen_at >= one_hour_ago,
                RuntimeException.heal_attempts > 0,
            )
        )).scalar_one()
        if recent >= _MAX_HEALS_PER_HOUR:
            return {"status": "rate_limited",
                    "reason": f"{recent} heals in last hour ≥ cap"}

        project = await db.get(Project, project_id)
        if project is None or not project.output_dir:
            return {"status": "skipped",
                    "reason": "project missing or no output_dir"}

        row.status = RuntimeExceptionStatus.in_progress
        row.heal_attempts = (row.heal_attempts or 0) + 1
        await db.commit()
        await db.refresh(row)

        snapshot = _snapshot(row)
        output_dir = project.output_dir
        proj_id = project.id

    prompt = _synthesize_smith_prompt(snapshot)
    logger.info("[self-heal] invoking Smith project=%s exc=%s attempt=%d",
                proj_id, exc_id, snapshot["heal_attempts"])

    # SH-1: publish an in-progress message BEFORE Smith runs so the user sees
    # "🔧 fixing…" the moment the heal starts, not 30-90s later when Smith
    # commits. On completion the SAME conv row is UPDATED (not appended) so
    # the chat panel replaces the progress card with the final result card.
    in_progress_conv_id = await _persist_self_heal_progress(proj_id, snapshot)

    from agents.smith_agent import run_smith_agent
    try:
        recall_block = ""
        try:
            from services.app_recall import assemble_recall
            recall_block = assemble_recall(output_dir).to_prompt_block()
        except Exception:  # noqa: BLE001
            logger.exception("[self-heal] assemble_recall failed")

        memory_block = ""
        try:
            from services.smith_memory import read_smith_memory
            async with async_session() as sess:
                memory = await read_smith_memory(sess, proj_id)
                memory_block = memory.to_prompt_block()
        except Exception:  # noqa: BLE001
            logger.exception("[self-heal] read_smith_memory failed")

        # Enrich the prompt with anchors — the raw error/stack alone made Smith
        # ask "which screen?"; loading the workflow JSON + page schema + registry
        # summary gives him files to act on immediately (no clarifying turn wasted).
        anchor_block = _load_anchor_files(snapshot, output_dir)
        prompt_with_anchors = f"{prompt}\n\n{anchor_block}" if anchor_block else prompt

        # Runtime-exception healing needs more turns than a user-typed
        # chat. When FORGE_SMITH_ORCH=1 the orchestrator loop handles
        # retry-until-guards-green with rollback on give-up — much
        # stronger than the flat max_iters=20 fallback for the classic
        # smith agent.
        import os as _os
        if _os.environ.get("FORGE_SMITH_ORCH") == "1":
            from services.smith_orchestrator import run as _smith_orch_run
            orch = await asyncio.to_thread(
                _smith_orch_run,
                prompt_with_anchors, output_dir,
                project_id=str(proj_id),
            )
            # Adapt to run_smith_agent's shape for the rest of this handler.
            smith_result = {
                "answer":       orch.answer if orch.status in ("resolved", "no_op", "rolled_back") else None,
                "question":     orch.question,
                "handoff":      orch.handoff,
                "diagnosis":    None,
                "edited_paths": orch.applied_paths,
                "trace":        orch.trace,
            }
            logger.info("[smith-orch/self-heal] status=%s turns=%d applied=%d commit=%s",
                        orch.status, orch.turns, len(orch.applied_paths), orch.commit)
        else:
            smith_result = await asyncio.to_thread(
                run_smith_agent, prompt_with_anchors, output_dir, recall_block, memory_block,
                max_iters=20,
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("[self-heal] Smith crashed")
        await _mark_exception(
            exc_id, status=RuntimeExceptionStatus.open,
            summary=f"Smith crashed during heal: {exc!r}",
        )
        return {"status": "error", "reason": str(exc)[:400]}

    edited_paths = smith_result.get("edited_paths") or []
    answer = smith_result.get("answer")
    diagnosis = smith_result.get("diagnosis")

    resolution_commit: str | None = None
    if edited_paths:
        try:
            from services.post_generate_fixes import apply_post_generate_fixes
            from services.fix_applier import _commit
            apply_post_generate_fixes(output_dir)
            summary = ", ".join(edited_paths[:3])
            if len(edited_paths) > 3:
                summary += f" (+{len(edited_paths) - 3} more)"
            _commit(output_dir,
                    f"smith(self-heal exc={str(exc_id)[:8]}): {summary}",
                    git=True,
                    # Stage ONLY what the heal touched (register SX-3). The
                    # paths are right here in `edited_paths`; without them
                    # this fell back to `git add -A` and swept whatever the
                    # user had in progress under output_dir into a commit
                    # attributed to Smith — which S24-6/S24-9 then let "undo
                    # that" destroy.
                    paths=list(edited_paths or []))
            resolution_commit = _read_head_commit(output_dir)
            logger.info("[self-heal] committed %d file(s) commit=%s",
                        len(edited_paths), resolution_commit)
        except Exception:  # noqa: BLE001
            logger.exception("[self-heal] commit failed")

    chat_message = _format_chat_message(snapshot, smith_result,
                                        resolution_commit)
    conv_id = await _persist_self_heal_message(
        proj_id, chat_message, snapshot, edited_paths, resolution_commit,
        smith_result=smith_result,
        existing_conv_id=in_progress_conv_id,
    )

    resolved = bool(edited_paths) and not smith_result.get("question")
    if resolved:
        await _mark_exception(
            exc_id,
            status=RuntimeExceptionStatus.resolved,
            summary=(answer or "Smith applied a fix.")[:2000],
            commit=resolution_commit,
            conversation_id=conv_id,
        )
        return {"status": "resolved", "commit": resolution_commit,
                "attempts": snapshot["heal_attempts"], "files": edited_paths}

    await _mark_exception(
        exc_id,
        status=RuntimeExceptionStatus.open,
        summary=(
            (smith_result.get("question") or smith_result.get("answer")
             or (diagnosis or {}).get("explanation") or "no fix produced")
        )[:2000],
        conversation_id=conv_id,
    )
    return {"status": "attempted", "attempts": snapshot["heal_attempts"],
            "reason": "no edits landed"}


# --------------------------------------------------------------------------- #
# Prompt synthesis
# --------------------------------------------------------------------------- #

def _load_anchor_files(exc: dict, output_dir: str) -> str:
    """Pre-load the files Smith would otherwise have to hunt for.

    Runtime errors carry structured locators (``workflow_id``,
    ``node_id``, ``page_route``) — resolve those to actual file
    contents and inline a summary + the top ~120 lines of each so Smith
    can act on turn 1 instead of asking the user "which screen?" — that
    generic response is exactly what killed the prior heal attempt.

    Silent on any failure — a missing file just shortens the anchor
    block, never crashes the heal loop."""
    import json as _json
    import os

    out_lines: list[str] = ["── ANCHOR FILES (pre-loaded for you) ──"]
    loaded_any = False

    # Workflow anchor — for kind=workflow, load the definition JSON.
    # Two locator paths, tried in order:
    #   1. `workflow_id` on the payload → filename match.
    #   2. `node_id` only (common when the runtime ctx didn't carry a
    #      workflow id) → scan every workflow JSON for a node with that
    #      id and preload the first match. Without this, Smith gets no
    #      anchor for the "No values to set" class and burns his cap
    #      enumerating workflows manually.
    wf_id = exc.get("workflow_id")
    node_id = exc.get("node_id")
    wf_dir = os.path.join(output_dir, "workflows")
    wf_path = None
    if wf_id and os.path.isdir(wf_dir):
        wanted = str(wf_id).lower()
        for fn in os.listdir(wf_dir):
            if fn.lower().endswith(".json") and wanted in fn.lower().replace("_", "").replace("-", ""):
                wf_path = os.path.join(wf_dir, fn)
                break
        if not wf_path:
            candidate = os.path.join(wf_dir, f"{wf_id}.json")
            if os.path.exists(candidate):
                wf_path = candidate
    if wf_path is None and node_id and os.path.isdir(wf_dir):
        # Search every workflow file for a node with the given id.
        wanted_node = str(node_id)
        for fn in sorted(os.listdir(wf_dir)):
            if not fn.lower().endswith(".json"):
                continue
            fp = os.path.join(wf_dir, fn)
            try:
                data = _json.loads(open(fp, "r", encoding="utf-8").read())
            except Exception:  # noqa: BLE001
                continue
            nodes = data.get("nodes") or data.get("steps") or []
            if not isinstance(nodes, list):
                continue
            for n in nodes:
                if isinstance(n, dict) and (n.get("id") == wanted_node
                                             or (n.get("data") or {}).get("id") == wanted_node):
                    wf_path = fp
                    break
            if wf_path:
                break
    if wf_path and os.path.exists(wf_path):
        try:
            text = open(wf_path, "r", encoding="utf-8").read()
            if len(text) > 8000:
                text = text[:8000] + "\n… [truncated]"
            hint = f" (matched via node_id={node_id!r})" if not wf_id and node_id else ""
            out_lines.extend([
                "", f"### workflow: {os.path.relpath(wf_path, output_dir)}{hint}", "```json", text, "```",
            ])
            loaded_any = True
        except Exception:  # noqa: BLE001
            pass

    # Page anchor — for a page-route locator, load the page schema.
    route = exc.get("page_route")
    if route:
        # Strip dynamic-segment values so a route like /appointments/abc-123
        # resolves to the schemas that live under /appointments (list) or
        # /appointments/[id] (detail).
        cleaned = str(route).strip("/").split("?")[0]
        schemas_dir = os.path.join(output_dir, "src", "schemas")
        tried: list[str] = []
        for candidate in (cleaned, cleaned + "/[id]", cleaned.rsplit("/", 1)[0]):
            if not candidate:
                continue
            p = os.path.join(schemas_dir, f"{candidate}.json")
            tried.append(p)
            if os.path.exists(p):
                try:
                    text = open(p, "r", encoding="utf-8").read()
                    if len(text) > 6000:
                        text = text[:6000] + "\n… [truncated]"
                    out_lines.extend([
                        "", f"### page schema: {os.path.relpath(p, output_dir)}", "```json", text, "```",
                    ])
                    loaded_any = True
                    break
                except Exception:  # noqa: BLE001
                    pass

    # Registry summary — always useful (entity names + relations shape).
    reg_path = os.path.join(output_dir, "registry.json")
    if os.path.exists(reg_path):
        try:
            reg = _json.loads(open(reg_path, "r", encoding="utf-8").read())
            ents = reg.get("entities") or {}
            ent_names = sorted(ents.keys()) if isinstance(ents, dict) else []
            wfs = reg.get("workflows") or {}
            wf_names = sorted(wfs.keys()) if isinstance(wfs, dict) else []
            out_lines.extend([
                "", "### registry summary",
                f"entities ({len(ent_names)}): {', '.join(ent_names[:20])}",
                f"workflows ({len(wf_names)}): {', '.join(wf_names[:15])}",
            ])
            loaded_any = True
        except Exception:  # noqa: BLE001
            pass

    if not loaded_any:
        # No locators in the payload — but Smith still has enumeration
        # tools. Explicitly hand him the recipe so he doesn't fall back
        # to `ask_user`. Runtime crashes are the ONE class where "ask
        # the user which screen" is never the right move — the crash IS
        # the ground truth and the app files are enumerable.
        return _no_anchor_directive(exc)
    out_lines.extend([
        "",
        "── END ANCHOR FILES ──",
        "",
        "The files above are already loaded — read them FIRST, don't hunt. "
        "Use `read_workflow` / `read_page` for the full content, `edit_file` "
        "to patch, and `verify_promise` to confirm. This is a RUNTIME CRASH — "
        "the file to fix is one of the anchors above. Do NOT call `ask_user`; "
        "if you truly can't localize, enumerate with `list_workflows` / "
        "`list_pages` and grep the message text.",
    ])
    return "\n".join(out_lines)


def _no_anchor_directive(exc: dict) -> str:
    """The fallback prompt when the exception payload had no locators
    (workflow_id / page_route / node_id all null). Hands Smith an
    explicit enumeration recipe so he can find the culprit himself
    instead of asking the user "which screen?" — the user did not
    trigger this loop, the crash did, and the answer is in the files."""
    msg = str(exc.get("message") or "").strip().replace('"', '\\"')[:200]
    kind = str(exc.get("kind") or "unhandled")
    lines = [
        "── ANCHOR FILES — no direct locators available ──",
        "",
        (
            "The exception payload didn't carry a workflow_id, node_id, "
            "or page_route. That is a REPORTER limitation, not a signal "
            "that the crash is unfixable. The failing artifact IS in the "
            "generated app on disk — you just have to find it."
        ),
        "",
        "STRICT PROCEDURE — do NOT call `ask_user` before finishing this:",
        "",
    ]
    if kind == "workflow":
        lines.extend([
            "  1. Call `list_workflows` to enumerate every workflow.",
            "  2. For each workflow returned, call `read_workflow(workflow_id)` "
            "     and scan the JSON for the failure signature (below).",
            "  3. The failure signature for this crash class is: `db_update` / "
            "     `db_insert` / `db_delete` steps whose `config.where.<field>` "
            "     or `config.values.<field>` binding resolves to empty at "
            "     runtime — usually `{{input.id}}` when the trigger step's "
            "     `config.inputs` doesn't declare an `id` input, or when no "
            "     page.action.input_map supplies it.",
            "  4. Once you find the culprit, `edit_file` to add the missing "
            "     trigger input (or replace the binding with a supplied one), "
            "     then `verify_promise` and `answer` with the workflow name "
            "     and what you changed.",
        ])
    else:
        lines.extend([
            "  1. Call `list_pages` to enumerate every page.",
            "  2. For each page returned, call `read_page(path)` and scan for "
            "     the failure signature in the crash message.",
            "  3. If the crash mentions a route, grep the returned pages for a "
            "     matching route pattern (e.g. `/assessment-days/[id]` when the "
            "     URL is `/assessmentDays/<uuid>` — the app uses kebab-case "
            "     routes so a camelCase URL will 404).",
            "  4. `edit_file` the offending route or nav_flow entry, then "
            "     `verify_promise` and `answer`.",
        ])
    lines.extend([
        "",
        f'The exact error is:  "{msg}"',
        "",
        "Grep for keywords from that message in the workflow / page JSON. "
        "The registry summary above tells you which entities exist so you "
        "can narrow the search. Every artifact you need is enumerable via "
        "a tool — enumerate first, edit second, ask NEVER on this class.",
        "",
        "── END ANCHOR FILES ──",
    ])
    return "\n".join(lines)


def _synthesize_smith_prompt(exc: dict) -> str:
    """Turn the exception row into a plain-language ask Smith can act on.

    Highlights the LOCATOR fields Smith needs to find the file — the
    workflow id + node id for workflow crashes, the page route for page
    crashes, the request url for API crashes. The literal error message
    is included verbatim so Smith can pattern-match on it (this is how
    he'd find e.g. the ``22P02 invalid uuid syntax for ""`` and know to
    inspect ``_buildWhere``)."""
    lines = [
        "A runtime error just happened in the generated app. Fix it.",
        "",
        f"Kind:    {exc['kind']}",
        f"Message: {exc['message']}",
    ]
    if exc.get("source_file"):
        loc = exc["source_file"]
        if exc.get("source_line"):
            loc += f":{exc['source_line']}"
        lines.append(f"Where:   {loc}")
    if exc.get("workflow_id"):
        wf = exc["workflow_id"]
        if exc.get("node_id"):
            wf += f" (node: {exc['node_id']})"
        lines.append(f"Workflow: {wf}")
    if exc.get("page_route"):
        lines.append(f"Page:    {exc['page_route']}")
    if exc.get("request_url"):
        req = exc["request_url"]
        if exc.get("request_method"):
            req = f"{exc['request_method']} {req}"
        lines.append(f"Request: {req}")
    if exc.get("occurrence_count", 0) > 1:
        lines.append(f"Seen:    {exc['occurrence_count']} times")
    if exc.get("stack"):
        stack = str(exc["stack"])
        if len(stack) > 4000:
            stack = stack[:4000] + "\n… [truncated]"
        lines.extend(["", "Stack:", stack])
    lines.extend([
        "",
        "This is a RUNTIME crash captured by the app itself — no user is",
        "asking you a question. Find the culprit and fix it.",
        "",
        "RULES for runtime-exception healing:",
        "  • Do NOT call `ask_user` on this turn. The crash IS the ground",
        "    truth; there is nothing to clarify. If you're tempted to ask",
        "    'which screen/workflow?', call `list_workflows` / `list_pages`",
        "    instead and grep the JSON for the failure signature.",
        "  • Do NOT call `propose_fix` — the runtime file needs a direct",
        "    edit, not a seam patch card.",
        "  • Use `read_workflow` / `read_page` / `read_file` to inspect,",
        "    `edit_file` to patch, `verify_promise` to confirm the fix",
        "    survived a re-run of the guards.",
        "  • `answer` with a short summary of what you changed and where.",
    ])
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _snapshot(row: RuntimeException) -> dict:
    """Copy the exception into a plain dict so we can drop the DB session."""
    return {
        "id": row.id, "project_id": row.project_id,
        "kind": row.kind.value if row.kind else None,
        "message": row.message, "stack": row.stack,
        "source_file": row.source_file, "source_line": row.source_line,
        "workflow_id": row.workflow_id, "node_id": row.node_id,
        "page_route": row.page_route,
        "request_url": row.request_url, "request_method": row.request_method,
        "occurrence_count": row.occurrence_count or 1,
        "heal_attempts": row.heal_attempts or 0,
    }


async def _mark_exception(
    exc_id: uuid.UUID, *,
    status: RuntimeExceptionStatus,
    summary: str | None = None,
    commit: str | None = None,
    conversation_id: uuid.UUID | None = None,
) -> None:
    async with async_session() as db:
        row = await db.get(RuntimeException, exc_id)
        if row is None:
            return
        row.status = status
        if status == RuntimeExceptionStatus.resolved:
            row.resolved_at = datetime.now(timezone.utc)
        if summary is not None:
            row.resolution_summary = summary
        if commit is not None:
            row.resolution_commit = commit
        if conversation_id is not None:
            row.smith_conversation_id = conversation_id
        await db.commit()


def _read_head_commit(output_dir: str) -> str | None:
    import subprocess
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=output_dir, text=True,
        ).strip()
        return out[:12] if out else None
    except Exception:  # noqa: BLE001
        return None


def _format_chat_message(
    exc: dict, smith_result: dict, commit: str | None,
) -> str:
    """The user-visible chat message this heal produces. Deliberately
    conversational — this is a system-authored assistant turn."""
    edited = smith_result.get("edited_paths") or []
    answer = smith_result.get("answer") or ""
    question = smith_result.get("question")

    if question:
        return (
            "🩹 **Self-heal — needs your input**\n\n"
            f"Detected a runtime error: `{exc['message'][:200]}`\n\n"
            f"Smith asks: {question}"
        )
    if edited:
        header = f"🩹 **Self-heal — resolved** (commit `{commit or 'HEAD'}`)"
        files = "\n".join(f"  • `{p}`" for p in edited[:5])
        if len(edited) > 5:
            files += f"\n  • …and {len(edited) - 5} more"
        summary = answer or (
            "Smith identified the offending file and applied a targeted "
            "edit. Verify pass returned kept:true."
        )
        return (
            f"{header}\n\n"
            f"**Symptom:** `{exc['message'][:200]}`\n"
            f"**Files touched:**\n{files}\n\n"
            f"{summary}\n\n"
            "_You can `git revert` this commit if the fix caused a "
            "regression._"
        )
    return (
        "🩹 **Self-heal — no fix produced**\n\n"
        f"Detected a runtime error: `{exc['message'][:200]}`\n\n"
        f"{answer or 'Smith could not localize the fix on this attempt. '}"
        "The exception is still open; if it happens again I'll try once "
        "more (up to 3 attempts total)."
    )


def _shared_self_heal_metadata(exc_snapshot: dict) -> dict:
    """Metadata every SelfHealCard render needs — error anchors + attempt info."""
    return {
        "intent": "SMITH_SELF_HEAL",
        "self_heal": True,
        "exception_id": str(exc_snapshot["id"]),
        "exception_kind": exc_snapshot.get("kind"),
        "error_message": (exc_snapshot.get("message") or "")[:400],
        "workflow_id": exc_snapshot.get("workflow_id"),
        "node_id": exc_snapshot.get("node_id"),
        "page_route": exc_snapshot.get("page_route"),
        "source_file": exc_snapshot.get("source_file"),
        "attempt": exc_snapshot.get("heal_attempts"),
        "max_attempts": _MAX_ATTEMPTS_PER_EXCEPTION,
    }


async def _persist_self_heal_progress(
    project_id: uuid.UUID, exc_snapshot: dict,
) -> uuid.UUID | None:
    """SH-1: insert the ``status="in_progress"`` heal message BEFORE Smith
    runs so the chat panel shows "🔧 fixing…" instantly. Returns the conv
    id so the completion path can UPDATE the same row."""
    metadata = _shared_self_heal_metadata(exc_snapshot)
    metadata["status"] = "in_progress"
    text = (
        f"🔧 Self-heal started — attempting to fix runtime error in "
        f"`{exc_snapshot.get('node_id') or exc_snapshot.get('source_file') or 'the app'}`…"
    )
    try:
        async with async_session() as db:
            conv = Conversation(
                project_id=project_id,
                role=MessageRole.assistant,
                content=text,
                message_type=MessageType.chat,
                metadata_=metadata,
            )
            db.add(conv)
            await db.commit()
            await db.refresh(conv)
        await _publish_self_heal_event(
            str(project_id), str(conv.id), text, metadata,
            conv.created_at.isoformat() if conv.created_at else None,
        )
        return conv.id
    except Exception:  # noqa: BLE001
        logger.exception("[self-heal] progress-message persist failed (non-fatal)")
        return None


async def _publish_self_heal_event(
    project_id: str, conv_id: str, text: str,
    metadata: dict, created_at: str | None,
) -> None:
    """Push to project event bus so open chat panels update live. Failures
    are never blocking — the DB row is authoritative."""
    try:
        from services.project_event_bus import publish
        await publish(project_id, {
            "type": "self_heal_message",
            "conversation_id": conv_id,
            "role": "assistant",
            "content": text,
            "message_type": "chat",
            "metadata": metadata,
            "created_at": created_at,
        })
    except Exception:  # noqa: BLE001
        logger.exception("[self-heal] bus publish failed — chat DB row still authoritative")


async def _persist_self_heal_message(
    project_id: uuid.UUID,
    text: str,
    exc_snapshot: dict,
    edited_paths: list[str],
    commit: str | None,
    *,
    smith_result: dict | None = None,
    existing_conv_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Persist the terminal heal message.

    When ``existing_conv_id`` is provided (SH-1: the in-progress row from
    ``_persist_self_heal_progress``), UPDATE that row in place so the
    frontend replaces the progress card instead of rendering two rows.
    Otherwise INSERT a fresh row (backwards-compatible path)."""
    metadata = _shared_self_heal_metadata(exc_snapshot)
    metadata.update({
        "edited_paths": edited_paths,
        "commit": commit,
    })
    # Terminal status: resolved / asked / failed. Frontend uses this to
    # pick the SelfHealCard variant (icon, color, action buttons).
    if smith_result and smith_result.get("question"):
        metadata["status"] = "asked"
        metadata["question"] = smith_result["question"]
    elif edited_paths:
        metadata["status"] = "resolved"
    else:
        metadata["status"] = "failed"

    async with async_session() as db:
        conv = None
        if existing_conv_id is not None:
            conv = await db.get(Conversation, existing_conv_id)
        if conv is None:
            conv = Conversation(
                project_id=project_id,
                role=MessageRole.assistant,
                content=text,
                message_type=MessageType.chat,
                metadata_=metadata,
            )
            db.add(conv)
        else:
            conv.content = text
            conv.metadata_ = metadata
        await db.commit()
        await db.refresh(conv)

    await _publish_self_heal_event(
        str(project_id), str(conv.id), text, metadata,
        conv.created_at.isoformat() if conv.created_at else None,
    )
    return conv.id
