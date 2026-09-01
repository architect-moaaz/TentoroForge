"""The Fix-Assistant reasoning loop (Slice 3, Task 3-B).

Given a plain-language SYMPTOM plus the app's on-disk recall block, the agent
picks a tool from :mod:`services.fix_agent_tools`, observes the result, and
picks again — until it invokes one of two terminal tools:

- ``propose_fix(diagnosis)`` — the agent presents a structured Diagnosis
  matching the Slice 1-B contract; the caller streams it as a
  ``fix_proposal`` SSE event + stashes ``pending_fix`` for the ``[APPLY_FIX]``
  chip flow. **The agent never applies.**
- ``ask_user(question)`` — one focused clarifying question; the caller streams
  it as a plain ``message`` event.

The palette is closed: only the read-only inspectors + analyzers from Slice
0-2 plus these two terminals. There is no Write/Bash/Edit surface.

The LLM boundary is injectable (``query_fn``) so tests never hit the model. The
default seam uses the Claude Agent SDK the same way :mod:`agents.refiner` does.
"""
from __future__ import annotations

import copy
import json
import logging
import os
from typing import Any, Callable, Iterable, Optional

from services import fix_agent_tools as tools

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

QueryFn = Callable[[str, list[dict], list[dict]], Iterable[dict]]

_TERMINAL = "__terminal__"
_MAX_UNKNOWN_STREAK = 2  # two consecutive unknown-tool calls → force ask_user

# Extended-thinking gating — Sonnet 4.5+, Opus 4+, Fable 5+ support the
# ``thinking={"type":"enabled",…}`` request block. Older sonnet/opus/haiku
# models silently ignore it (or reject on newer server-side gates), so we
# prefix-match here rather than sending it unconditionally.
_THINKING_MODEL_PREFIXES: tuple[str, ...] = (
    "claude-sonnet-4-5",
    "claude-sonnet-4-6",
    "claude-sonnet-5",
    "claude-opus-4",
    "claude-opus-5",
    "claude-fable-5",
)


def _model_supports_thinking(model: str) -> bool:
    """Return True when ``model`` is an Anthropic model in the family
    that supports the extended-thinking request block. Prefix match so
    dated variants (``…-20260215``) all pass."""
    if not isinstance(model, str) or not model:
        return False
    m = model.strip()
    return any(m.startswith(p) for p in _THINKING_MODEL_PREFIXES)


#: Models that take ``thinking={"type": "adaptive"}`` and REJECT
#: ``budget_tokens`` outright (400) — everything from the 4.6 generation on.
#: The model decides how long to think per turn, which is what makes thinking
#: affordable on an interactive loop: a fixed budget spends it whether the turn
#: needs it or not.
_ADAPTIVE_THINKING_PREFIXES: tuple[str, ...] = (
    "claude-opus-4-6", "claude-opus-4-7", "claude-opus-4-8", "claude-opus-5",
    "claude-sonnet-4-6", "claude-sonnet-5", "claude-fable-5",
)

#: Reasoning headroom for the pre-4.6 models that still take an explicit
#: budget, and the headroom added to ``max_tokens`` on the adaptive path,
#: where the cap covers thinking and output together.
THINKING_HEADROOM_TOKENS = 4096


def _thinking_block(model: str) -> "dict | None":
    """The ``thinking`` request block for this model, or None when it has no
    thinking to request.

    NO SWITCH. This was read from ``FORGE_SMITH_THINKING_BUDGET``, defaulting
    to zero — so the reasoning stream, the SSE event and the frontend's
    renderer all worked and emitted nothing, and finding out why meant reading
    four files to arrive at an unset env var. Smith either shows its reasoning
    or it does not, and a flag whose off-position silently removes a
    capability is the shape that has cost this codebase the most.

    TWO FORMS, AND SENDING THE WRONG ONE IS A 400. ``budget_tokens`` is how
    thinking was requested before the 4.6 generation and is rejected outright
    from 4.7 on; `adaptive` is the current form and lets the model decide per
    turn. The supported-model list already named `claude-opus-5` and
    `claude-sonnet-5` while the call site sent them `budget_tokens`, so
    changing the model would have failed every request with an error naming
    neither the model nor the block.
    """
    if not _model_supports_thinking(model):
        return None
    if any(model.strip().startswith(p) for p in _ADAPTIVE_THINKING_PREFIXES):
        return {"type": "adaptive"}
    return {"type": "enabled", "budget_tokens": THINKING_HEADROOM_TOKENS}


def run_fix_agent(
    symptom: str,
    output_dir: str,
    recall_block: str,
    *,
    query_fn: Optional[QueryFn] = None,
    max_iters: int = 8,
) -> dict:
    """Run the reasoning loop.

    Args:
        symptom: The user's plain-language symptom.
        output_dir: Path to the generated app on disk.
        recall_block: Pre-assembled recall block (from
            ``assemble_recall(output_dir).to_prompt_block()``) — injected up
            front so every agent turn doesn't have to re-recall.
        query_fn: LLM boundary — a callable ``(system, messages, tools)`` that
            yields ``{"tool": <name>, "args": <dict>}`` dicts, one per turn. In
            tests, canned iterators of these dicts stand in for the model. When
            ``None``, uses the real Claude Agent SDK (requires
            ``ANTHROPIC_API_KEY``).
        max_iters: Hard cap on tool-call turns before the loop forces a
            terminal ``ask_user`` with whatever it learned so far.

    Returns:
        ``{"diagnosis": <Diagnosis>|None, "question": str|None,
           "trace": [{"tool", "args", "result_summary"}, ...]}``.
    """
    system_prompt = build_system_prompt()
    messages: list[dict] = [{
        "role": "user",
        "content": build_initial_user_message(symptom, recall_block),
    }]

    fn = query_fn or _default_query
    stream = fn(system_prompt, messages, list(tools.TOOL_CATALOG))
    trace: list[dict] = []
    diagnosis: Optional[dict] = None
    question: Optional[str] = None
    unknown_streak = 0

    for step in _bounded(stream, max_iters):
        tool_name = str((step or {}).get("tool") or "").strip()
        args = (step or {}).get("args")
        if not isinstance(args, dict):
            args = {}

        # ---- terminal tools ------------------------------------------------
        if tool_name == "propose_fix":
            diag_raw = args.get("diagnosis")
            valid, err_msg, normalized = _validate_diagnosis(diag_raw, symptom, output_dir)
            if not valid:
                trace.append({
                    "tool": tool_name,
                    "args": _trim_args(args),
                    "result_summary": f"invalid diagnosis: {err_msg}",
                })
                messages.append({
                    "role": "tool",
                    "tool": tool_name,
                    "content": json.dumps({"error": err_msg}),
                })
                continue
            trace.append({
                "tool": tool_name,
                "args": _trim_args(args),
                "result_summary": (
                    f"propose_fix: seam={(normalized.get('proposedFix') or {}).get('seam')} "
                    f"confidence={normalized.get('confidence')}"
                ),
            })
            diagnosis = normalized
            break

        if tool_name == "ask_user":
            q = args.get("question") or args.get("text") or args.get("message")
            if not isinstance(q, str) or not q.strip():
                trace.append({
                    "tool": tool_name,
                    "args": _trim_args(args),
                    "result_summary": "invalid ask_user: missing question",
                })
                messages.append({
                    "role": "tool",
                    "tool": tool_name,
                    "content": json.dumps({"error": "question must be a non-empty string"}),
                })
                continue
            trace.append({
                "tool": tool_name,
                "args": _trim_args(args),
                "result_summary": "ask_user",
            })
            question = q.strip()
            break

        # ---- read-only tools ----------------------------------------------
        tool_fn = _READONLY_TOOLS.get(tool_name)
        if tool_fn is None:
            unknown_streak += 1
            trace.append({
                "tool": tool_name or "<empty>",
                "args": _trim_args(args),
                "result_summary": f"unknown tool (streak={unknown_streak})",
            })
            messages.append({
                "role": "tool",
                "tool": tool_name or "<empty>",
                "content": json.dumps({
                    "error": (
                        f"unknown tool {tool_name!r}. Valid tools: "
                        + ", ".join(t["name"] for t in tools.TOOL_CATALOG)
                    ),
                }),
            })
            if unknown_streak >= _MAX_UNKNOWN_STREAK:
                question = (
                    "I'm not sure which part of the app to look at. "
                    "Could you tell me the screen you were on and the exact "
                    "error you saw?"
                )
                trace.append({
                    "tool": "ask_user",
                    "args": {"question": question, "forced": "unknown_tools"},
                    "result_summary": "forced ask_user after unknown tools",
                })
                break
            continue
        unknown_streak = 0

        try:
            result = tool_fn(output_dir, args)
        except Exception as exc:  # noqa: BLE001 — a tool crash must not blow up the loop
            logger.exception("fix_chat_agent: tool %s crashed", tool_name)
            result = {"error": f"tool crashed: {exc}"}
        trace.append({
            "tool": tool_name,
            "args": _trim_args(args),
            "result_summary": _summarize_result(result),
        })
        messages.append({
            "role": "tool",
            "tool": tool_name,
            "content": _serialize_for_llm(result),
        })
    else:
        # Iteration cap hit without a terminal call — force ask_user.
        question = (
            "I looked at the app but couldn't localize the issue with "
            "confidence in the turns I had. Could you tell me the screen you "
            "were on and the exact error you saw?"
        )
        trace.append({
            "tool": "ask_user",
            "args": {"question": question, "forced": "iteration_cap"},
            "result_summary": "forced ask_user at iteration cap",
        })

    return {"diagnosis": diagnosis, "question": question, "trace": trace}


# --------------------------------------------------------------------------- #
# System prompt + initial user message
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = (
    "You are Tentoro's Fix-Assistant. Diagnose a broken feature from a "
    "plain-language symptom using the tools below. INVESTIGATE FIRST (recall, "
    "then read the suspect workflow/page, then run analyzers) BEFORE proposing. "
    "Every proposed fix MUST target a real artifact + node/pointer AND "
    "validate clean. If you cannot localize with confidence, use `ask_user`. "
    "Never guess.\n\n"
    "Diagnosis contract (for propose_fix):\n"
    "  {\n"
    "    \"feature\": <what this feature is meant to do>,\n"
    "    \"rootCause\": <the precise defect>,\n"
    "    \"artifact\": {\"kind\": \"workflow\"|\"page\"|\"schema\", \"path\": <rel path>},\n"
    "    \"locator\": {\"nodeId\": <workflow node id | null>, \"jsonPointer\": <RFC-6901 | null>},\n"
    "    \"proposedFix\": {\n"
    "       \"seam\": \"workflow_node_config\"|\"page_schema_patch\"|\"code_edit\",\n"
    "       \"patch\": <object for workflow_node_config / list for page_schema_patch>\n"
    "    },\n"
    "    \"confidence\": <0..1>,\n"
    "    \"explanation\": <plain-language for the end user>\n"
    "  }\n\n"
    "Rules:\n"
    "- Bind ONLY to resources you can see via the tools. Never invent an entity, "
    "column, or workflow id.\n"
    "- For a workflow-value bug: use seam=workflow_node_config and patch a "
    "config-merge dict `{\"values\": {...FULL corrected values map...}}`. "
    "Rebind wrong literals to `{{input}}` bindings; drop columns you cannot "
    "safely correct (they take the DB default).\n"
    "- Use code_edit only as a last resort.\n"
    "- One tool call per turn. When you have enough evidence, call "
    "`propose_fix`. If you don't, call `ask_user`.\n"
)


def build_system_prompt() -> str:
    catalog_lines = "\n".join(
        f"- {t['name']}({_sig_args(t['signature'])}): {t['desc']}"
        for t in tools.TOOL_CATALOG
    )
    return SYSTEM_PROMPT + "\nTOOL PALETTE:\n" + catalog_lines


def _sig_args(sig: str) -> str:
    """Extract the args portion of a signature string like ``foo(a, b) -> x``."""
    l = sig.find("(")
    r = sig.find(")")
    if 0 <= l < r:
        return sig[l + 1:r]
    return ""


def build_initial_user_message(symptom: str, recall_block: str) -> str:
    return (
        f"SYMPTOM: {symptom}\n\n"
        f"## App recall (pre-assembled — you may call `recall` again for re-checks)\n"
        f"{recall_block or '(no recall available)'}\n\n"
        "Investigate with the tools, then either `propose_fix` or `ask_user`."
    )


# --------------------------------------------------------------------------- #
# Read-only tool dispatch table
# --------------------------------------------------------------------------- #

def _t_recall(output_dir: str, args: dict) -> dict:
    return tools.recall(output_dir)

def _t_list_workflows(output_dir: str, args: dict) -> dict:
    return tools.list_workflows(output_dir)

def _t_read_workflow(output_dir: str, args: dict) -> dict:
    return tools.read_workflow(output_dir, args.get("path", ""))

def _t_read_page(output_dir: str, args: dict) -> dict:
    return tools.read_page(output_dir, args.get("path", ""))

def _t_read_column(output_dir: str, args: dict) -> dict:
    return tools.read_column(output_dir, args.get("entity", ""), args.get("column", ""))

def _t_analyze(output_dir: str, args: dict) -> dict:
    return tools.analyze_workflow_values_tool(output_dir, args.get("path", ""))

def _t_parse_error(output_dir: str, args: dict) -> dict:
    return tools.parse_error_tool(args.get("text", ""))

def _t_probe_logs(output_dir: str, args: dict) -> dict:
    lines = args.get("lines", 200)
    return tools.probe_logs_tool(output_dir, lines=lines)

def _t_probe_endpoint(output_dir: str, args: dict) -> dict:
    return tools.probe_endpoint_tool(output_dir, args.get("url", ""))


_READONLY_TOOLS: dict[str, Callable[[str, dict], dict]] = {
    "recall": _t_recall,
    "list_workflows": _t_list_workflows,
    "read_workflow": _t_read_workflow,
    "read_page": _t_read_page,
    "read_column": _t_read_column,
    "analyze_workflow_values": _t_analyze,
    "parse_error": _t_parse_error,
    "probe_logs": _t_probe_logs,
    "probe_endpoint": _t_probe_endpoint,
}


# --------------------------------------------------------------------------- #
# Diagnosis validation (matches the Slice 1-B contract)
# --------------------------------------------------------------------------- #

_ALLOWED_ARTIFACT_KINDS = {"workflow", "page", "schema", "code"}
_ALLOWED_SEAMS = {"workflow_node_config", "page_schema_patch",
                  "add_page", "add_workflow", "add_entity", "code_edit"}


def _validate_diagnosis(raw: Any, symptom: str, output_dir: str) -> tuple[bool, str, dict]:
    """Validate the shape of a proposed Diagnosis; when it's a
    ``workflow_node_config`` fix, re-validate by applying the merge to a copy
    of the workflow node and re-running the analyzer. Returns
    ``(ok, error_message, normalized)``.

    A dirty re-analysis is not fatal — the diagnosis passes with a lowered
    confidence and a note appended to the explanation (mirrors
    fix_diagnoser._normalize_diagnosis's behaviour)."""
    if not isinstance(raw, dict):
        return False, "diagnosis must be a JSON object", {}
    artifact = raw.get("artifact") if isinstance(raw.get("artifact"), dict) else {}
    kind = artifact.get("kind")
    path = artifact.get("path")
    if kind not in _ALLOWED_ARTIFACT_KINDS:
        return False, f"artifact.kind must be one of {sorted(_ALLOWED_ARTIFACT_KINDS)}", {}
    if kind != "code" and not (isinstance(path, str) and path.strip()):
        return False, "artifact.path is required for non-code artifacts", {}
    locator = raw.get("locator") if isinstance(raw.get("locator"), dict) else {"nodeId": None, "jsonPointer": None}
    proposed = raw.get("proposedFix") if isinstance(raw.get("proposedFix"), dict) else {}
    seam = proposed.get("seam")
    if seam not in _ALLOWED_SEAMS:
        return False, f"proposedFix.seam must be one of {sorted(_ALLOWED_SEAMS)}", {}
    patch = proposed.get("patch")
    if seam == "workflow_node_config" and not isinstance(patch, dict):
        return False, "workflow_node_config patch must be an object", {}
    if seam == "page_schema_patch" and not isinstance(patch, list):
        return False, "page_schema_patch patch must be a list of RFC-6902 ops", {}
    if seam == "add_page":
        if not isinstance(patch, dict):
            return False, "add_page patch must be an object with archetype/entity/route", {}
        for req in ("archetype", "entity", "route"):
            if not patch.get(req):
                return False, f"add_page patch is missing required field {req!r}", {}
    if seam == "add_workflow":
        if not isinstance(patch, dict):
            return False, "add_workflow patch must be an object with op/entity", {}
        for req in ("op", "entity"):
            if not patch.get(req):
                return False, f"add_workflow patch is missing required field {req!r}", {}
    if seam == "add_entity":
        if not isinstance(patch, dict):
            return False, "add_entity patch must be an object with name/fields", {}
        if not patch.get("name"):
            return False, "add_entity patch is missing required field 'name'", {}
        if not isinstance(patch.get("fields"), list) or not patch["fields"]:
            return False, "add_entity patch.fields must be a non-empty list", {}

    try:
        confidence = float(raw.get("confidence", 0.6))
    except (TypeError, ValueError):
        confidence = 0.6

    normalized: dict = {
        "symptom": symptom,
        "feature": raw.get("feature") or "unknown",
        "rootCause": raw.get("rootCause") or "",
        "artifact": {"kind": kind, "path": path},
        "locator": {
            "nodeId": locator.get("nodeId"),
            "jsonPointer": locator.get("jsonPointer"),
        },
        "proposedFix": {"seam": seam, "patch": patch if patch is not None else ({} if seam != "page_schema_patch" else [])},
        "confidence": max(0.0, min(1.0, confidence)),
        "explanation": raw.get("explanation") or "",
        "validation": {"clean": None, "remaining": []},
    }

    # workflow_node_config gets a live re-validate via the analyzer.
    if seam == "workflow_node_config" and locator.get("nodeId"):
        node_id = locator.get("nodeId")
        try:
            validation = _revalidate_workflow_patch(output_dir, path, node_id, patch or {})
            normalized["validation"] = validation
            if validation.get("clean") is False:
                normalized["confidence"] = min(normalized["confidence"], 0.25)
                normalized["explanation"] = (
                    (normalized["explanation"] + " ").strip()
                    + "(Heads up: the proposed change still leaves a type mismatch — "
                    "review before applying.)"
                )
        except Exception:  # noqa: BLE001
            logger.exception("fix_chat_agent: revalidate failed")

    if seam == "code_edit":
        normalized["confidence"] = min(normalized["confidence"], 0.3)

    return True, "", normalized


def _revalidate_workflow_patch(output_dir: str, rel_path: str, node_id: str, patch: dict) -> dict:
    """Apply the config-merge to a COPY of the node and re-run the analyzer.
    Returns ``{"clean": bool, "remaining": [findings]}``.

    Shares semantics with ``agents.fix_diagnoser.validate_workflow_patch``
    (which the applier also uses). Kept local to avoid importing the diagnoser
    for one function — the agent already imports the analyzer directly."""
    from services.workflow_value_types import (
        analyze_workflow_values,
        columns_by_table_from_registry,
    )
    abs_path = os.path.join(output_dir, rel_path) if not os.path.isabs(rel_path) else rel_path
    try:
        with open(abs_path, encoding="utf-8") as fh:
            wf = json.load(fh)
    except (OSError, ValueError):
        return {"clean": False, "remaining": [{"reason": "workflow not readable"}]}
    if not isinstance(wf, dict):
        return {"clean": False, "remaining": [{"reason": "workflow not a JSON object"}]}
    defn = copy.deepcopy(wf.get("definition") or {})
    node = None
    for n in (defn.get("nodes") or []):
        if isinstance(n, dict) and (n.get("id") == node_id
                                    or (n.get("data") or {}).get("id") == node_id):
            node = n
            break
    if node is None:
        return {"clean": False, "remaining": [{"reason": f"node {node_id} not found"}]}
    cfg = node.setdefault("data", {}).setdefault("config", {})
    if isinstance(patch, dict):
        cfg.update(patch)  # shallow merge — mirrors routers/workflows.py PATCH
    try:
        with open(os.path.join(output_dir, "contracts", "resource-registry.json"),
                  encoding="utf-8") as fh:
            registry = json.load(fh)
    except (OSError, ValueError):
        registry = {}
    cbt = columns_by_table_from_registry(registry)
    findings = analyze_workflow_values(defn, cbt)
    return {"clean": not findings, "remaining": findings}


# --------------------------------------------------------------------------- #
# Trace / message helpers
# --------------------------------------------------------------------------- #

_TRACE_TRIM = 500


def _summarize_result(result: Any) -> str:
    """Compact string summary of a tool result for the trace log."""
    try:
        s = json.dumps(result, default=str)
    except (TypeError, ValueError):
        s = str(result)
    return s if len(s) <= _TRACE_TRIM else s[:_TRACE_TRIM] + "…"


def _serialize_for_llm(result: Any) -> str:
    """Serialize a tool result for insertion into the next model turn."""
    try:
        return json.dumps(result, default=str)
    except (TypeError, ValueError):
        return json.dumps({"error": "unserializable result"})


def _trim_args(args: dict) -> dict:
    """Clone args, trimming any oversized string so the trace stays readable."""
    out: dict = {}
    for k, v in (args or {}).items():
        if isinstance(v, str) and len(v) > _TRACE_TRIM:
            out[k] = v[:_TRACE_TRIM] + "…"
        else:
            out[k] = v
    return out


def _bounded(stream: Iterable[dict], max_iters: int) -> Iterable[dict]:
    """Iterate ``stream`` but stop after ``max_iters`` items (loop uses a
    ``for/else`` on this — the ``else`` fires only when the stream ended AND
    the cap was NOT hit inside the loop's ``break``)."""
    i = 0
    for step in stream:
        if i >= max_iters:
            return
        yield step
        i += 1


# --------------------------------------------------------------------------- #
# Default LLM boundary — real Claude Agent SDK.
# --------------------------------------------------------------------------- #

def _compose_user_content(
    last_user_content: Any,
    tool_msgs: list[str],
    instruction: str,
):
    """Build one turn's user content — a plain string, or a block list.

    The last user turn used to always be a string, so this was a `join`.
    Attachments made it an anthropic-style block list, and joining a list
    raises TypeError. Flattening it to text would be worse: the images
    would vanish silently and Smith would answer about a screenshot it
    never received.

    Returns a **string** when there is no media to carry (identical request
    shape to before attachments existed) and a **block list** otherwise.
    The instruction always lands last — behind an image, the model tends to
    narrate rather than emit the tool-call JSON the runner parses.
    """
    trailer_parts: list[str] = []
    if tool_msgs:
        trailer_parts.append("Tool results so far:\n" + "\n".join(tool_msgs))
    trailer_parts.append(instruction)
    trailer = "\n\n".join(trailer_parts)

    if not isinstance(last_user_content, list):
        head = str(last_user_content or "")
        return f"{head}\n\n{trailer}" if head else trailer

    text_bits: list[str] = []
    media: list[dict] = []
    for b in last_user_content:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text":
            t = b.get("text")
            if isinstance(t, str) and t:
                text_bits.append(t)
        elif b.get("type") in ("image", "document"):
            media.append(b)

    head = "\n\n".join(text_bits)
    if not media:
        # All-text blocks: no reason to pay the block-list request shape.
        return f"{head}\n\n{trailer}" if head else trailer

    out: list[dict] = []
    if head:
        out.append({"type": "text", "text": head})
    out.extend(media)
    out.append({"type": "text", "text": trailer})
    return out


def _default_query(
    system_prompt: str,
    messages: list[dict],
    tool_catalog: list[dict],
    reasoning_callback: Optional[Callable[[str], None]] = None,
) -> Iterable[dict]:
    """Real-model boundary. Mirrors :mod:`agents.refiner` — uses the Claude
    Agent SDK with an explicit tool catalog rendered into the system prompt
    and no unfettered file-system access.

    Rather than exposing the tools as SDK-native tools (which the SDK will
    execute for us, muddying the reasoning trace), we stream the model as a
    plain chat and expect each turn to emit ONE tool-call JSON object of the
    form ``{"tool":"read_workflow","args":{"path":"..."}}``. The runner
    executes it and appends the result as the next user message. This keeps
    the loop identical in shape to the injected test seam.

    When ``reasoning_callback`` is given and the target model supports
    Anthropic's extended thinking, each thinking block in the response is
    forwarded to the callback verbatim BEFORE the tool-call JSON is parsed. This lets the caller (e.g. the SSE
    stream in ``routers/generate.py``) surface Smith's reasoning to the
    UI without changing the parsed-tool-call return shape.

    Raises ``RuntimeError`` when no ``ANTHROPIC_API_KEY`` is set (mirrors
    :mod:`agents.fix_diagnoser`)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "run_fix_agent's default LLM seam requires ANTHROPIC_API_KEY "
            "(or an injected query_fn)."
        )
    try:
        from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError(f"anthropic SDK unavailable: {exc}") from exc

    client = llm_client.Anthropic(api_key=api_key)
    convo = list(messages)

    model = "claude-sonnet-4-6"
    thinking = _thinking_block(model)
    thinking_on = thinking is not None

    def _next_turn() -> Optional[dict]:  # noqa: ANN001
        last_user_pos = max(
            (i for i, m in enumerate(convo) if m.get("role") == "user"),
            default=0,
        )
        # Flatten tool observations after the last user turn into a synthetic
        # user turn so the model sees them in a single message.
        tool_msgs = [
            f"[tool {m.get('tool')}] {m.get('content')}"
            for m in convo[last_user_pos + 1:]
            if m.get("role") == "tool"
        ]
        # `content` is a string on ordinary turns and an anthropic block list
        # when the user attached images/documents — _compose_user_content
        # keeps the media intact instead of string-joining it away.
        user_prompt = _compose_user_content(
            convo[last_user_pos].get("content", ""),
            tool_msgs,
            'Respond with a single JSON object: {"tool": "...", "args": {...}}. '
            "No prose, no markdown fences.",
        )

        create_kwargs: dict[str, Any] = {
            "model": model,
            # Response budget stays 1500 tokens; when thinking is on we
            # add the thinking budget on top so the model has room for
            # both the internal reasoning tokens and the tool-call JSON.
            "max_tokens": 1500 + (THINKING_HEADROOM_TOKENS if thinking_on else 0),
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        if thinking_on:
            # Extended thinking requires temperature=1.0; the API rejects
            # other values when the thinking block is present.
            create_kwargs["temperature"] = 1.0
            create_kwargs["thinking"] = thinking

        msg = client.messages.create(**create_kwargs)

        # Forward reasoning blocks BEFORE parsing the tool call so the
        # UI sees Smith "think out loud" first, then the tool chip. The
        # non-streaming path emits them as a single burst per turn.
        if reasoning_callback is not None:
            for b in msg.content:
                if hasattr(b, "thinking"):
                    chunk = getattr(b, "thinking", None)
                    if isinstance(chunk, str) and chunk.strip():
                        try:
                            reasoning_callback(chunk)
                        except Exception:  # noqa: BLE001
                            logger.exception("reasoning_callback raised — ignored")

        # ThinkingBlock has ``.thinking`` (not ``.text``), so the existing
        # text extractor picks up only the actual answer text blocks.
        text = "".join(b.text for b in msg.content if hasattr(b, "text"))
        return _parse_tool_call(text)

    while True:
        step = _next_turn()
        if step is None:
            return
        yield step
        # Runner will append the tool result to `convo` externally via the
        # closure? No — this generator can't see updates. The real runner is
        # single-threaded via `messages` mutation upstream; on the SDK path
        # tool observations are visible on the next iteration only when the
        # runner appends them BEFORE calling `_next_turn` again. Since the
        # runner (:func:`run_fix_agent`) mutates the same list we captured in
        # `convo = list(messages)`, updates from outside won't reach us —
        # so we mirror them by re-reading `messages` at each step.
        convo = list(messages)


def _parse_tool_call(text: str) -> Optional[dict]:
    """Parse a single ``{"tool":..., "args":...}`` object out of the model's
    reply. Tolerant of leading prose / fenced code — returns ``None`` when it
    can't find a valid object."""
    if not isinstance(text, str) or not text.strip():
        return None
    # Trim ```json ... ``` fence if present.
    s = text.strip()
    if s.startswith("```"):
        # drop opening fence
        first_nl = s.find("\n")
        if first_nl >= 0:
            s = s[first_nl + 1:]
        # drop closing fence
        end = s.rfind("```")
        if end >= 0:
            s = s[:end]
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(s[start:i + 1])
                    if isinstance(obj, dict) and "tool" in obj:
                        return obj
                    return None
                except ValueError:
                    return None
    return None
