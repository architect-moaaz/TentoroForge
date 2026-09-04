"""Smith — the platform's conversational build/fix assistant.

Given the user's plain-language turn PLUS the app's recall dossier + the
cross-turn memory block, Smith picks a tool from
:mod:`services.smith_tools`, observes the result, and picks again — until
he invokes one of three terminal tools:

- ``propose_fix(diagnosis)`` — a code change proposal
  (workflow_node_config OR page_schema_patch seam). The caller streams
  this as a ``fix_proposal`` SSE event + stashes ``pending_fix`` on the
  turn so the frontend's Apply-fix chip flow works unchanged. This is
  Smith's write path — same one the fix-assistant uses.
- ``answer(text)`` — a plain conversational reply. No code change.
  Used for "explain how X works", "why is Y designed that way",
  discussion, or acknowledging that no action is needed.
- ``ask_user(question)`` — one focused clarifying question when Smith
  cannot pin down the ask.

Structurally identical to :mod:`agents.fix_chat_agent`. The differences
are three: the tool palette is broader (via :mod:`services.smith_tools`),
the system prompt frames Smith as a build partner rather than a fix
specialist, and the initial user message threads in
``<smith-memory>`` alongside the recall block.

Shared utilities (Diagnosis validation, iterator bounding, model-boundary
serializers, the default Anthropic SDK query loop) are imported from
:mod:`agents.fix_chat_agent` — duplicating them would drift.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Iterable, Optional

from services import smith_tools

# Shared plumbing — Smith is structurally a superset of the fix agent, so
# the utilities that are already battle-tested get imported rather than
# re-implemented.
from agents.fix_chat_agent import (
    _bounded,
    _default_query,
    _serialize_for_llm,
    _summarize_result,
    _trim_args,
    _validate_diagnosis,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

QueryFn = Callable[[str, list[dict], list[dict]], Iterable[dict]]

_MAX_UNKNOWN_STREAK = 2

# Tools that MUTATE files on disk. If any of these appears in the trace and no
# subsequent ``verify_promise`` / ``run_guards`` follows, ``answer`` is
# refused — the model must prove the edit landed before it may claim it did.
_MUTATING_TOOLS = frozenset({
    "edit_file", "edit_page", "edit_workflow",
    "add_page", "add_workflow", "add_entity",
    # NOTE: no "add_component" — it was advertised here and in the mutation-guard
    # prompt but has NO handler in smith_tools, so the model was steered to call a
    # phantom tool that dead-ended ("Smith doesn't do it"). Adding a section/
    # component is done through edit_page.
    "remove_page", "wire_form_to_workflow",
    # 21st.dev component splice — fetches JSX, converts to schema, calls
    # edit_page internally. edit_page's mutation is already caught, but
    # naming this too keeps the mutation-intent gate honest at the outer
    # tool name the LLM invokes.
    "use_21st_component",
    # These three reach a workflow write too and were absent (register
    # S24-1), so they bypassed the verify-before-answer gate, the
    # understand_ask gate and the fabricated-"Done!" gate. `plan_and_apply`
    # in particular runs an LLM-authored chain of up to 8 seam calls
    # unattended — the LAST thing that should answer without verifying.
    "plan_and_apply", "_tool_app_modifier", "set_field_interaction",
    # Writes a project_rules row + re-exports rules/index.json into the app.
    "create_business_rule",
})
_VERIFYING_TOOLS = frozenset({"verify_promise", "run_guards"})

# Tools that produce a VERIFIABLE EFFECT the user needs (deploy, publish).
# These aren't disk mutations — they kick off a background job — but they
# ARE actions the user asked for. When the user says "deploy the app",
# `answer` must be preceded by one of these; otherwise Smith is punting.
_EFFECT_TOOLS = frozenset({"publish"})
# Verbs that trigger the deploy-intent guard. Matched as whole words on
# a lowercased copy of the message. Kept narrow — false positives here
# force one extra `publish` call at worst.
_DEPLOY_INTENT_VERBS = frozenset({
    "deploy", "publish", "ship", "release",
})


# --------------------------------------------------------------------------- #
# Mutation-intent detection                                                   #
# --------------------------------------------------------------------------- #
# When the user's message asks for a change ("remove the Department field"),
# refusing ``answer`` unless a mutating tool was called stops the LLM from
# fabricating "Done!" replies (the B-020-class Smith regression). Kept
# deliberately narrow — a false positive here forces one extra tool call at
# worst, never a wrong action.
#
# Verbs are matched as whole words, case-insensitive. Grouped by
# confidence: strong verbs (remove/delete/add/rename) are unambiguous;
# soft verbs (fix/update/change) may still refer to a discussion.
_STRONG_MUTATION_VERBS = frozenset({
    "remove", "delete", "drop", "hide",
    "add", "insert", "create", "wire",
    "rename", "replace", "swap",
    "move", "reorder",
    # Expanded: common change verbs that were NOT covered, so a mutation ask
    # phrased with them slipped past the anti-fabrication guard and Smith could
    # reply a confident "Done!" with zero edits.
    "convert", "switch", "eliminate", "strip", "toggle",
    "enable", "disable", "duplicate", "combine", "merge",
    "split", "attach", "detach", "connect", "disconnect",
    "unhide", "show", "restyle", "recolor", "relabel",
})
_SOFT_MUTATION_VERBS = frozenset({
    "change", "update", "set", "make",
    "fix", "correct", "adjust", "turn", "convert", "edit", "modify",
})
# Multi-word mutation phrases the whole-word verb matcher can't catch.
_MUTATION_PHRASES = (
    "get rid of", "take out", "turn into", "turn it into", "get rid",
    "do away with", "clear out", "pull out",
)

# Anaphora-only follow-ups where the referent lives in an earlier turn.
# These are NOT mutations by themselves — "did you fix it?" is a question
# ABOUT a prior mutation ask, not a fresh one. Excluded from the guard so
# a question about a hallucinated "Done!" doesn't get flagged as a
# mutation of its own.
_QUESTION_STARTS = ("did you", "does it", "is it", "was it", "have you", "can you")


# --------------------------------------------------------------------------- #
# Claim-count overclaim detection                                              #
# --------------------------------------------------------------------------- #
# Smith's LLM composes "Done! I did 1, 2, 3, 4, 5" from its PLAN, not from
# the actual edit_page result. When only 2 of 5 changes actually landed,
# the reply is fabrication. We detect that by comparing the claim count
# in the answer text to the concrete change count from the tool result.


import re as _re


def _count_answer_claims(text: str) -> int:
    """Rough count of specific claims in the answer text.

    Signals (any of):
      • numbered list items ``1.`` / ``1)`` — count them
      • markdown bullets ``• - *`` at line start — count them
      • otherwise 1 (a prose reply is one claim)

    Deliberately conservative — a false-high triggers unnecessary
    rewrites, a false-low lets fabrication through. Numbered/bulleted
    lists are the failure mode we saw live, so we optimize for those.
    """
    if not isinstance(text, str) or not text.strip():
        return 0
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    numbered = sum(1 for ln in lines if _re.match(r"^\d+[.)]\s+", ln))
    if numbered >= 2:
        return numbered
    bulleted = sum(1 for ln in lines if _re.match(r"^[-*•]\s+", ln))
    if bulleted >= 2:
        return bulleted
    return 1


def _last_edit_page_changes(trace: list[dict]) -> list[dict] | None:
    """Find the most recent ``edit_page`` tool call in the trace and
    return its ``changes`` list. Returns ``None`` when no edit_page ran
    or its result didn't carry a change list (older callers).
    """
    for step in reversed(trace):
        if not isinstance(step, dict):
            continue
        if step.get("tool") != "edit_page":
            continue
        # The result payload is stashed on the messages array in the
        # calling loop, but we only kept a summary in the trace. To
        # avoid changing the trace shape, we parse the summary — the
        # llm_edit result_summary format is stable.
        summary = step.get("result_summary") or ""
        # We also stashed the raw changes on the trace entry when
        # edit_page landed — see the call-site patch in the tool
        # dispatcher below.
        changes = step.get("changes")
        if isinstance(changes, list):
            return changes
    return None


def _answer_overclaims_edit(
    trace: list[dict], answer_text: str,
) -> tuple[int, int, list[dict]] | None:
    """Return (claim_count, change_count, change_list) when the answer
    text enumerates more concrete claims than the last edit_page result
    actually produced. Returns ``None`` when there's no overclaim (safe
    to accept the answer)."""
    changes = _last_edit_page_changes(trace)
    if not isinstance(changes, list):
        return None
    change_count = sum(
        1 for c in changes if isinstance(c, dict)
        and c.get("kind") in ("text-changed", "added", "removed", "value-changed")
    )
    claim_count = _count_answer_claims(answer_text)
    # Guard fires only when the answer is a 3+ item enumeration. A
    # short prose "Done!" reply falls through — that class is caught
    # by the existing mutation-intent guard.
    if claim_count < 3:
        return None
    if claim_count <= change_count:
        return None
    return (claim_count, change_count, changes)


def _is_mutation_intent(text: str) -> bool:
    """Return True when the user's message is asking Smith to CHANGE the
    app on disk (as opposed to explain / diagnose / discuss).

    Signals:
      * a strong mutation verb anywhere in the message, OR
      * a soft mutation verb + at least one target-shaped noun phrase
        (route path, entity capitalized, .json / .tsx / .ts filename).

    Question-only follow-ups ("did you fix it?") return False — the
    referent lives in the earlier turn, and the guard should fire on
    THAT turn's ask, not on the question about it.
    """
    if not text or not isinstance(text, str):
        return False
    stripped = text.strip().lower()
    if not stripped:
        return False

    # Question-only follow-ups — Smith's job here is to answer, not to
    # re-mutate. Return False so the guard doesn't force a redundant edit.
    for prefix in _QUESTION_STARTS:
        if stripped.startswith(prefix):
            return False

    import re
    # Multi-word mutation phrases ("get rid of", "turn into") the whole-word
    # matcher below can't see.
    if any(p in stripped for p in _MUTATION_PHRASES):
        return True
    words = set(re.findall(r"[a-z]+", stripped))
    # "turn X into Y" / "change X into Y" — a transform, regardless of the words
    # in between (the phrase list only caught them adjacent).
    if "into" in words and words & {"turn", "change", "convert", "make", "split"}:
        return True
    if words & _STRONG_MUTATION_VERBS:
        return True

    if words & _SOFT_MUTATION_VERBS:
        # Require a target-shaped noun to avoid firing on chat like
        # "change my mind" / "fix it later". Any of: a `/route/path`,
        # a `filename.tsx`, a capitalized noun in the raw text.
        has_route = "/" in text
        has_filename = bool(re.search(r"\.(tsx|ts|json|jsx|js|css)\b", text))
        has_capitalized = bool(re.search(r"\b[A-Z][a-zA-Z0-9]{2,}\b", text))
        if has_route or has_filename or has_capitalized:
            return True

    return False


def _is_deploy_intent(text: str) -> bool:
    """Return True when the user's message is asking Smith to deploy /
    publish / ship the app. Symmetric to :func:`_is_mutation_intent` but
    scoped to effect verbs — a punt on ``deploy the app`` is the failure
    mode this catches.

    Question-only follow-ups ("did you deploy it?") return False; the
    user is asking about a PRIOR deploy, not requesting a fresh one.
    """
    if not text or not isinstance(text, str):
        return False
    stripped = text.strip().lower()
    if not stripped:
        return False
    for prefix in _QUESTION_STARTS:
        if stripped.startswith(prefix):
            return False
    import re
    words = set(re.findall(r"[a-z]+", stripped))
    return bool(words & _DEPLOY_INTENT_VERBS)


_VERIFY_INTENT_PHRASES = (
    "verify", "self-verify", "self verify",
    "test the app", "test my app", "test the whole app",
    "check the app", "check my app",
    "run tests", "run the tests",
    "does it work", "is it working",
    "find bugs", "find any bugs", "find issues",
    "fix the app", "fix everything", "fix all",
    "make sure it works", "make sure everything works",
    "audit the app", "audit my app",
    "smoke test", "smoke-test",
)


def _is_verify_intent(text: str) -> bool:
    """Return True when the user's message is asking Smith to run the
    Self-Verify Pass on the whole app (as opposed to editing / explaining
    a single screen). Symmetric to :func:`_is_mutation_intent` /
    :func:`_is_deploy_intent`.

    Whole-app asks like "verify and fix the app" are intentionally broad;
    the scope-check gate should NOT trigger a screen-picking clarification
    on these. When this returns True, the router bypasses scope-check and
    routes straight to the Self-Verify Pass.

    Question-only follow-ups ("did you verify it?") return False — those
    ask about a PRIOR run, not a fresh one. But "does it work?" / "is it
    working?" are LEGIT verify asks (the user genuinely wants a check),
    so we only filter question-follow-ups that reference prior action
    ("did you …", "have you …", "were you …").
    """
    if not text or not isinstance(text, str):
        return False
    stripped = text.strip().lower()
    if not stripped:
        return False
    # Prior-action follow-ups only — NOT all questions.
    _PRIOR_ACTION_STARTS = ("did you", "have you", "were you", "did it", "have you already")
    for prefix in _PRIOR_ACTION_STARTS:
        if stripped.startswith(prefix):
            return False
    return any(phrase in stripped for phrase in _VERIFY_INTENT_PHRASES)


def _build_informed_scope_question(
    user_message: str, output_dir: str, trace: list[dict],
) -> str:
    """Punt fallback: instead of "I couldn't pin down your ask", show the
    user WHAT we searched for and what came back.

    Priority:
      1. Grounding matched ≥1 entity → enumerate its primary pages (same
         format as the deterministic scope-check).
      2. Grounding matched nothing → list the noun phrases we tried and
         ask the user to name the target directly.
      3. All else → conservative apology naming a concrete next step.
    """
    try:
        from services.smith_grounding import (
            _extract_candidates,
            _guess_target_kind,
            _looks_like_feature_add,
        )
        from services.smith_find_resources import find_resources
    except Exception:  # noqa: BLE001
        return (
            "I looked at the app but couldn't pin down what you're asking "
            "about. Could you name the specific page (e.g. `/candidates`) "
            "or component you'd like me to work on?"
        )

    # Workflow-targeted asks must not fall back to a PAGE picker — the
    # ask names a workflow, so enumerate workflows instead and ask which
    # node/message the user means.
    if _re.search(r"workflows?", user_message or "", _re.I):
        try:
            import glob as _glob
            import os as _os
            wf_files = sorted(
                _os.path.basename(f)
                for f in _glob.glob(_os.path.join(output_dir, "workflows", "*.json"))
            )
        except Exception:  # noqa: BLE001
            wf_files = []
        if wf_files:
            listing = "\n".join(f"  • `{w}`" for w in wf_files[:15])
            return (
                "I couldn't complete that workflow change on my own. The "
                "app's workflows are:\n" + listing +
                "\n\nCould you tell me which workflow file and, if you know "
                "it, which step/notification you mean? A short quote of the "
                "current message text also helps me find the exact node."
            )

    candidates = _extract_candidates(user_message or "") if user_message else []
    matches: list[dict] = []
    seen_entities: set[str] = set()
    for cand in candidates:
        try:
            r = find_resources(output_dir, cand)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(r, dict):
            continue
        ent = r.get("matched_entity")
        if not ent or ent in seen_entities:
            continue
        seen_entities.add(ent)
        matches.append({"query": cand, "resource": r})

    if matches:
        m = matches[0]
        r = m["resource"]
        ent = r.get("matched_entity")
        pages = r.get("pages") or []
        wf_count = len(r.get("workflows") or [])
        kind_order = {"list": 0, "detail": 1, "create": 2, "edit": 3}
        pages_sorted = sorted(
            pages,
            key=lambda p: (kind_order.get(p.get("kind"), 99), p.get("route", "")),
        )
        guess = _guess_target_kind(user_message or "")
        page_lines: list[str] = []
        for p in pages_sorted:
            route = p.get("route", "")
            kind = p.get("kind", "")
            marker = "  ← likely for this ask" if kind == guess else ""
            page_lines.append(f"  • `{route}` ({kind}){marker}")

        deps = r.get("fks_in") or []
        hint_line = (
            f"**{ent}** has **{len(pages)} primary pages**"
            + (f" and **{wf_count} workflows**" if wf_count else "")
            + (
                "; dependent entities: "
                + ", ".join(sorted({d['from'].split('.')[0] for d in deps}))
                if deps
                else ""
            )
        )
        feature_hint = ""
        if _looks_like_feature_add(user_message or ""):
            feature_hint = (
                "\n\nYour ask sounds like a **new feature**. Two ways to add it:\n"
                "  1. **Replace an existing page** with a new archetype\n"
                "  2. **Add a new page** at a new route\n"
                "Which do you prefer, and which page (if replacing)?"
            )
        return (
            f"📍 {hint_line}\n\n"
            + ("Which one has the issue?\n" if not feature_hint else "Pick a target:\n")
            + "\n".join(page_lines)
            + feature_hint
        )

    if candidates:
        tried = ", ".join(f"`{c}`" for c in candidates[:5])
        return (
            f"I searched for {tried} in the app map but didn't find a "
            "matching page or entity. Could you name the exact route "
            "(e.g. `/candidates/[id]/edit`) or the entity as it appears "
            "in the sidebar?"
        )

    return (
        "I couldn't pin down which part of the app your ask targets. "
        "Could you name the specific page (e.g. `/candidates`) or the "
        "entity as it appears in the sidebar?"
    )


def _pending_confirmation_from(trace: list[dict]) -> Optional[dict]:
    """The LAST confirmation request in ``trace``, or None.

    A tool that wants confirmation returns ``{"status": "needs_confirmation",
    kind, target, …}``. Recording that server-side is what makes a
    subsequent "yes" grantable without depending on the model relaying the
    prompt verbatim (register S24-8).
    """
    for step in reversed(trace or []):
        if not isinstance(step, dict):
            continue
        pending = step.get("needs_confirmation")
        if isinstance(pending, dict) and pending:
            return {"tool": step.get("tool"), **pending}
    return None


def _edits_without_matching_verify(trace: list[dict]) -> list[str]:
    """Return names of mutating tools called with no verify/run_guards
    after the last one. Empty list ⇒ safe to answer."""
    last_mutation_idx = -1
    last_mutation_names: list[str] = []
    for i, step in enumerate(trace):
        tool = step.get("tool") or ""
        if tool in _MUTATING_TOOLS:
            # Skip calls that never reached the tool — rejected by the
            # scoping guard or any other pre-dispatch guard.
            #
            # This used to be a SUBSTRING TEST on `result_summary`, which is
            # model-authored prose: a real edit reporting "edit refused for
            # step 3 but applied for step 1" contains the word "refused", so
            # the gate treated it as no edit at all and let `answer` through
            # with nothing verified (register S24-2). Every pre-dispatch
            # refusal site knows the truth at the moment it records the
            # entry, so it now says so with `ran: False` and this gate reads
            # the flag. Absent flag ⇒ assume it RAN: over-gating costs one
            # verify call, under-gating ships an unverified edit.
            if step.get("ran") is False:
                continue
            if i > last_mutation_idx:
                last_mutation_idx = i
                last_mutation_names = [tool]
            elif i == last_mutation_idx:
                last_mutation_names.append(tool)
    if last_mutation_idx < 0:
        return []
    for step in trace[last_mutation_idx + 1:]:
        if (step.get("tool") or "") in _VERIFYING_TOOLS:
            return []
    return last_mutation_names


def run_smith_agent(
    user_message: str,
    output_dir: str,
    recall_block: str,
    memory_block: str = "",
    *,
    prior_messages: Optional[list[dict]] = None,
    query_fn: Optional[QueryFn] = None,
    max_iters: int = 16,
    scoped_tools: Optional[list[str]] = None,
    reasoning_callback: Optional[Callable[[str], None]] = None,
    progress_callback: Optional[Callable[[dict], None]] = None,
    pending_confirmation: Optional[dict] = None,
    current_route: Optional[str] = None,
    attachment_blocks: Optional[list[dict]] = None,
) -> dict:
    """Run the conversational reasoning loop.

    Args:
        user_message: The user's turn text (plain language).
        output_dir: Path to the generated app on disk.
        recall_block: Pre-assembled recall block
            (``assemble_recall(...).to_prompt_block()``).
        memory_block: Pre-assembled Smith memory block
            (``read_smith_memory(...).to_prompt_block()``). Optional —
            an empty string is treated as "no prior memory available".
        query_fn: LLM boundary — tests inject a canned iterator. When
            ``None``, uses the real Claude Agent SDK boundary shared with
            the fix agent (:func:`agents.fix_chat_agent._default_query`).
        max_iters: Hard cap on tool-call turns before the loop forces a
            terminal ``ask_user`` (matches fix-agent behaviour, one step
            higher since Smith has more inspection surface to walk).

    Returns:
        A dict with **exactly one** of ``diagnosis`` / ``answer`` /
        ``question`` / ``handoff`` populated (the terminal that fired),
        plus ``trace``::

            {
              "diagnosis": <Diagnosis>|None,
              "answer":    str|None,
              "question":  str|None,
              "handoff":   {"kind": "discovery"|"planner"|"refine",
                            "message": str}|None,
              "trace":     [{"tool", "args", "result_summary"}, …],
            }

        A caller can therefore branch on which key is non-None to pick
        the SSE event to emit (or, for handoff, delegate to the
        existing pipeline branch).
    """
    system_prompt = build_system_prompt()

    # ── Reward/punishment ledger (smith_outcomes) ─────────────────────────
    # Every mutating tool gets scored on execution; verifying tools score
    # the mutations that preceded them this turn. The scoreboard is
    # distilled into the playbook block injected below, so consequences
    # compound across turns. All calls are fail-open.
    from services import smith_outcomes as _outcomes
    _outcome_turn = _outcomes.next_turn_id(output_dir)
    _outcome_kind = _outcomes.classify_intent_kind(user_message)
    _turn_mutations: list[str] = []

    # Playbook injection — Smith reads his own ledger every turn.
    try:
        _playbook = _outcomes.render_playbook(output_dir)
        if _playbook:
            memory_block = _playbook + "\n" + (memory_block or "")
    except Exception:  # noqa: BLE001
        pass

    # Smith Auto-Act (S1) — prepend a "Current context" block to the memory
    # so Smith knows which page the user is looking at. When the user says
    # "change the Status field" and current_route is /candidates, this line
    # lets smith_decide's scoring (+50 route-match) resolve the ambiguity
    # without a punt. Silently no-op when current_route is None.
    if current_route:
        _route_line = f"<smith-current-context>\nCurrent page: {current_route}\n</smith-current-context>\n"
        memory_block = _route_line + (memory_block or "")

    # Prior turns are threaded as real chat messages so the model can
    # resolve follow-ups like "did you fix it?" natively — flattening
    # them into a bulleted memory block (the old path) breaks anaphora
    # because the LLM sees no prior assistant turn to continue from.
    # The current message follows this list, keeping the required
    # user/assistant alternation.
    messages: list[dict] = []
    if prior_messages:
        messages.extend(prior_messages)
    _initial = build_initial_user_message(user_message, recall_block, memory_block)
    if attachment_blocks:
        # Attachments ride in the SAME user turn as the ask — the model must
        # read "make the dashboard look like this" and the image together, not
        # as two separate turns it has to correlate. Text first so the
        # instruction frames the images rather than trailing them.
        messages.append({"role": "user",
                         "content": [{"type": "text", "text": _initial},
                                     *attachment_blocks]})
    else:
        # Plain string when there is nothing attached: identical to the
        # pre-attachment behaviour, so no existing turn changes shape.
        messages.append({"role": "user", "content": _initial})

    # Track user intent once — used by the answer terminal to refuse
    # fabricated "Done!" replies on mutation asks.
    user_wants_mutation = _is_mutation_intent(user_message)
    user_wants_deploy = _is_deploy_intent(user_message)

    # Default LLM boundary. When a `reasoning_callback` is provided AND the
    # caller didn't inject a custom `query_fn`, wrap `_default_query` so the
    # extra kwarg is threaded without changing the public QueryFn signature
    # (kept 3-arg for backward compat with injected test seams).
    if query_fn is not None:
        fn = query_fn
    elif reasoning_callback is not None:
        def _wrapped(system_prompt, messages, tool_catalog):  # noqa: ANN001
            return _default_query(
                system_prompt, messages, tool_catalog,
                reasoning_callback=reasoning_callback,
            )
        fn = _wrapped
    else:
        fn = _default_query
    # Phase 0 — scoped toolset. When the intent classifier had high
    # confidence, `scoped_tools` names the allowed subset. We filter
    # the catalog BEFORE the LLM sees it so the model can't be tempted
    # by wrong-domain tools. Dispatch also enforces the subset (see
    # `_scoped_tools_set` guard below) as defense in depth. `None`
    # keeps today's behaviour (full 39-tool catalog).
    _catalog = list(smith_tools.TOOL_CATALOG)
    if scoped_tools:
        _allowed = {str(t) for t in scoped_tools}
        _catalog = [t for t in _catalog if t.get("name") in _allowed]
    _scoped_tools_set: Optional[frozenset[str]] = (
        frozenset(str(t) for t in scoped_tools) if scoped_tools else None
    )
    stream = fn(system_prompt, messages, _catalog)
    trace: list[dict] = []
    diagnosis: Optional[dict] = None
    answer: Optional[str] = None
    question: Optional[str] = None
    handoff: Optional[dict] = None
    unknown_streak = 0
    seen_calls: set[str] = set()  # dedup key per read-only (tool, args)
    # Claude-Code-style file tools mutate disk inside the loop. Track
    # the paths so the caller can commit them + run post-generate fixes
    # after Smith reaches a terminal.
    edited_paths: list[str] = []
    # The structured ask-extraction Smith emitted via understand_ask.
    # The orchestrator uses it to relevance-check the resulting diff.
    understanding: dict | None = None
    # Retry-break: track failure count per (tool, target). When a mutating
    # tool fails N times in a row against the same target (e.g. edit_page
    # on /candidates/new keeps rejecting the LLM's output), we refuse
    # further attempts and inject an escalation hint. Without this the
    # LLM re-issues near-identical calls until the iteration cap and
    # Smith falls out to the canned "couldn't pin that down" reply.
    #
    # Keyed on (tool, target_key) — target_key is the argument that names
    # what's being edited (``path`` for edit_page / edit_file / read_page,
    # ``workflow_id`` for edit_workflow). Values: (count, last_reason).
    fail_counts: dict[tuple[str, str], tuple[int, str]] = {}
    _MAX_FAILURES_PER_TARGET = 2

    _VALID_HANDOFF_KINDS = {"discovery", "planner", "refine"}

    # Terminals aren't user-facing tool calls — Smith surfaces them via
    # the outer terminal event (message / propose_fix / handoff). Skipping
    # them from live progress avoids a duplicate/noisy chip right before
    # the actual answer arrives.
    _TERMINAL_TOOLS = frozenset({"propose_fix", "answer", "ask_user",
                                  "handoff_to_pipeline"})

    for step in _bounded(stream, max_iters):
        tool_name = str((step or {}).get("tool") or "").strip()
        args = (step or {}).get("args")
        if not isinstance(args, dict):
            args = {}

        # Live tool_start chip so the frontend renders progress BEFORE the
        # tool actually runs. Tools can take seconds (read_page on a big
        # schema, edit_workflow, etc); without this the chat looks frozen
        # while the model + dispatch chew. Terminals excluded (see set
        # above) — the outer terminal event covers those. Errors in the
        # callback never break the loop; the smith turn is authoritative.
        if progress_callback is not None and tool_name and tool_name not in _TERMINAL_TOOLS:
            try:
                progress_callback({
                    "phase": "tool_start",
                    "tool": tool_name,
                    "args": _trim_args(args),
                })
            except Exception:  # noqa: BLE001
                pass

        # Phase 0 — scoped-toolset defense-in-depth. If the classifier
        # picked a subset and the LLM somehow picks a tool outside it
        # (rare — the catalog it saw was already filtered — but possible
        # via hallucinated names), refuse politely and inject the
        # allowed set. Cheaper than a wrong-tool call landing.
        if (
            _scoped_tools_set is not None
            and tool_name
            and tool_name not in _scoped_tools_set
        ):
            trace.append({
                "tool": tool_name,
                "args": _trim_args(args),
                "result_summary": (
                    f"scoped: tool {tool_name!r} not in intent-scoped subset"
                ),
                "ran": False,
            })
            messages.append({
                "role": "tool",
                "tool": tool_name,
                "content": json.dumps({
                    "error": (
                        f"Tool {tool_name!r} is not available for the classified "
                        f"intent. Pick one of: {sorted(_scoped_tools_set)}. If "
                        "your ask actually needs a different tool, use "
                        "`ask_user` to say so."
                    ),
                }),
            })
            continue

        # ---- terminal: propose_fix -----------------------------------------
        if tool_name == "propose_fix":
            diag_raw = args.get("diagnosis")
            valid, err_msg, normalized = _validate_diagnosis(
                diag_raw, user_message, output_dir,
            )
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

        # ---- terminal: answer ---------------------------------------------
        if tool_name == "answer":
            text = args.get("text") or args.get("content") or args.get("message")
            if not isinstance(text, str) or not text.strip():
                trace.append({
                    "tool": tool_name,
                    "args": _trim_args(args),
                    "result_summary": "invalid answer: missing text",
                })
                messages.append({
                    "role": "tool",
                    "tool": tool_name,
                    "content": json.dumps({"error": "text must be a non-empty string"}),
                })
                continue
            unverified = _edits_without_matching_verify(trace)
            if unverified:
                trace.append({
                    "tool": tool_name,
                    "args": _trim_args(args),
                    "result_summary": f"answer refused: unverified edits {unverified}",
                })
                messages.append({
                    "role": "tool",
                    "tool": tool_name,
                    "content": json.dumps({
                        "error": (
                            f"You called {unverified} but did not call "
                            "verify_promise or run_guards after. Verify "
                            "your edit landed on disk before answering."
                        ),
                    }),
                })
                continue

            # Refuse to answer with confident "Done!" text when the user
            # asked for a mutation and NO mutating tool has been called
            # at all. This is the fabricated-answer failure mode: the
            # LLM decides the ask is trivial, skips edit_page, and just
            # writes "Removed the fields." No file ever changed.
            if user_wants_mutation:
                called_mutating = any(
                    (s.get("tool") or "") in _MUTATING_TOOLS for s in trace
                )
                if not called_mutating:
                    trace.append({
                        "tool": tool_name,
                        "args": _trim_args(args),
                        "result_summary": (
                            "answer refused: mutation ask with no mutating tool call"
                        ),
                    })
                    messages.append({
                        "role": "tool",
                        "tool": tool_name,
                        "content": json.dumps({
                            "error": (
                                "The user asked for a change to the app but you "
                                "haven't called any mutating tool (edit_page, "
                                "edit_workflow, add_page, remove_page, add_entity, "
                                "add_workflow, wire_form_to_workflow, or edit_file). "
                                "To add or change a section/component ON a page, use "
                                "edit_page. Either call the appropriate tool to make "
                                "the change and then verify, or, if you genuinely "
                                "cannot make it, call ask_user with a specific "
                                "question rather than fabricating a 'Done!' reply."
                            ),
                        }),
                    })
                    continue

            # Refuse to answer with a "please click Publish" style punt
            # when the user asked to deploy but NO effect tool (publish)
            # ran. Same class as the mutation guard, different verb set.
            # Fabricated failure narratives ("hit a transient loop
            # error") are the real-world tell we're catching here.
            if user_wants_deploy:
                called_effect = any(
                    (s.get("tool") or "") in _EFFECT_TOOLS for s in trace
                )
                if not called_effect:
                    trace.append({
                        "tool": tool_name,
                        "args": _trim_args(args),
                        "result_summary": (
                            "answer refused: deploy ask with no publish call"
                        ),
                    })
                    messages.append({
                        "role": "tool",
                        "tool": tool_name,
                        "content": json.dumps({
                            "error": (
                                "The user asked to deploy/publish/ship the "
                                "app but you have not called `publish`. Call "
                                "`publish(target='vercel')` — it returns "
                                "immediately with {ok: True, message: ...} "
                                "and runs the deploy in the background. "
                                "Relay the returned message verbatim in your "
                                "answer. Do NOT invent a 'transient error' "
                                "excuse or tell the user to click the button "
                                "themselves — that IS the same pipeline the "
                                "tool triggers."
                            ),
                        }),
                    })
                    continue

            # Claim-count guard — bind Smith's "Done! I did X, Y, Z"
            # reply to the ACTUAL change list from the last edit_page
            # call. If the answer enumerates more concrete claims than
            # the diff actually contains, we know at least some are
            # fabricated (the recruitment-app class: 5 claims, 2 real).
            # Refuse and inject the real change list back so the LLM
            # can rewrite honestly.
            overclaim = _answer_overclaims_edit(trace, text)
            if overclaim is not None:
                claim_count, change_count, change_list = overclaim
                trace.append({
                    "tool": tool_name,
                    "args": _trim_args(args),
                    "result_summary": (
                        f"answer refused: overclaim ({claim_count} claims, "
                        f"{change_count} real changes)"
                    ),
                })
                # Compact rendering of the actual changes for the LLM.
                sample = []
                for c in change_list[:12]:
                    kind = c.get("kind")
                    at = c.get("at", "?")
                    if kind == "text-changed":
                        sample.append(f"- text at {at}: {c.get('from')!r} → {c.get('to')!r}")
                    elif kind == "added":
                        sample.append(f"- added {at}")
                    elif kind == "removed":
                        sample.append(f"- removed {at}")
                    elif kind == "value-changed":
                        sample.append(f"- value at {at} changed")
                    else:
                        sample.append(f"- {kind} at {at}")
                if len(change_list) > 12:
                    sample.append(f"- (…{len(change_list) - 12} more)")
                messages.append({
                    "role": "tool",
                    "tool": tool_name,
                    "content": json.dumps({
                        "error": (
                            f"Your reply enumerates {claim_count} specific "
                            f"claims, but the last edit_page produced only "
                            f"{change_count} concrete change(s) on disk. Do "
                            "NOT overstate. Rewrite your answer using ONLY "
                            "the actual changes below — anything not in "
                            "this list did not happen, and you must either "
                            "retry the missing edits or tell the user which "
                            "ones didn't land.\n\nActual changes:\n"
                            + "\n".join(sample)
                        ),
                    }),
                })
                continue

            trace.append({
                "tool": tool_name,
                "args": _trim_args(args),
                "result_summary": "answer",
            })
            answer = text.strip()
            break

        # ---- terminal: handoff_to_pipeline --------------------------------
        if tool_name == "handoff_to_pipeline":
            kind = str(args.get("kind") or "").strip().lower()
            handoff_msg = args.get("message") or user_message
            if kind not in _VALID_HANDOFF_KINDS:
                trace.append({
                    "tool": tool_name,
                    "args": _trim_args(args),
                    "result_summary": f"invalid handoff kind: {kind!r}",
                })
                messages.append({
                    "role": "tool",
                    "tool": tool_name,
                    "content": json.dumps({
                        "error": f"kind must be one of {sorted(_VALID_HANDOFF_KINDS)}",
                    }),
                })
                continue
            if not isinstance(handoff_msg, str) or not handoff_msg.strip():
                trace.append({
                    "tool": tool_name,
                    "args": _trim_args(args),
                    "result_summary": "invalid handoff: empty message",
                })
                messages.append({
                    "role": "tool",
                    "tool": tool_name,
                    "content": json.dumps({"error": "message must be a non-empty string"}),
                })
                continue
            trace.append({
                "tool": tool_name,
                "args": _trim_args(args),
                "result_summary": f"handoff → {kind}",
            })
            handoff = {"kind": kind, "message": handoff_msg.strip()}
            break

        # ---- terminal: ask_user -------------------------------------------
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

        # Gate: `_confirmed` is only honoured when the SERVER can see that a
        # confirmation was actually requested and granted.
        #
        # It used to be an ordinary argument the model supplied, with nothing
        # recorded server-side that a prompt had ever been shown (register
        # S24-3) — so a single turn could emit a destructive call already
        # marked confirmed, and the "are you sure?" step never happened. The
        # two facts below both come from the conversation, not the model's
        # own claim: the previous assistant turn ended with OUR confirmation
        # prompt, and this turn's user message reads as a yes.
        if isinstance(args, dict) and args.get("_confirmed"):
            from services.confirmation_gate import (
                confirmation_was_requested,
                parse_confirmation_reply,
            )
            # `pending_confirmation` is the SERVER's own record that the
            # previous turn ended in a confirmation request. Checking only
            # the relayed prose made confirmation ungrantable whenever the
            # model paraphrased the summary — and nothing told it not to
            # (register S24-8), so `remove_page` and the newly-gated
            # `edit_workflow remove_step/rename` became unusable rather
            # than merely gated. The prose check stays as a fallback for
            # callers that pass no record.
            asked = bool(pending_confirmation) or confirmation_was_requested(prior_messages)
            replied = parse_confirmation_reply(user_message)
            if not (asked and replied == "yes"):
                args = {k: v for k, v in args.items() if k != "_confirmed"}
                logger.warning(
                    "smith_agent: stripped unsubstantiated _confirmed on %r "
                    "(server record=%s, prompt relayed=%s, user reply=%r) — "
                    "the tool will ask.",
                    tool_name, bool(pending_confirmation),
                    confirmation_was_requested(prior_messages), replied,
                )

        # Gate: any mutating tool call MUST be preceded by an
        # understand_ask this turn. Without it the orchestrator's
        # relevance gate can't verify the diff addressed the user's
        # ask, so we refuse the call and push Smith to extract intent
        # first. Bypass is only allowed if he already emitted a valid
        # understanding or the tool itself is understand_ask.
        if (
            tool_name in _MUTATING_TOOLS
            and understanding is None
            and tool_name != "understand_ask"
        ):
            trace.append({
                "tool": tool_name,
                "args": _trim_args(args),
                "result_summary": "mutation blocked: understand_ask required first",
                # NOT `ran: False`. The tool did not run, but a blocked
                # mutation must still gate `answer` — otherwise a refused
                # edit followed by "Done!" is a fabricated claim the loop
                # lets through. The old prose test skipped neither this
                # entry nor the duplicate-call one; the flag preserves
                # exactly which entries gate while removing the substring
                # test that a real edit's summary could trip (S24-2).
            })
            messages.append({
                "role": "tool",
                "tool": tool_name,
                "content": json.dumps({
                    "error": (
                        f"Refused to run {tool_name!r}: you must call "
                        "understand_ask FIRST so the orchestrator can "
                        "verify your diff against the user's actual ask. "
                        "Emit understand_ask with the VERB you mean and "
                        "that verb's fields \u2014 rename needs {screen, "
                        "element_label, current_behavior, "
                        "desired_behavior, target_file}, compose_route "
                        "needs {route}, add_widgets needs {route, "
                        "widgets} \u2014 then retry. Naming the wrong verb "
                        "is what makes a build request come back as "
                        "'nothing to change'."
                    ),
                }),
            })
            continue

        # ---- read-only tools ----------------------------------------------
        tool_fn = smith_tools.READONLY_HANDLERS.get(tool_name)
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
                        + ", ".join(t["name"] for t in smith_tools.TOOL_CATALOG)
                    ),
                }),
            })
            if unknown_streak >= _MAX_UNKNOWN_STREAK:
                question = (
                    "I'm not sure which part of the app you're asking about. "
                    "Could you tell me the screen you were on and what you "
                    "were trying to do?"
                )
                trace.append({
                    "tool": "ask_user",
                    "args": {"question": question, "forced": "unknown_tools"},
                    "result_summary": "forced ask_user after unknown tools",
                })
                break
            continue
        unknown_streak = 0

        # Retry-break: if this (tool, target) has already failed N times
        # this turn, refuse further attempts and force escalation. Keyed on
        # the TARGET, not the full args — the LLM often reruns the same
        # underlying operation with a slightly reworded ``intent`` string,
        # and per-arg dedup misses that. Prescribes the escalation path so
        # the LLM has an actionable next step rather than a dead end.
        target_key = _target_key_for(tool_name, args)
        if target_key is not None:
            fail_hist = fail_counts.get((tool_name, target_key))
            if fail_hist and fail_hist[0] >= _MAX_FAILURES_PER_TARGET:
                trace.append({
                    "tool": tool_name,
                    "args": _trim_args(args),
                    "result_summary": (
                        f"refused: {tool_name!r} on {target_key!r} already "
                        f"failed {fail_hist[0]}× — escalate"
                    ),
                    "ran": False,
                })
                messages.append({
                    "role": "tool",
                    "tool": tool_name,
                    "content": json.dumps({
                        "error": (
                            f"You already called {tool_name!r} on "
                            f"{target_key!r} {fail_hist[0]} times and it "
                            f"kept failing with: {fail_hist[1]!r}. "
                            f"DO NOT retry this seam on this target. "
                            f"Escalate: (a) `edit_file` for byte-level "
                            f"changes, (b) `propose_fix` with a "
                            f"diagnosis, or (c) `ask_user` to clarify. "
                            f"Retrying will be refused again."
                        ),
                    }),
                })
                continue

        # Dedup: if the SAME tool+args have been called before, don't waste
        # a turn (the live-run trace on a clean app showed Smith re-reading
        # the same page 6 times in a row). Push back with a hint so the
        # model picks something new or moves to a terminal.
        call_key = _canonical_call_key(tool_name, args)
        if call_key in seen_calls:
            trace.append({
                "tool": tool_name,
                "args": _trim_args(args),
                "result_summary": "duplicate call — result already in context",
            })
            messages.append({
                "role": "tool",
                "tool": tool_name,
                "content": json.dumps({
                    "error": (
                        f"you already called {tool_name!r} with the same "
                        f"args this turn — the result is above. Call a "
                        f"DIFFERENT tool or a terminal (propose_fix / "
                        f"answer / ask_user)."
                    ),
                }),
            })
            continue
        seen_calls.add(call_key)

        try:
            result = tool_fn(output_dir, args)
        except Exception as exc:  # noqa: BLE001 — a tool crash must not blow up the loop
            logger.exception("smith_agent: tool %s crashed", tool_name)
            result = {"error": f"tool crashed: {exc}"}

        # Retry-break bookkeeping: bump the per-target failure counter when
        # a mutating tool call didn't apply. Successful applies reset the
        # counter so a later legitimate retry (after Smith addresses the
        # error) isn't punished.
        if target_key is not None and isinstance(result, dict):
            applied = result.get("applied") is True or result.get("edited") is True \
                or result.get("success") is True
            reason = str(result.get("reason") or result.get("error") or "")[:200]
            key = (tool_name, target_key)
            if applied:
                fail_counts.pop(key, None)
            elif reason:
                prev = fail_counts.get(key, (0, ""))[0]
                fail_counts[key] = (prev + 1, reason)
        # Capture the structured ask-extraction the moment it succeeds;
        # the orchestrator reads it back to gate the resolved verdict.
        if (
            tool_name == "understand_ask"
            and isinstance(result, dict)
            and result.get("recorded") is True
            and isinstance(result.get("understanding"), dict)
        ):
            understanding = result["understanding"]

        # Track successful direct-edit writes so the caller can commit +
        # heal the app once Smith terminates. Two return-shape families:
        #  * edit_file: {edited: bool, path: str}
        #  * specialist seams (edit_page, edit_workflow, add_page, etc.):
        #    {applied: bool, edited_paths: [str, ...]}
        if isinstance(result, dict):
            if tool_name == "edit_file" and result.get("edited") is True:
                p = result.get("path")
                if isinstance(p, str) and p and p not in edited_paths:
                    edited_paths.append(p)
            elif result.get("applied") is True:
                for p in (result.get("edited_paths") or []):
                    if isinstance(p, str) and p and p not in edited_paths:
                        edited_paths.append(p)
                # edit_workflow returns {success, path} instead of
                # {applied, edited_paths}; fold it in as well.
                p = result.get("path")
                if isinstance(p, str) and p and p not in edited_paths:
                    edited_paths.append(p)
            elif tool_name == "edit_workflow" and result.get("success") is True:
                p = result.get("path")
                if isinstance(p, str) and p and p not in edited_paths:
                    edited_paths.append(p)
        # A tool asking for confirmation is recorded structurally, not left
        # for prose-matching on whatever the model relays (register S24-8).
        if (
            isinstance(result, dict)
            and result.get("status") == "needs_confirmation"
        ):
            _trace_entry_pending = {
                "kind": result.get("kind"),
                "target": result.get("target"),
                "cascade": bool(result.get("cascade")),
            }
        else:
            _trace_entry_pending = None
        _trace_entry = {
            "tool": tool_name,
            "args": _trim_args(args),
            "result_summary": _summarize_result(result),
        }

        # ── Score this tool call in the outcome ledger ────────────────────
        try:
            _res_err = isinstance(result, dict) and (
                bool(result.get("error"))
                or any(result.get(k) is False
                       for k in ("applied", "edited", "ok"))
            )
            if tool_name in _MUTATING_TOOLS:
                _outcomes.record_outcome(
                    output_dir, tool=tool_name,
                    signal="apply_error" if _res_err else "apply_ok",
                    intent_kind=_outcome_kind, intent_text=user_message,
                    evidence=_summarize_result(result)[:200],
                    turn=_outcome_turn)
                if not _res_err:
                    _turn_mutations.append(tool_name)
            elif tool_name in _VERIFYING_TOOLS and _turn_mutations:
                _v_fail = _res_err or (
                    isinstance(result, dict)
                    and any(result.get(k) is False
                            for k in ("passed", "ok", "green", "kept"))
                )
                for _mt in dict.fromkeys(_turn_mutations):
                    _outcomes.record_outcome(
                        output_dir, tool=_mt,
                        signal="regression" if _v_fail else "verified",
                        intent_kind=_outcome_kind, intent_text=user_message,
                        evidence=f"{tool_name}: {_summarize_result(result)[:160]}",
                        turn=_outcome_turn)
        except Exception:  # noqa: BLE001 — ledger must never break the loop
            pass
        if _trace_entry_pending:
            _trace_entry["needs_confirmation"] = _trace_entry_pending
        # Stash the concrete change list from edit_page so the
        # answer-terminal overclaim guard can compare Smith's numbered
        # reply to what actually landed on disk. Kept off the sub_trace
        # projection above because this is data, not display.
        if (
            tool_name == "edit_page"
            and isinstance(result, dict)
            and isinstance(result.get("changes"), list)
        ):
            _trace_entry["changes"] = result["changes"]
        # Sub-agent trace forwarding (slice 3) — when Smith called
        # ``_tool_app_modifier`` the result carries the modifier's own
        # per-step trace. Preserve a compact projection so the outer
        # SSE emitter can render each inner Read/Bash/Edit/Write as
        # its own ``smith_thought`` chip (prefixed with `↳ ` in the
        # streamer). Also folds edited_paths from files_touched.
        if isinstance(result, dict) and isinstance(result.get("trace"), list):
            _trace_entry["sub_trace"] = [
                {"tool": (s or {}).get("tool"),
                 "summary": ((s or {}).get("result_summary") or "")[:280]}
                for s in result["trace"] if isinstance(s, dict)
            ]
            for ft in (result.get("files_touched") or []):
                fp = (ft or {}).get("path")
                if isinstance(fp, str) and fp and fp not in edited_paths:
                    edited_paths.append(fp)
        trace.append(_trace_entry)
        messages.append({
            "role": "tool",
            "tool": tool_name,
            "content": _serialize_for_llm(result),
        })
    else:
        # Iteration cap hit without a terminal call — build an INFORMED
        # question from grounding data + Smith's trace instead of the
        # generic apology. If grounding found an entity we can enumerate
        # its pages; otherwise we show what Smith tried so the user can
        # steer him.
        question = _build_informed_scope_question(
            user_message, output_dir, trace,
        )
        trace.append({
            "tool": "ask_user",
            "args": {"question": question, "forced": "iteration_cap"},
            "result_summary": "forced ask_user at iteration cap",
        })

    return {
        "diagnosis":    diagnosis,
        "answer":       answer,
        "question":     question,
        "handoff":      handoff,
        "trace":        trace,
        # New — Claude-Code-style direct edits Smith made this turn.
        # The caller commits + runs post-generate fixes when non-empty.
        "edited_paths": list(edited_paths),
        # New — the structured ask-extraction, if Smith ran one. Used
        # by the orchestrator's relevance gate.
        "understanding": understanding,
        # The confirmation a tool asked for this turn, as a SERVER-side
        # record. The caller persists it on the assistant message and hands
        # it back as `pending_confirmation` next turn, so a granted "yes"
        # works whether or not the model relayed the prompt verbatim
        # (register S24-8). None when nothing is pending.
        "pending_confirmation": _pending_confirmation_from(trace),
    }


# --------------------------------------------------------------------------- #
# System prompt + initial user message
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = (
    "You are Smith — Tentoro Forge's conversational build assistant. You "
    "are the single entry point for every user turn on this platform. Your "
    "FIRST job is to correctly identify what the user wants and route "
    "accordingly. There is no pre-classifier — you decide.\n\n"
    "BLUEPRINT IS PRIMARY REFERENCE.\n"
    "  The app's BLUEPRINT.md (rendered inside <smith-memory> as \"## App "
    "blueprint\") is your primary reference. Read it FIRST when planning "
    "any action — entities, pages, workflows, forms, navigation, and "
    "design decisions are all captured there and kept current by the "
    "platform. If a downstream file contradicts the blueprint, the "
    "blueprint is authoritative — reconcile the file to match, not the "
    "other way around. Cite the blueprint section you consulted when "
    "answering.\n\n"
    "TOP PRIORITY — ROUTE MUTATIONS BY ARTIFACT SHAPE.\n"
    "  The right tool depends on WHAT the ask touches, not just WHETHER "
    "it's a mutation. Structured artifacts (page schemas, workflow "
    "JSON, entities) have deterministic appliers that read+patch+write "
    "for you — do NOT hand-edit their bytes.\n\n"
    "  Ask class                                 → Preferred FIRST tool\n"
    "  -----------------------------------------    -------------------------------\n"
    "  Modify a field, prop, label, control on   → edit_page(path, patch)\n"
    "    an existing page (e.g. \"CV upload\n"
    "    should be a FileUpload not a dropdown\")\n"
    "  Add a section/component to a page         → edit_page(path, patch)\n"
    "  Remove a field/section from a page        → edit_page(path, patch)\n"
    "  Fix a wrong menu/sidebar label or the     → edit_file(src/schemas/shell.json)\n"
    "    page it opens to (e.g. \"Recruiters       (find SideNav.props.groups[].items[]\n"
    "    menu shows Users page\")                   and change label or route). Also\n"
    "                                              consider src/contracts/nav-flow.json\n"
    "                                              if the menu label matches a page id.\n"
    "  Add a whole FEATURE (entity + list page +  → plan_and_apply(ask)\n"
    "    create page + workflow + wiring, e.g.       — ONE call, ONE plan, ONE progress\n"
    "    'add candidate messaging')                  stream. Do NOT call add_entity +\n"
    "                                                add_page + add_workflow separately\n"
    "                                                for a feature ask — the LLM turn\n"
    "                                                overhead is 5x higher and the\n"
    "                                                layman sees a jerky 5-message flow.\n"
    "  Add a brand-new whole page                → add_page(archetype, entity, route)\n"
    "  Modify a workflow's trigger/steps/config  → edit_workflow(workflow_id, changes)\n"
    "  Add a new workflow                        → add_workflow(op, entity, name?)\n"
    "  Wire an EXISTING form to an EXISTING      → wire_form_to_workflow(page_route,\n"
    "    workflow (retrofit an orphan workflow;    workflow_name, field_map?)\n"
    "    connect a manually-authored form to a\n"
    "    workflow) — deterministic, no LLM\n"
    "  Add a new entity + CRUD slice             → add_entity(name, fields, table?)\n"
    "  Author a BUSINESS RULE (server-enforced   → create_business_rule(name, rule_type,\n"
    "    data logic on all writes: 'reject X',      model_name?, field_name?, config)\n"
    "    'require Y', 'compute Z = ...', validation,\n"
    "    guards, decision tables). Persists to the\n"
    "    Rules editor + ships instantly. NOT the\n"
    "    same as set_field_interaction — that is a\n"
    "    single form field's reactive UI; a business\n"
    "    rule guards/derives the DATA model-wide.\n"
    "  Reactive UI for ONE form field            → set_field_interaction(page, field,\n"
    "    (cascade dropdown, autofill-on-change,      interaction)\n"
    "    show/hide a field)\n"
    "  Fix code/config OUTSIDE the schema        → _tool_app_modifier({ask: <verbatim>})\n"
    "    surface — TS runtime code, next.config,\n"
    "    .env.local, tsconfig, package.json,\n"
    "    vendored /packages files, wiring bugs\n"
    "    the seams can't reach\n"
    "  WHOLE-APP replan / pivot                  → handoff_to_pipeline(kind=\"refine\")\n"
    "    (rip out auth, convert to a marketplace, etc — NEVER for a\n"
    "     feature-add; those go to add_entity + add_page above)\n\n"
    "For schema/workflow/entity mutations you MUST use the seam above. "
    "The seam's applier is deterministic — it reads the current JSON, "
    "applies your patch atomically, validates, and writes. That is why "
    "these seams succeed where hand-crafted Edits fail: no anchor "
    "hunting, no old_string mismatches, no partial writes.\n\n"
    "ANSWERS ARE BOUND TO EDITS — CLAIM ONLY WHAT THE DIFF PROVES.\n"
    "  Every ``edit_page`` result carries a structured ``changes`` "
    "array — the exact list of concrete facts that differ between the "
    "old and new schema. When you write an ``answer`` describing what "
    "you did (a 'Done! I fixed 1, 2, 3, …' reply), each numbered / "
    "bulleted item MUST correspond to at least one entry in that "
    "``changes`` array. Do NOT enumerate things you PLANNED to change "
    "but that never appeared in the diff. If the diff has 2 changes and "
    "you planned 5, either (a) call ``edit_page`` again with the "
    "missing intent, or (b) tell the user honestly that 3 of the 5 "
    "asks didn't take effect and ask if they want you to retry.\n"
    "  Rule of thumb: read your own answer top-to-bottom, and for each "
    "specific claim ask 'is this in the last edit_page changes[]?' — "
    "if any claim can't be pointed at a concrete change entry, revise "
    "the answer before calling ``answer``.\n\n"
    "`_tool_app_modifier` is the ESCAPE HATCH — reserve it for asks the "
    "schema-aware seams can't reach (code files, config files, "
    "cross-cutting fixes that touch multiple non-schema artifacts).\n\n"
    "Examples:\n"
    "  • \"CV upload should be FileUpload, not dropdown\" → "
    "edit_page (page schema mutation).\n"
    "  • \"Add a Recruiters page\"                        → add_page.\n"
    "  • \"Add the recruiter feature\" (feature-add)      → sequence of\n"
    "    add_page (list) + add_page (create) + add_page (detail) +\n"
    "    add_page (edit), ONE per turn. NOT handoff_to_pipeline —\n"
    "    the refiner will drop action rows and mis-type fields.\n"
    "  • \"The Save button isn't working\"                → INVESTIGATE "
    "with list_pages+read_page; if it's a schema issue → edit_page; "
    "if the workflow is broken → edit_workflow; only if the fix "
    "needs code changes → _tool_app_modifier.\n"
    "  • \"Update next.config to enable SSR streaming\"   → "
    "_tool_app_modifier (config file, not schema).\n\n"
    "INTENT ROUTING (read the message + <smith-memory> + recall, then pick):\n\n"
    "  A. GREETING / META (\"hi\", \"who are you?\", \"what can you do?\", \"help\")\n"
    "     → `answer(text)`. Warm, short (2-3 sentences). Introduce yourself, "
    "then ask what they want to build or change based on whether the recall "
    "shows an existing app. Do NOT call inspection tools first — that makes "
    "you feel slow on a greeting.\n"
    "     • Fresh project: 'Hi! I'm Smith — your build partner here. Tell "
    "me what you'd like to build (a patient management system, a project "
    "tracker, an inventory app…) and I'll draft a plan we can iterate on.'\n"
    "     • Existing app: 'Hey! I can see your app is up. What would you "
    "like to change — a workflow, a page, or a bug you're seeing?'\n\n"
    "  B. NEW-APP DESCRIPTION (\"Build me an X\", \"I want an app that…\")\n"
    "     on a project with NO existing entities/pages in recall.\n"
    "     → `handoff_to_pipeline(kind=\"discovery\", message=<user text>)`.\n"
    "     The discovery agent researches the domain, then the planner "
    "produces a plan the user can approve. That flow is battle-tested — "
    "you defer to it. Do NOT try to author the plan yourself.\n\n"
    "  C. FIX A BROKEN FEATURE (\"X is not working\", \"click Y and nothing "
    "happens\", pasted error) → INVESTIGATE with read-only tools, then "
    "`propose_fix(diagnosis)` when you have a real seam target. If your "
    "seams can't reach the fix (missing API route, wrong Next config, "
    "code-level bug), fall back to "
    "`handoff_to_pipeline(kind=\"refine\", message=<symptom>)` — the "
    "code-editing refiner has a broader surface than propose_fix.\n\n"
    "  D. EXPLAIN / DISCUSS (\"how does X work?\", \"why is Y designed "
    "that way?\") → INVESTIGATE briefly if needed, then `answer(text)`. "
    "Short and specific.\n\n"
    "  E. CONTINUATION AFTER A PARTIAL APPLY — memory will show a recent "
    "`applied change` line saying the previous fix left N issues remaining. "
    "A short follow-up like \"yes please\", \"yes take another look\", "
    "\"try again\" means \"continue investigating the SAME feature\" — "
    "re-diagnose with the residual context in mind. Do NOT ask the user "
    "which screen; memory already tells you.\n\n"
    "  F. GENUINELY AMBIGUOUS (you can't tell A-E even after inspection) "
    "→ `ask_user(question)`. One focused question.\n\n"
    "GENERAL RULES:\n"
    "- ONE tool call per turn. When you have enough evidence, call the "
    "right terminal.\n"
    "\n"
    "DIRECT-EDIT MODE (Claude-Code-style — preferred for targeted "
    "byte-level edits like \"rename a field\", \"remove a widget\", "
    "\"tweak a label\"):\n"
    "  1. `read_file(path)` on the target file to see the LITERAL bytes.\n"
    "     Do NOT rely on `read_page` for edits — it returns a "
    "structural summary, not the actual text on disk, so its strings "
    "may not match what edit_file wants.\n"
    "  2. `edit_file(path, old_string, new_string)` with an old_string "
    "that appears EXACTLY ONCE in the file. If the tool complains the "
    "match is ambiguous, add surrounding lines to old_string and "
    "retry.\n"
    "  3. `verify_promise(path, claim)` where claim is your original "
    "intent (\"the password field is removed\", \"a status dropdown "
    "was added\"). If verify returns kept:false, don't answer \"Done\" "
    "— go back to step 2 and try again.\n"
    "  4. `answer(text)` ONLY once verify_promise passes. The router "
    "auto-commits your edited files + runs the app's health checks.\n"
    "For MULTI-STEP edits (rename + add a field): chain edit_file "
    "calls, then verify each with a scoped claim.\n"
    "\n"
    "SEAM MODE (structured propose_fix — use when the change is a "
    "known pattern the platform's own builders can regenerate, or when "
    "the user asked for something that spans multiple files atomically):\n"
    "- For workflow-value changes: seam=workflow_node_config; "
    "patch=`{\"values\": {…full corrected values map…}}`.\n"
    "- For page/component EDITS on an existing page: seam=page_schema_patch; "
    "patch is a list of RFC-6902 ops. Verify component names via "
    "`list_components`.\n"
    "- For ADDING A WHOLE NEW PAGE: seam=add_page; artifact.kind=\"page\"; "
    "artifact.path=the intended schema path (e.g. `src/schemas/pipeline.json`); "
    "patch is a dict of SEAM PARAMETERS the applier feeds to the pipeline's "
    "own deterministic builders — NOT hand-authored JSON. Shape:\n"
    "     {\n"
    "       \"archetype\": one of {list, form, create, edit, detail, kanban, calendar},\n"
    "       \"entity\":    the primary bound entity name from recall,\n"
    "       \"route\":     starts with '/',\n"
    "       \"title\":     display title (optional),\n"
    "       \"features\":  optional hints like [\"groupBy:stage\"] for kanban\n"
    "     }\n"
    "   Use add_page WHEN: `list_pages` shows no matching page for the ask AND\n"
    "   the ask reads as an IA-level 'add a whole page' request. Prefer\n"
    "   page_schema_patch when the ask is 'add a SECTION to page X'.\n"
    "- Bind ONLY to resources you can see via a tool. Never invent an "
    "entity, column, workflow id, or component name.\n"
    "- `explanation` reads as a PROPOSAL (\"will be…\", \"proposes to…\"), "
    "not an accomplished change — the user clicks Apply to commit.\n"
    "- NEVER apply a fix yourself. propose_fix streams a card; the router "
    "handles apply on the follow-up [APPLY_FIX] chip.\n\n"
    "Use `ask_user(question)` only when the request is genuinely ambiguous "
    "or you cannot localize what to look at. Never guess.\n\n"
    "MEMORY: the `<smith-memory>` block below carries prior turns and a "
    "state summary (pending fixes, applied changes). READ IT before acting. "
    "If the state shows a `pending fix` you already proposed and the user is "
    "confirming (\"yes\", \"apply it\", \"go\"), do NOT re-diagnose — the "
    "router handles the apply for you. In that case, `answer` with a short "
    "acknowledgement and stop; the frontend will confirm the apply.\n\n"
    "RECALL: the `## App recall` block describes the app's ENTITIES, ROLES, "
    "workflows, and recent commits. Bind ONLY to resources you can see here "
    "or via a tool call. Never invent an entity, column, workflow id, or "
    "component name — call `list_components` when in doubt about what "
    "components are available.\n\n"
    "Diagnosis contract (for propose_fix):\n"
    "  {\n"
    "    \"feature\": <what feature this touches>,\n"
    "    \"rootCause\": <the precise defect or thing the user wants changed>,\n"
    "    \"artifact\": {\"kind\": \"workflow\"|\"page\"|\"schema\", \"path\": <rel path>},\n"
    "    \"locator\": {\"nodeId\": <workflow node id | null>, \"jsonPointer\": <RFC-6901 | null>},\n"
    "    \"proposedFix\": {\n"
    "       \"seam\": \"workflow_node_config\"|\"page_schema_patch\"|\"code_edit\",\n"
    "       \"patch\": <object for workflow_node_config / list of RFC-6902 ops for page_schema_patch>\n"
    "    },\n"
    "    \"confidence\": <0..1>,\n"
    "    \"explanation\": <plain-language for the end user — what will change AFTER Apply>\n"
    "  }\n\n"
    "Rules:\n"
    "- One tool call per turn. When you have enough evidence, call the right terminal.\n"
    "- For a workflow-value change: seam=workflow_node_config; "
    "patch=`{\"values\": {…full corrected values map…}}` — rebind wrong "
    "literals to `{{input}}` bindings; drop columns you can't safely correct.\n"
    "- For a page/component change: seam=page_schema_patch; patch is a "
    "list of RFC-6902 ops. Verify component names via `list_components` first.\n"
    "- Use code_edit only as a last resort.\n"
    "- `explanation` must read as a PROPOSAL (\"will be…\", \"proposes to…\"), "
    "not as an accomplished change — the user still has to click Apply.\n\n"
    "COMMON page_schema_patch PATTERNS (call list_pages then read_page first):\n\n"
    "  1. Append a component to a page's content array:\n"
    "     [{\"op\": \"add\", \"path\": \"/content/-\",\n"
    "       \"value\": {\"type\": \"Tag\", \"props\": {\"label\": \"Active\", \"tone\": \"positive\"}}}]\n\n"
    "  2. Insert a component at a specific index (index 0 = first child):\n"
    "     [{\"op\": \"add\", \"path\": \"/content/0/children/2\",\n"
    "       \"value\": {\"type\": \"Kanban\", \"props\": {\"dataSource\": \"applications\", \"groupBy\": \"stage\"}}}]\n\n"
    "  3. Change a prop on an existing component (target by jsonPointer):\n"
    "     [{\"op\": \"replace\", \"path\": \"/content/1/props/label\", \"value\": \"Schedule assessment\"}]\n\n"
    "  4. Remove a component:\n"
    "     [{\"op\": \"remove\", \"path\": \"/content/3\"}]\n\n"
    "The jsonPointer paths reflect the READ_PAGE output — always read the page "
    "first so your paths are correct. `props.dataSource` for tables/charts must "
    "name a real entity slug from `recall`.\n"
)


_ROUTING_RULES = """
SCAN FIRST, ACT SECOND — you are the Smith ARCHITECT. You authored
this app; you know the entities, pages, workflows exist, but you do
NOT know the current content of any file from memory alone. Read
before you speak. NEVER answer "the current state already matches"
without having read the file — that phrase, unverified, is a lie.

REASONING ORDER (do these in ORDER, not in parallel):
  read → understand → confirm-scope-if-ambiguous → act → verify
NEVER "guess-and-edit" — every wrong-file edit costs the user two turns
to notice + one to revert.

For every ask that references something the user can see on a screen
(a field label, a button, a component type, a page name):

  1. `think(thought)` — parse in plain language: what SCREEN, what
     ELEMENT (by visible label), current vs desired. `think` is your
     scratchpad and persists across the turn.

  2. LOCATE THE ARTIFACT(S) via scan tools. In order of preference:
       - User named an entity or feature phrase ("recruitment drive",
         "candidate profile", "the drives page") → `find_resources(query)`
         FIRST. One call returns EVERY page, workflow, and FK dependent
         for that entity. If the incoming message already has a
         "## Grounding" block naming the matched entity (CTX-2 pre-groun-
         ded it), the entity is decided — proceed to step 3 with the
         graph slice, do not re-hunt.
       - User named a visible label → `grep_schemas(pattern)` with the
         label text; e.g. "CV Upload", "Approve button", "Total". The
         previews tell you which file to open.
       - User named a screen ("Add Candidate") → `list_pages` to find
         the route(s) whose path or route matches the wording, THEN
         `read_page` on the winner.
       - User asked about a component ("the dropdown", "the Kanban") →
         `find_component(name)` to enumerate every usage.
     Skipping this step is what makes Smith look like a chatbot. Do
     NOT skip it.

  2a. PICK CONFIDENTLY. You are an LLM — use your judgment. When you
     can identify one candidate you're reasonably confident about, act
     on it. Signals that add up to "confident":
       - User's phrase resembles the route ("New Retailer" → /admin/retailers/new).
       - <smith-current-context> names the same route.
       - <smith-recent-edits> lists the same route.
       - Only one page has the referenced element.
       - The ask names a specific route path.
     Say the pick in ONE line at the start of your work ("Editing
     /admin/retailers/new — the New Retailer form."), then proceed.
     Do NOT enumerate the other candidates as a picker when you
     already know which one it is — that's a chatbot move.

     Only fall back to `ask_user` when candidates truly look
     interchangeable (e.g., "fix the Status column" and the label
     appears on 3 unrelated pages with no route/context signal).
     When you must ask, enumerate the concrete matches with your
     best guess called out — never the generic "which screen?".

     Optional escape hatch: `resolve_target(query, current_route?,
     recent_edits?)` returns a scored decision (act / act_all / chip /
     ask). Call it when you genuinely want a second opinion; skip it
     when you already know the answer.

  3. `read_page` (or `read_workflow` / `read_file`) on the file you
     located, so you see the actual current state. THIS is where
     "matches" or "does not match" is decided — not from memory.

  4. `understand_ask({screen, element_label, current_behavior,
     desired_behavior, target_file})` with your structured extraction.
     The orchestrator's RELEVANCE GATE will refuse to mark you
     'resolved' unless your final diff touches `target_file` AND
     mentions `element_label` verbatim.

  5. Pick a mutating tool. Mutating tools are refused until
     understand_ask has been called this turn.

FOR "ADD" ASKS ("add screens for interviewers", "add the recruiter
feature", "add auth") — YOU are the builder-caller. The composite
seams (`add_entity`, `add_page`, `add_workflow`) are deterministic:
they read the registry, invoke the platform's own field-model /
schema builders (same code the initial generation used), write the
files, update `nav-flow.json` + registries, and produce forms with
submit buttons, workflow bindings, action rows. They cannot fail
silently the way a free-form refiner call can.

RULES:
  * NEVER call `handoff_to_pipeline(kind="refine")` for a feature-add
    the seams can reach. The refiner drops action rows, mis-types
    fields, and skips workflow wiring — the seams do not.
  * ALWAYS call `list_entities`, `list_pages`, `list_workflows`
    FIRST — you must know what to reuse vs. what to author.
  * DECOMPOSE the ask into: which entity? which pages (list / new /
    [id] / [id]/edit)? which workflows (create / update / delete)?
    Every real feature is 1 entity + 3-4 pages + 2-3 workflows.
  * PROPOSE the full slice in a single `think`, then ONE `ask_user`
    for approval — not one question per decision.
  * On approval, fan out to `add_entity` → `add_workflow` × N →
    `add_page` × N in dependency order. Each seam call is self-
    contained; you don't need to hand-wire anything between them.

WORKED EXAMPLE — user asks "add the feature to add recruiter":

  Turn 1: `think` — Recruiter is a User with role='recruiter'. If
     `list_entities` shows User already exists, reuse it. Otherwise
     add a User entity. Pages needed: /recruiters (list), /recruiters/new
     (create form), /recruiters/[id] (detail), /recruiters/[id]/edit
     (edit form). Workflows: CreateUser, UpdateUser (add if missing).
  Turn 2: `list_entities` — confirm User + which columns.
  Turn 3: `list_workflows` — confirm CreateUser + UpdateUser exist.
  Turn 4: `ask_user` — "I'll add a Recruiters area: a list page, a
     create form, a detail page, and an edit form — all wired to
     the existing User entity and its CreateUser / UpdateUser
     workflows. OK to proceed?"
  Turn 5 (on yes): `add_page({archetype: "list",   entity: "User", route: "/recruiters"})`
  Turn 6:          `add_page({archetype: "create", entity: "User", route: "/recruiters/new"})`
  Turn 7:          `add_page({archetype: "detail", entity: "User", route: "/recruiters/[id]"})`
  Turn 8:          `add_page({archetype: "edit",   entity: "User", route: "/recruiters/[id]/edit"})`
  Turn 9: `answer` — the shell menu sync + guards run automatically;
     tell the user which routes were added.

  NOT this: one `handoff_to_pipeline(kind="refine", message="add
  recruiter")` call. That hands the ask to a black-box builder that
  will produce forms without action rows.

ESCAPE HATCH — `_tool_app_modifier` for code/config edits only.

  ``_tool_app_modifier`` is a sub-agent that runs a sandboxed
  Read/Bash/Edit/Write loop. Use it ONLY when the ask touches
  something the schema-aware seams can't reach:

    - Runtime TS/TSX code under src/lib/, src/app/
    - .env.local / next.config / tsconfig / package.json
    - Vendored packages/ files
    - Cross-cutting fixes that span multiple non-schema files

  NEVER call it for page schemas, workflows, or entities — the
  schema-aware seams (`edit_page`, `edit_workflow`, `add_page`,
  `add_workflow`, `add_entity`) do a deterministic JSON-Patch apply
  and land in 1 call. The modifier's byte-level Edit is fragile on
  structured JSON and wastes iterations hunting for anchors.

  When to call it (code/config only):
    _tool_app_modifier({"ask": "<user's request VERBATIM>"})

ROUTING RULES — pick the specialist that OWNS the artifact before reaching
for edit_file. edit_file is a last-resort primitive; direct string edits on
schema / workflow JSON are the exact operation that drift-tracks itself into
"believes-he-did-it" answers.

  Ask class                                    → Preferred tool
  -----------------------------------------    -------------------------------
  Change a form/page field's TYPE, PROPS,      edit_page(path, patch)
    LABEL, or props on an existing page
  Modify an existing workflow's trigger        edit_workflow(workflow_id,
    inputs, step config, or connectivity        changes)
  Add a brand-new whole page                   add_page(archetype, entity,
                                                 route)
  Add a brand-new workflow                     add_workflow(op, entity, name?)
  Add a new entity + schema + starter tables   add_entity(name, fields, table?)
  User wants a WHOLE NEW APP, or a scope-      handoff_to_pipeline(kind=
    changing pivot ("rip out auth and rebuild     "planner"|"refine")
    with SAML", "convert this to a marketplace") — a genuine
    replan, not a feature-add. Feature-adds route to add_entity /
    add_page / add_workflow above, NEVER here.
  Change .env.local / other config file        edit_file(path, ...)
  Runtime .ts / .tsx code under src/lib/**     edit_file  (last resort)

BEFORE editing anything, call impact_analysis(target) on the artifact the
user's ask centers on. Its output tells you EVERY page / workflow / api /
contract / env-var that will need to change together. Route each impacted
artifact to the specialist that owns it. If you skip impact_analysis, you
will miss the cascade and the guard suite will keep failing.

AFTER editing, call run_guards() (or wait for the orchestrator to invoke
it). If any guard is red, DO NOT answer — parse the failure, route to the
correct specialist, and edit again. Only answer once guards are green.

VERIFY BEFORE REPORTING SUCCESS (SMITH-VERIFY):
  * After every edit, `read_page` / `read_file` the touched file and CONFIRM
    the intent landed. A tool result saying `applied=true` is a promise, not
    a proof — the specialist may have written a different node than you
    thought. If the readback doesn't show your change, DO NOT report
    resolved — either retry or downgrade to partial (below).

HONEST STATUS REPORTING — three shapes, pick the one that's true:
  * **Fully resolved**: file was edited, readback confirms the intent, and
    (when applicable) guards are green. Say "Done. Changed X — before/after
    summary."
  * **Partially resolved**: you fixed part of what the user asked but not
    all. Say what you fixed, what remains, and WHY (e.g. "Fixed the Status
    dropdown on /drives/new. The same field on /drives/[id]/edit needs the
    same fix — want me to do that too?"). This is more useful than a false
    'resolved' the user will re-open in 30 seconds.
  * **Systemic — needs source fix**: `find_source_generator(symptom)`
    returned `propose_source_fix`. Rather than editing N pages in place, say
    "This affects M pages across the app because the generator at
    <module>::<function> emits it that way. Editing here would regress on
    the next generation. Want me to (a) fix all N places in-app and flag
    the source module as a follow-up task, or (b) leave it for a source-
    code fix?" — let the user choose scope.

SYSTEMIC-BUG CHECK (SMITH-SOURCE-1):
  Before making a 3rd in-place edit of the SAME class of bug in one turn,
  call `find_source_generator(symptom)`. If `recommendation ==
  "propose_source_fix"`, stop editing and offer the systemic option — the
  user paying twice for N pages that regenerate on the next gen is worse
  than one honest "this is a source bug" message.
"""


def build_system_prompt() -> str:
    """The system prompt with the routing rules + live TOOL_CATALOG
    appended so tool names, signatures, and descriptions stay in sync
    with :mod:`services.smith_tools` without a manual copy."""
    lines = [
        f"- {t['name']}({_sig_args(t['signature'])}): {t['desc']}"
        for t in smith_tools.TOOL_CATALOG
    ]
    return (
        SYSTEM_PROMPT
        + "\n" + _ROUTING_RULES
        + "\n" + _confirmation_rules()
        + "\nTOOL PALETTE:\n" + "\n".join(lines)
    )


def _confirmation_rules() -> str:
    """How to relay a ``needs_confirmation`` tool result.

    S24-3 made ``_confirmed`` server-derived: it is honoured only when
    :func:`confirmation_gate.confirmation_was_requested` can see OUR exact
    marker sentence in the previous assistant turn. That is the right shape —
    the model can no longer assert its own permission — but nothing ever told
    the model to emit that sentence, so the condition could not become true
    and every destructive operation was permanently unconfirmable (register
    S24-8). A gate nobody can pass is not a safe gate; it is a broken feature
    that looks like a safe one.

    The marker is OUR string, produced by :func:`build_impact_summary`, so
    relaying ``.summary`` unchanged is all that is required.

    Imported lazily, like the gate call in :func:`_gate_tool_call`, because
    ``services.confirmation_gate`` pulls in the tool layer.
    """
    from services.confirmation_gate import CONFIRMATION_PROMPT_MARKER

    return (
        "\nCONFIRMATION (destructive operations):\n"
        'When a tool returns {"status": "needs_confirmation", ...}:\n'
        "  1. Do NOT call the tool again in the same turn, and do NOT set "
        "_confirmed.\n"
        "  2. Reply to the user with the tool's `summary` field **verbatim** — "
        "copy it exactly, including the final line\n"
        f'     "{CONFIRMATION_PROMPT_MARKER}"\n'
        "     That sentence is how the server records that you actually asked. "
        "If you paraphrase it, the user's\n"
        "     \"yes\" cannot be honoured and the operation can never proceed.\n"
        "  3. Then stop and wait. On the NEXT turn, if the user agreed, "
        "re-issue the same tool call with\n"
        "     _confirmed=true. If they declined, do not.\n"
    )


def _sig_args(sig: str) -> str:
    l = sig.find("(")
    r = sig.find(")")
    if 0 <= l < r:
        return sig[l + 1:r]
    return ""


def _target_key_for(tool: str, args: dict) -> Optional[str]:
    """The argument that names WHAT a tool operates on — for retry-break.

    Retry-break dedups on target, not full args: an LLM that reworded its
    ``intent`` string ("fix the layout" → "improve the layout") would
    otherwise slip past the per-arg dedup and keep failing on the same
    page. Returns None for tools whose failure isn't tied to a single
    named target (``run_guards``, ``understand_ask``, terminals)."""
    if not isinstance(args, dict) or not tool:
        return None
    for k in ("path", "workflow_id", "route", "entity", "name"):
        v = args.get(k)
        if isinstance(v, str) and v:
            return f"{k}={v}"
    # ``target`` nested {path, ...} — some seams pass their target that way.
    tgt = args.get("target")
    if isinstance(tgt, dict):
        p = tgt.get("path")
        if isinstance(p, str) and p:
            return f"path={p}"
    return None


def _canonical_call_key(tool: str, args: dict) -> str:
    """Stable string key for a (tool, args) pair — used by the loop's
    duplicate-call short-circuit. json.dumps with sort_keys is enough here:
    args are shallow, small, and JSON-safe. Non-serializable payloads fall
    back to str() so the key can still form; that's fine — worst case a
    repeat isn't caught, which is the same as pre-dedup behaviour."""
    try:
        return f"{tool}::{json.dumps(args or {}, sort_keys=True, default=str)}"
    except Exception:  # noqa: BLE001
        return f"{tool}::{str(args)[:400]}"


def build_initial_user_message(
    user_message: str,
    recall_block: str,
    memory_block: str = "",
) -> str:
    """Compose the first turn the model sees: the user's message, the
    recall dossier, and the smith-memory block.

    Memory sits ABOVE recall because a stale pending-fix signal (from
    memory) must dominate a fresh-eyes re-derivation from recall. If
    memory is empty (fresh conversation) it's still rendered so the model
    sees a consistent structure."""
    parts = [f"USER: {user_message}"]
    parts.append("")
    parts.append(memory_block or "<smith-memory>\nNo prior conversation state.\n</smith-memory>")
    parts.append("")
    parts.append("## App recall (pre-assembled — you may call `recall` again for re-checks)")
    parts.append(recall_block or "(no recall available)")
    parts.append("")
    parts.append(
        "Investigate with the read-only tools as needed, then call ONE of "
        "`propose_fix`, `answer`, or `ask_user`."
    )
    return "\n".join(parts)
