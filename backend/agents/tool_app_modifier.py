"""_tool_app_modifier — the modify/add sub-agent Smith calls.

A Claude-Code-style ReAct loop. Tool palette: Read, Bash, Edit, Write,
RegistryPatch. Every mutation ask (edit a field, add an entity, add a
page) flows through this agent. Smith stays the architect voice; this
agent does the surgery.

The system prompt enforces the 7-step ordering from the hand-drawn
spec — Read Registry → Read Contract → Find Files → Impact Analysis
→ Modify → Validate → Update Registry & Plan.

After the agent's terminal, the guard suite fires
(``apply_post_generate_fixes``) so the file / registry / contract
representations end up internally consistent.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Optional

from services import tool_app_modifier_tools as tools


logger = logging.getLogger(__name__)


QueryFn = Callable[[str, list[dict], list[dict]], Awaitable[list[dict]]]
"""LLM boundary — (system_prompt, messages, tool_catalog) → assistant steps.

Each step is a dict with either:
  * ``{tool: str, args: dict}`` — call a tool, keep looping
  * ``{tool: "answer", args: {text: str}}`` — terminal, report to caller
  * ``{tool: "ask", args: {question: str}}`` — terminal, need user input
"""


SYSTEM_PROMPT = """\
You are _tool_app_modifier — Smith's mutation surgeon.

The user (via Smith) is asking you to change one thing about the
generated app on disk. The app lives entirely inside a project's
output_dir. You have five primitives:

  Read(path, offset?, limit?)         — inspect any file in the project
  Bash(command, cwd?)                 — read-only shell (grep, jq, find, ls, python3)
  Edit(path, old_string, new_string,  — exact-string replace an anchor
       replace_all?)
  Write(path, content)                — create a NEW file (refuses overwrite)
  RegistryPatch(kind, op, entry)      — structured update to registry.json,
                                        plan.json, contracts/*.json

You must follow this 7-step loop for every mutation. Do NOT skip
steps. Do NOT invent shortcuts.

  1. Read Registry.
     Read registry.json AND contracts/resource-registry.json.
     Know every entity, page, workflow, dataSource that already exists.

  2. Read Contract.
     Read packages/registry/dist/component-contracts.json for the
     component prop schemas. Read contracts/*.json in the project for
     the platform's action + binding contracts.

  3. Find Files — route-first, then structured, then dumb grep.

     The ask almost always names a SCREEN (e.g. "add candidate page",
     "orders list") + an ELEMENT (a field, a button, a column). Use
     the registry you just read to jump to the schema; do NOT open
     with `grep 'CV Upload'` — user labels rarely match on-disk text.

     Recipe (do these in order, STOP at the first one that resolves):

     a) MAP THE SCREEN → SCHEMA PATH.
        You already have registry.json in memory. Run:
          Bash: jq -r '.pages[] | select(.route|test("<slug>";"i"))
                                       // (.title|test("<phrase>";"i"))
                                | "\\(.path)\\t\\(.route)\\t\\(.title)"' registry.json
        Substitute <slug> with the noun in the ask ("candidate", "order")
        and <phrase> with the verb+noun ("add candidate", "edit order").
        You want ONE file back. If you get several, pick the one whose
        route matches the verb (create=/new, edit=/[id]/edit, list=root).

     b) READ THE SCHEMA.
        Read the winning path directly. Its `root` is a tree of
        {type, props, children}. Locate the ELEMENT by walking the tree
        for `type` (FileUpload, Input, Select, Button, Table…) filtered
        by `props.label` / `props.name` / `props.dataSource`. Prefer
        SEMANTIC match — a FileUpload with `props.accept` mentioning
        "pdf" IS the CV upload even if the label says "Resume".

     c) FALLBACK — JQ SEMANTIC SWEEP over the schema file:
        Bash: jq '.. | objects | select(
                (.type//"" | test("FileUpload|Input";"i"))
                and (
                  (.props.label//"" | test("<needle>";"i")) or
                  (.props.name//""  | test("<needle>";"i")) or
                  (.props.accept//""| test("<needle>";"i"))
                )
              )' <schema_path>
        with <needle> = the noun stem (cv|resume, phone, address).

     d) LAST RESORT — repository-wide grep. Only if a) and b) both
        returned nothing. Use `grep -rlE '<needle>' src/schemas/` and
        stop at the first hit.

     Do NOT run more than 3 Bash calls in step 3. If those 3 don't
     converge, terminate with `ask` and quote the specific pages you
     did find so the user can point at the right one.

  4. Identify + Analyze Impact.
     For each file identified:
       - Impact: what OTHER workflow / page / registry entry depends
         on this file? Enumerate.
       - Gap analysis (for adds): what artifacts are MISSING that must
         be created? Standard CRUD slice = entity + list + create +
         detail + edit + workflow + registry entries + nav.
     If a template is needed for a Write (new file), Read an existing
     analog in this same project — a similar entity's Drizzle schema,
     a similar page's JSON — and adapt from it. Do not invent shapes.

  5. Modify + Create the appropriate files.
     Edit existing files with unique anchors. Write new files based
     on templates you just read. Order: data model → registry entry
     for the entity → pages → workflow → nav.

  6. Ensure schemas are correct & complete.
     After each Edit/Write, Read the file back or run a Bash validation
     (`python3 -c "import json; json.load(open('<path>'))"`). If a
     validation fails, GO BACK to step 5 with the failure info.

  7. Update Registry & Plan & Contracts.
     Use RegistryPatch(kind, op, entry) for every entity, page,
     workflow, dataSource, or action you added / removed / modified
     in step 5. This keeps registry.json, plan.json, and
     contracts/*.json in sync with the files on disk.

Terminals — end the turn with ONE of:

  {"tool": "answer", "args": {"text": "<user-facing summary of what changed>"}}
    Use when the mutation succeeded. Text is a plain-English one-liner.

  {"tool": "ask", "args": {"question": "<one specific question>"}}
    Use when the ask is genuinely ambiguous — e.g. two candidate targets,
    or two valid strategies where only the user can pick. Do NOT use
    this to punt design decisions the user pays you to make.

Ambiguity threshold: if you can pick a reasonable default and mention
it, DO — don't ask. Only ask when the choice is load-bearing and can't
be inferred.

Never call the same tool with the same args twice. If you tried
something and it failed, try a different approach on the next call.

Bounded budget: 20 tool calls max per turn. Prefer to answer with
partial progress + a note than to burn iterations.
"""


# --------------------------------------------------------------------------- #
# Public entry
# --------------------------------------------------------------------------- #

async def run_tool_app_modifier(
    *,
    ask: str,
    output_dir: str,
    project_id: str = "",
    blueprint_summary: str = "",
    query_fn: Optional[QueryFn] = None,
    max_iters: int = 20,
    emit_fn: Any = None,
) -> dict:
    """Run one modify/add turn.

    Args:
      ask: the user's plain-language mutation request.
      output_dir: the project's on-disk root.
      project_id: passed for logging.
      blueprint_summary: compact slice Smith supplies so the modifier
        knows what Smith knows.
      query_fn: LLM boundary. Tests inject a canned iterator; prod
        supplies a real Claude Agent SDK call. When None the loop is
        a no-op that returns immediately.
      max_iters: hard cap on tool calls.
      emit_fn: optional per-step callback (stage, payload) → None, so
        callers can stream progress as SSE.

    Returns:
      {status, summary, files_touched, registry_delta, validation, trace,
       question_for_user, commit}
    """
    def _emit(stage: str, payload: dict) -> None:
        if emit_fn is None:
            return
        try:
            emit_fn(stage, payload)
        except Exception:  # noqa: BLE001
            logger.exception("modifier: emit_fn raised — ignored")

    trace: list[dict] = []
    files_touched: list[dict] = []
    registry_delta: dict[str, list] = {"added": [], "removed": [], "modified": []}
    question_for_user: str | None = None
    commit: str | None = None
    final_answer: str | None = None

    if query_fn is None:
        # No LLM wired — return a stub result so callers can smoke-test
        # the plumbing without an API key. Not a real answer.
        return {
            "status": "not_enabled",
            "summary": "modifier ran without an LLM boundary (query_fn=None)",
            "files_touched": [], "registry_delta": registry_delta,
            "validation": {}, "trace": [], "commit": None,
            "question_for_user": None,
        }

    initial_user = _build_initial_user_message(
        ask=ask, output_dir=output_dir, blueprint_summary=blueprint_summary,
    )
    messages: list[dict] = [{"role": "user", "content": initial_user}]

    seen_calls: set[str] = set()
    import inspect as _inspect
    stream = query_fn(SYSTEM_PROMPT, messages, list(tools.TOOL_CATALOG))
    try:
        if _inspect.isawaitable(stream):
            stream = await stream
    except Exception as exc:  # noqa: BLE001
        logger.exception("modifier: query_fn crashed")
        return {
            "status": "failed",
            "summary": f"LLM boundary crashed: {type(exc).__name__}: {exc}",
            "files_touched": [], "registry_delta": registry_delta,
            "validation": {}, "trace": trace, "commit": None,
            "question_for_user": None,
        }

    logger.info("modifier: starting loop (max_iters=%d) ask=%r", max_iters, ask[:80])
    _step_iter = iter(stream or [])
    _iter_count = 0
    while _iter_count < max_iters:
        try:
            step = next(_step_iter)
        except StopIteration:
            break
        _iter_count += 1
        logger.info("modifier: iter %d/%d tool=%s",
                    _iter_count, max_iters,
                    (step or {}).get("tool") or "<none>")
        tool_name = str((step or {}).get("tool") or "").strip()
        args = (step or {}).get("args") or {}
        _emit("modifier_step", {"tool": tool_name, "args": args})

        # ── terminals ──────────────────────────────────────────────
        if tool_name == "answer":
            final_answer = str(args.get("text") or "").strip() or "Applied."
            trace.append({"tool": tool_name, "args": args,
                          "result_summary": final_answer[:200]})
            break
        if tool_name == "ask":
            question_for_user = str(args.get("question") or "").strip()
            trace.append({"tool": tool_name, "args": args,
                          "result_summary": question_for_user[:200]})
            break

        # ── tool calls ─────────────────────────────────────────────
        key = _canonical_call_key(tool_name, args)
        if key in seen_calls:
            _dup_hint = (
                f"You already called {tool_name} with these exact args and "
                "the observation didn't help. Do NOT repeat this call. "
                "Try a different approach: change the search pattern, pivot "
                "to Read on a specific path, use jq on the registry to map "
                "the ask's noun to a page/entity, or terminate with `ask` "
                "if you're stuck."
            )
            trace.append({
                "tool": tool_name, "args": args,
                "result_summary": "SKIPPED — duplicate call this turn",
            })
            messages.append({
                "role": "tool", "tool": tool_name,
                "content": json.dumps({"error": "duplicate_call", "hint": _dup_hint}),
            })
            continue
        seen_calls.add(key)

        handler = tools.HANDLERS.get(tool_name)
        if handler is None:
            unknown_msg = (
                f"ERROR — unknown tool. Palette: "
                + ", ".join(t["name"] for t in tools.TOOL_CATALOG)
            )
            trace.append({
                "tool": tool_name, "args": args,
                "result_summary": unknown_msg,
            })
            messages.append({
                "role": "tool", "tool": tool_name or "<empty>",
                "content": json.dumps({"error": unknown_msg})[:2000],
            })
            continue

        try:
            result = handler(output_dir, args)
        except Exception as exc:  # noqa: BLE001
            logger.exception("modifier: handler %s crashed", tool_name)
            result = {"ok": False, "error": f"handler crash: {exc}"}

        summary = _summarize_result(tool_name, args, result)
        trace.append({"tool": tool_name, "args": args, "result_summary": summary})
        try:
            _obs_body = json.dumps(result, default=str)[:4000]
        except Exception:  # noqa: BLE001
            _obs_body = f'{{"ok":false,"error":"unserializable result: {type(result).__name__}"}}'
        messages.append({
            "role": "tool", "tool": tool_name, "content": _obs_body,
        })

        # Accumulate side-effect metadata for the caller.
        if tool_name in ("Edit", "Write") and result.get("ok"):
            files_touched.append({
                "path": str(args.get("path") or ""),
                "action": "created" if tool_name == "Write" else "modified",
                "size":   result.get("new_size") or result.get("size"),
            })
        elif tool_name == "RegistryPatch" and result.get("ok"):
            for ft in result.get("files_touched") or []:
                if ft not in files_touched:
                    files_touched.append(ft)
            delta = result.get("delta") or {}
            op = delta.get("op")
            if op in registry_delta:
                registry_delta[op + "ed" if op != "add" else "added"].append(delta)

    if _iter_count >= max_iters and final_answer is None and question_for_user is None:
        logger.warning("modifier: hit max_iters=%d without terminal", max_iters)

    # ── post-terminal guard suite ──────────────────────────────────
    validation: dict[str, Any] = {}
    if files_touched:
        try:
            from services.post_generate_fixes import (
                apply_post_generate_fixes_with_result,
            )
            gr = apply_post_generate_fixes_with_result(output_dir)
            validation["guard_failures"] = [
                {"guard": f.guard, "message": f.message}
                for f in (gr.failures or [])
            ][:20]
            validation["guard_count"] = len(gr.failures or [])
        except Exception:  # noqa: BLE001
            logger.exception("modifier: guard suite crashed")
            validation["guard_failures"] = []
            validation["guard_error"] = "guard suite crashed"

        # git commit if we made any mutation
        try:
            import subprocess as _sp
            # Stage ONLY what this run edited. `git add -A` swept the user's
            # in-progress work in output_dir into a commit attributed to
            # Smith (register SX-3) — and a later "undo that" would then
            # destroy work that was never separately committed. Every step
            # above already recorded its path in `files_touched`.
            _staged = [str(ft.get("path") or "").strip()
                       for ft in files_touched if str(ft.get("path") or "").strip()]
            if _staged:
                _sp.run(["git", "add", "--", *_staged], cwd=output_dir,
                        check=False, capture_output=True)
            else:
                logger.warning(
                    "modifier: no files_touched recorded — staging nothing "
                    "rather than sweeping the working tree into a Smith commit"
                )
            from services.git_service import COMMIT_ACTOR_TRAILER
            msg = (f"[tool_app_modifier] {final_answer or ask[:80]}"
                   f"\n\n{COMMIT_ACTOR_TRAILER}: smith")
            r = _sp.run(
                ["git", "commit", "-m", msg],
                cwd=output_dir, capture_output=True, text=True,
            )
            if r.returncode == 0:
                rev = _sp.run(
                    ["git", "rev-parse", "--short", "HEAD"],
                    cwd=output_dir, capture_output=True, text=True,
                )
                commit = (rev.stdout or "").strip() or None
        except Exception:  # noqa: BLE001
            logger.exception("modifier: git commit failed")

    # ── build the final envelope ───────────────────────────────────
    if question_for_user:
        status = "blocked"
        summary = question_for_user
    elif final_answer is not None and files_touched:
        status = "applied"
        summary = final_answer
    elif final_answer is not None:
        status = "no_change_needed"
        summary = final_answer
    else:
        status = "failed"
        summary = "Hit iteration cap without a terminal."

    return {
        "status": status,
        "summary": summary,
        "files_touched": files_touched,
        "registry_delta": registry_delta,
        "validation": validation,
        "trace": trace,
        "commit": commit,
        "question_for_user": question_for_user,
    }


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _build_initial_user_message(
    *, ask: str, output_dir: str, blueprint_summary: str,
) -> str:
    parts = [
        "## The user's ask",
        ask,
        "",
        "## Project",
        f"output_dir: {output_dir}",
    ]
    if blueprint_summary.strip():
        parts.extend(["", "## Blueprint slice (what Smith already knows)",
                      blueprint_summary.strip()])
    parts.extend([
        "",
        "Run the 7-step loop. Start with step 1 — Read the registry.",
    ])
    return "\n".join(parts)


def _canonical_call_key(tool: str, args: dict) -> str:
    try:
        return f"{tool}::{json.dumps(args or {}, sort_keys=True, default=str)}"
    except Exception:  # noqa: BLE001
        return f"{tool}::{str(args)[:400]}"


# --------------------------------------------------------------------------- #
# Sync wrapper for Smith's tool dispatcher
# --------------------------------------------------------------------------- #

def run_tool_app_modifier_sync(
    *,
    ask: str,
    output_dir: str,
    project_id: str = "",
    blueprint_summary: str = "",
    max_iters: int = 20,
    emit_fn: Any = None,
) -> dict:
    """Sync entry — what Smith's tool handler calls.

    Smith's tool dispatch is synchronous (see ``READONLY_HANDLERS`` in
    ``services/smith_tools.py``), so this wrapper (a) adapts the sync
    SDK boundary (``fix_chat_agent._default_query``) into an async
    ``query_fn``, and (b) runs the async modifier in a worker thread
    with a fresh event loop so it works even when the caller (FastAPI)
    is already inside one.
    """
    import asyncio as _asyncio
    import concurrent.futures as _cf

    # Sync SDK step-stream → async adapter for the modifier's contract.
    from agents.fix_chat_agent import _default_query as _sdk_query

    async def _adapter(system_prompt, messages, catalog):
        # _sdk_query is a sync generator that re-reads ``messages`` at
        # each yield to pick up observations the modifier appends between
        # steps. Return the generator itself — do NOT materialize with
        # list() or the model never sees tool results and loops forever.
        return _sdk_query(system_prompt, messages, catalog)

    def _target():
        return _asyncio.run(run_tool_app_modifier(
            ask=ask,
            output_dir=output_dir,
            project_id=project_id,
            blueprint_summary=blueprint_summary,
            query_fn=_adapter,
            max_iters=max_iters,
            emit_fn=emit_fn,
        ))

    try:
        with _cf.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_target).result()
    except Exception as exc:  # noqa: BLE001 — must not raise into Smith's dispatch
        logger.exception("run_tool_app_modifier_sync crashed")
        return {
            "status": "failed",
            "summary": f"modifier crashed: {type(exc).__name__}: {exc}",
            "files_touched": [], "registry_delta": {"added":[], "removed":[], "modified":[]},
            "validation": {}, "trace": [], "commit": None,
            "question_for_user": None,
        }


def _summarize_result(tool: str, args: dict, result: dict) -> str:
    """One-line human-readable summary of a tool call result — used
    in the trace so Smith can narrate what the modifier did."""
    if not isinstance(result, dict):
        return f"{tool} — unrecognized result shape"
    if not result.get("ok"):
        return f"{tool} FAILED: {result.get('error', 'unknown')}"
    if tool == "Read":
        p = args.get("path", "?")
        return f"Read {p} — {result.get('lines', 0)} lines"
    if tool == "Bash":
        cmd = str(args.get("command", ""))[:80]
        stdout = (result.get("stdout") or "").strip()
        head = stdout.splitlines()[0][:120] if stdout else "(empty)"
        return f"Bash `{cmd}` exit={result.get('exit_code')} → {head}"
    if tool == "Edit":
        return (
            f"Edit {args.get('path', '?')} — "
            f"replaced {result.get('matches_replaced', 0)} match(es)"
        )
    if tool == "Write":
        return f"Write {result.get('path', '?')} — {result.get('size', 0)} bytes"
    if tool == "RegistryPatch":
        d = result.get("delta") or {}
        return (
            f"RegistryPatch {d.get('kind')} {d.get('op')} {d.get('key')} — "
            f"{len(result.get('files_touched') or [])} file(s)"
        )
    return f"{tool} — ok"
