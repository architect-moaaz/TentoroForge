"""Smith orchestrator — the Actor–Critic-with-guards edit loop.

Smith today runs one ReACT loop, calls `answer`, commits whatever
happened, and hopes for the best. He can't see the blast radius of a
change, has no gate that says "your edit didn't fulfill the promise",
and no path from "guard failed" back to "try again with corrective
context". Three consecutive live tries on the same field-type change
proved the shortest path an LLM will take is the safe substring edit
plus a plausible-sounding lie.

This orchestrator wraps ``run_smith_agent`` in a bounded loop:

1. Invoke Smith with the ask + a running corrective context.
2. If Smith edited any files, run the guard suite.
3. Green → commit, synthesize the answer from the actual diff,
   return.
4. Red → parse failures into the next-turn corrective prompt, loop.
5. Turns exhausted → ``git revert`` every applied change, return
   an honest failure report naming the residual guard failures.

Answer text comes from the diff, not Smith's prose — kills the
"believes he did it" class by construction. The orchestrator's
``answer`` is authoritative; Smith's own ``answer`` becomes advisory.

All external boundaries are injectable seams (``smith_fn``,
``guard_fn``, ``diff_fn``, ``commit_fn``, ``revert_fn``) so the
loop is testable end-to-end without touching the LLM, git, or disk.
Prod defaults wire the real services.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Result type
# --------------------------------------------------------------------------- #

@dataclass
class OrchestratorResult:
    """The outcome the router/self-heal caller receives."""
    status: str                      # "resolved" | "asked" | "handoff" | "rolled_back" | "no_op"
    answer: str                      # user-visible chat message
    turns: int = 0                   # how many outer loop iterations ran
    applied_paths: list[str] = field(default_factory=list)
    commit: str | None = None
    handoff: dict[str, Any] | None = None
    question: str | None = None       # populated iff status == "asked"
    guard_history: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)  # inner-Smith traces per turn

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Public entry
# --------------------------------------------------------------------------- #

def run(
    user_message: str,
    output_dir: str,
    *,
    project_id: str | None = None,
    max_outer_turns: int = 15,
    smith_max_iters: int = 20,
    # Injectable seams — real defaults resolved lazily.
    smith_fn: Optional[Callable[..., dict[str, Any]]] = None,
    guard_fn: Optional[Callable[[str], Any]] = None,
    diff_fn:  Optional[Callable[[str, list[str]], str]] = None,
    commit_fn: Optional[Callable[[str, str, list[str]], str | None]] = None,
    revert_fn: Optional[Callable[[str, list[str]], bool]] = None,
    recall_fn: Optional[Callable[[str], str]] = None,
) -> OrchestratorResult:
    """Run the orchestrator loop.

    Contract:
      * ``smith_fn(user_message, output_dir, recall_block, memory_block,
                    max_iters)`` → dict shaped like ``run_smith_agent``'s
        return: ``{answer, question, handoff, diagnosis, edited_paths, trace}``.
      * ``guard_fn(output_dir)`` → :class:`services.guard_result.GuardResult`.
      * ``diff_fn(output_dir, paths)`` → human diff summary string.
      * ``commit_fn(output_dir, msg, paths)`` → short commit SHA or None.
      * ``revert_fn(output_dir, paths)`` → True on success.
      * ``recall_fn(output_dir)`` → enriched recall string.

    Never raises. Any unexpected exception is caught and converted to
    ``status='rolled_back'`` with an honest error message."""
    _smith  = smith_fn  or _default_smith
    _guards = guard_fn  or _default_guards
    _diff   = diff_fn   or _default_diff
    _commit = commit_fn or _default_commit
    _revert = revert_fn or _default_revert
    _recall = recall_fn or _default_recall

    applied_paths: list[str] = []
    guard_history: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    corrective_context = ""

    # ── Chat-native feedback (smith_outcomes) ────────────────────────────
    # The user's opening words judge the PREVIOUS turn: praise rewards it,
    # "still broken"/"didn't work" punishes it, and re-asking the same
    # thing is a silent punishment. Runs before this turn does anything so
    # the playbook Smith reads already reflects the verdict. Fail-open.
    try:
        from services import smith_outcomes as _outcomes
        _fb = _outcomes.apply_feedback_to_last_turn(output_dir, user_message)
        if _fb.get("applied"):
            logger.info("[smith-orch] feedback %s applied to last turn moves %s",
                        _fb["applied"], _fb.get("moves"))
    except Exception:  # noqa: BLE001
        pass

    # Snapshot the pre-Smith guard state so we only hold him accountable
    # for regressions HE introduces — not pre-existing app-level warnings
    # (e.g. an unrelated mutation-guard warning that was already red before
    # the ask arrived). Falls back to no baseline if the snapshot itself
    # crashes so a broken guard suite never blocks the loop entirely.
    try:
        baseline_guards = _guards(output_dir)
        logger.info(
            "[smith-orch] baseline guard snapshot: green=%s pre_existing_failures=%d",
            getattr(baseline_guards, "green", False),
            len(getattr(baseline_guards, "failures", []) or []),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[smith-orch] baseline snapshot failed: %r", exc)
        baseline_guards = None

    try:
        for turn in range(1, max_outer_turns + 1):
            recall = _recall(output_dir)
            memory = ""  # base recall carries this; can be extended
            full_msg = user_message
            if corrective_context:
                full_msg = user_message + "\n\n" + corrective_context

            smith_result = _smith(
                user_message=full_msg,
                output_dir=output_dir,
                recall_block=recall,
                memory_block=memory,
                max_iters=smith_max_iters,
            )
            traces.append({"turn": turn, **{k: v for k, v in smith_result.items()
                                             if k not in {"trace"}}})

            # -- Terminal: ask_user ---------------------------------------
            if smith_result.get("question"):
                last_tool = (smith_result.get("trace") or [{}])[-1].get("tool", "?")
                tools_used = [t.get("tool") for t in (smith_result.get("trace") or [])]
                logger.info(
                    "[smith-orch] turn=%d asked user: tools_used=%s "
                    "last_tool=%s question=%r",
                    turn, tools_used, last_tool,
                    (smith_result["question"] or "")[:200],
                )
                # Partial-success context: when an EARLIER turn already
                # applied edits (guards green on them), a later-turn punt
                # question must not HIDE that work — the user's files
                # changed, but the chat would show only a confused
                # clarification (register: About-page paragraph landed,
                # user saw a page-picker). Status stays "asked" — green
                # guards don't prove the ask landed (that's the
                # relevance gate's whole point) — but the answer leads
                # with what WAS applied so nothing is silently swallowed.
                answer_text = smith_result["question"]
                _last_green = bool(guard_history) and bool(
                    getattr(guard_history[-1], "green", False)
                )
                if applied_paths and _last_green:
                    applied_note = "\n".join(
                        f"  • `{p_}`" for p_ in applied_paths
                    )
                    answer_text = (
                        "I already applied change(s) to:\n" + applied_note +
                        "\n\nBut I'm not certain they fully cover your ask, "
                        "so before I go further:\n\n" + answer_text
                    )
                    logger.info(
                        "[smith-orch] turn=%d punt question prefixed with "
                        "%d applied path(s)", turn, len(applied_paths),
                    )
                return OrchestratorResult(
                    status="asked", answer=answer_text,
                    question=smith_result["question"],
                    turns=turn, applied_paths=applied_paths,
                    guard_history=[g.to_dict() if hasattr(g, "to_dict") else g
                                   for g in guard_history],
                    trace=traces,
                )

            # -- Terminal: handoff_to_pipeline ----------------------------
            if smith_result.get("handoff"):
                return OrchestratorResult(
                    status="handoff", answer=smith_result.get("answer") or "",
                    handoff=smith_result["handoff"],
                    turns=turn, applied_paths=applied_paths,
                    guard_history=[g.to_dict() if hasattr(g, "to_dict") else g
                                   for g in guard_history],
                    trace=traces,
                )

            new_edits = list(smith_result.get("edited_paths") or [])

            # -- Terminal: propose_fix (legacy) --------------------------
            # Smith emitted a diagnosis instead of doing the edit himself.
            # Apply the proposed fix through the seam it names, then loop
            # so guards can verify the applied changes.
            diagnosis = smith_result.get("diagnosis")
            if diagnosis and not new_edits:
                logger.info(
                    "[smith-orch] turn=%d Smith emitted diagnosis "
                    "(seam=%s) instead of direct edit — applying via seam",
                    turn,
                    ((diagnosis.get("proposedFix") or {}).get("seam") or "?"),
                )
                applied_from_fix, reject_reason, reject_details = \
                    _apply_proposed_fix(output_dir, diagnosis)
                if applied_from_fix:
                    new_edits = applied_from_fix
                else:
                    corrective_context = _build_reject_corrective(
                        turn=turn,
                        reason=reject_reason or "unknown",
                        details=reject_details or [],
                        diagnosis=diagnosis,
                    )
                    continue

            if not new_edits and not applied_paths:
                answer_text = smith_result.get("answer") or ""
                last_tool = (smith_result.get("trace") or [{}])[-1].get("tool", "?")
                logger.info(
                    "[smith-orch] turn=%d no_op: last_tool=%s answer_len=%d",
                    turn, last_tool, len(answer_text),
                )
                return OrchestratorResult(
                    status="no_op",
                    answer=answer_text or
                           "I looked into it but didn't make any changes.",
                    turns=turn, applied_paths=[],
                    guard_history=[], trace=traces,
                )

            applied_paths.extend(p for p in new_edits if p not in applied_paths)

            # -- Verify system-wide ---------------------------------------
            raw_guard = _guards(output_dir)
            # Filter to only NEW failures Smith is responsible for.
            # Falls back to raw result when baseline was unavailable or the
            # returned object doesn't support diff (test doubles).
            if baseline_guards is not None and hasattr(raw_guard, "diff_against"):
                guard_result = raw_guard.diff_against(baseline_guards)
                pre_existing = len(getattr(raw_guard, "failures", []) or []) - \
                               len(getattr(guard_result, "failures", []) or [])
                if pre_existing > 0:
                    logger.info(
                        "[smith-orch] turn=%d filtered %d pre-existing "
                        "failure(s); %d new failure(s) attributed to Smith",
                        turn, pre_existing,
                        len(getattr(guard_result, "failures", []) or []),
                    )
            else:
                guard_result = raw_guard
            guard_history.append(guard_result)

            if getattr(guard_result, "green", False):
                # Relevance gate — guards are green means "nothing broke,"
                # NOT "the user's ask landed." Check that Smith's diff
                # actually touched what he claimed to target.
                understanding = smith_result.get("understanding")
                relevance = _check_relevance(
                    output_dir, applied_paths, understanding, _diff,
                )
                if not relevance["ok"]:
                    logger.info(
                        "[smith-orch] turn=%d guards green but relevance "
                        "gate failed: %s", turn, relevance["reason"],
                    )
                    corrective_context = _build_relevance_corrective(
                        turn, user_message, understanding, applied_paths,
                        relevance,
                    )
                    continue

                # Convergence.
                diff_summary = _diff(output_dir, applied_paths) if applied_paths else ""
                commit_sha = _commit(
                    output_dir,
                    f"smith-orch: {user_message[:80]}",
                    applied_paths,
                ) if applied_paths else None
                answer = _synthesize_answer(user_message, diff_summary, applied_paths)
                return OrchestratorResult(
                    status="resolved", answer=answer, turns=turn,
                    applied_paths=applied_paths, commit=commit_sha,
                    guard_history=[g.to_dict() if hasattr(g, "to_dict") else g
                                   for g in guard_history],
                    trace=traces,
                )

            # -- Red: build corrective context, loop ----------------------
            corrective_context = _build_corrective_context(guard_result, turn)

        # -- Turns exhausted: rollback + honest failure ------------------
        _revert(output_dir, applied_paths)
        # A rollback is the strongest automatic punishment: the whole
        # turn's strategy failed guards until the budget ran out.
        try:
            from services import smith_outcomes as _outcomes
            _last, _entries = _outcomes.last_turn_entries(output_dir)
            for _e in {e.get("tool") for e in _entries
                       if e.get("signal") in ("apply_ok", "verified")}:
                _outcomes.record_outcome(
                    output_dir, tool=_e or "?", signal="regression",
                    intent_kind=_outcomes.classify_intent_kind(user_message),
                    intent_text=user_message,
                    evidence="orchestrator rolled back the turn (guards stayed red)",
                    turn=_last)
        except Exception:  # noqa: BLE001
            pass
        return OrchestratorResult(
            status="rolled_back",
            answer=_honest_failure(guard_history[-1] if guard_history else None,
                                    max_outer_turns, user_message),
            turns=max_outer_turns,
            applied_paths=[],
            guard_history=[g.to_dict() if hasattr(g, "to_dict") else g
                           for g in guard_history],
            trace=traces,
        )
    except Exception as exc:  # noqa: BLE001 — the orchestrator must never crash the caller
        logger.exception("[smith-orch] unhandled failure — rolling back")
        # Only revert (and only CLAIM reversion) when something was
        # actually applied — a turn-0 crash (e.g. the API refusing the
        # request) previously reported "Reverted every applied edit"
        # with nothing applied, which reads as data loss to the user.
        if applied_paths:
            try:
                _revert(output_dir, applied_paths)
            except Exception:  # noqa: BLE001
                pass
            _crash_tail = ("Reverted every applied edit. "
                           "Please try again or refine the ask.")
        else:
            _crash_tail = ("No changes had been applied yet, so your app "
                           "is untouched. Please try again.")
        return OrchestratorResult(
            status="rolled_back",
            answer=(f"Orchestrator crashed mid-turn: {exc!r}. {_crash_tail}"),
            turns=len(traces), applied_paths=[],
            guard_history=[g.to_dict() if hasattr(g, "to_dict") else g
                           for g in guard_history],
            trace=traces,
        )


# --------------------------------------------------------------------------- #
# Answer synthesis — from the diff, NOT Smith's prose
# --------------------------------------------------------------------------- #

def _synthesize_answer(user_message: str, diff: str, paths: list[str]) -> str:
    """Compose the user-facing chat message from the actual diff.

    We deliberately do NOT parrot Smith's own summary — his prose is
    the exact place the "believes he did it" lie lives. The diff is
    the ground truth."""
    if not paths:
        return "I made no changes — the request didn't require any file edits."
    head = f"Applied {len(paths)} change(s):"
    file_lines = [f"  • `{p}`" for p in paths[:6]]
    if len(paths) > 6:
        file_lines.append(f"  • …and {len(paths) - 6} more")
    body = diff.strip()
    if not body:
        body = "(diff summary unavailable — see git show HEAD)"
    return "\n".join([head, *file_lines, "", "**What changed:**", body])


def _build_corrective_context(guard_result: Any, turn: int) -> str:
    """Turn a red GuardResult into a next-turn corrective prompt."""
    if guard_result is None:
        return f"Turn {turn} produced no result. Try again."
    if hasattr(guard_result, "to_prompt"):
        text = guard_result.to_prompt()
    else:
        text = str(guard_result)
    return "\n".join([
        f"--- CORRECTIVE CONTEXT (turn {turn}) ---",
        text,
        "",
        "Route each failure to the specialist seam that owns the impacted",
        "artifact (page_schema_patch, edit_workflow, add_entity, env_upsert, …).",
        "Do NOT `answer` until run_guards returns GREEN. Do NOT re-attempt",
        "the exact edit that just failed — pick a different path.",
    ])


def _honest_failure(last_guard: Any, turns: int, user_message: str) -> str:
    """The message we ship when the loop couldn't converge."""
    parts = [
        f"I tried {turns} iterations to satisfy: \"{user_message[:120]}\"",
        "",
        "Every edit I made has been reverted — the app is in its pre-change state.",
        "",
        "Residual failures that stopped convergence:",
    ]
    if last_guard is None:
        parts.append("  (no guard output captured — likely a mid-turn crash)")
    else:
        text = last_guard.to_prompt() if hasattr(last_guard, "to_prompt") else str(last_guard)
        parts.append(text)
    parts.extend([
        "",
        "Can you clarify what you want changed, or grant permission for a",
        "broader change than the safe substring-level edit I attempted?",
    ])
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Line-level diff readers used by the relevance gate
# --------------------------------------------------------------------------- #

def _raw_line_diff(output_dir: str, paths: list[str]) -> str:
    """Actual line-by-line git diff for ``paths`` against HEAD. Empty
    string on any failure — the caller falls back to reading the raw
    files, so a missing git surface is not fatal."""
    import subprocess
    if not paths:
        return ""
    try:
        return subprocess.check_output(
            ["git", "-C", output_dir, "diff", "-U0", "HEAD", "--", *paths],
            text=True, timeout=15, stderr=subprocess.DEVNULL,
        )
    except Exception:  # noqa: BLE001
        return ""


def _touched_files_contents(output_dir: str, paths: list[str]) -> str:
    """Fallback: concatenate the current text of every touched file.
    Weaker than a line diff (matches labels that were ALREADY present
    even if Smith didn't move them) but ensures the gate has *some*
    signal when git isn't available (tests, worktrees, etc.)."""
    from pathlib import Path
    root = Path(output_dir)
    chunks: list[str] = []
    for p in paths:
        f = root / p
        try:
            chunks.append(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
    return "\n".join(chunks)


# --------------------------------------------------------------------------- #
# Relevance gate — did the diff actually address the user's ask?
# --------------------------------------------------------------------------- #

def _check_relevance(
    output_dir: str,
    applied_paths: list[str],
    understanding: dict | None,
    diff_fn: Callable[[str, list[str]], str],
) -> dict:
    """The critic that closes the 'cheapest-edit-wins' loophole.

    Green guards prove nothing broke; the relevance gate proves the
    diff was ABOUT the ask. Returns ``{ok: bool, reason: str}``.

    Rules, applied in order:
      1. If ``understanding`` is missing, gate PASSES (no target to
         check against; the caller will surface this separately).
         In practice the mutation-block in :mod:`agents.smith_agent`
         means understanding is present whenever applied_paths is
         non-empty — so this branch only fires for tests / no-op
         convergence.
      2. If applied_paths is empty, gate PASSES (no diff to police —
         answer-only turns handle their own contract).
      3. target_file MUST appear in applied_paths (canonicalized).
         The diff must touch the file Smith said he'd touch.
      4. The element_label MUST appear literally in the diff output.
         The changed lines must reference the specific element."""
    if not understanding:
        return {"ok": True, "reason": "no understanding recorded — gate skipped"}
    if not applied_paths:
        return {"ok": True, "reason": "no edits — gate skipped"}

    target_file = (understanding.get("target_file") or "").strip()
    element_label = (understanding.get("element_label") or "").strip()

    if target_file:
        target_norm = target_file.lstrip("./").lower()
        touched = [p.lstrip("./").lower() for p in applied_paths]
        if not any(target_norm in p or p in target_norm for p in touched):
            return {
                "ok": False,
                "reason": (
                    f"target_file={target_file!r} was not touched. "
                    f"Applied paths: {applied_paths}"
                ),
                "kind": "wrong_file",
            }

    if element_label:
        # Try the caller-supplied diff_fn first (tests inject one), then
        # a real line-level git diff, then the current file contents as
        # a last-ditch signal. The check succeeds if ANY source
        # contains the label.
        raw_diff = ""
        for src in (
            lambda: diff_fn(output_dir, applied_paths) if diff_fn else "",
            lambda: _raw_line_diff(output_dir, applied_paths),
            lambda: _touched_files_contents(output_dir, applied_paths),
        ):
            try:
                candidate = src() or ""
            except Exception:  # noqa: BLE001
                candidate = ""
            if candidate and element_label.lower() in candidate.lower():
                raw_diff = candidate
                break
            raw_diff = raw_diff or candidate
        if element_label.lower() not in raw_diff.lower():
            # Token fallback — Smith often labels the element
            # DESCRIPTIVELY ("price alerts paragraph") rather than by
            # its literal text, and an exact-substring test rejected
            # every such turn until the loop exhausted and reverted a
            # good edit. Strip generic UI words; if every remaining
            # content token appears in the diff, the changed lines do
            # reference the element the user named.
            import re as _re2
            _GENERIC = {
                "page", "content", "section", "paragraph", "text",
                "button", "label", "field", "heading", "title", "area",
                "element", "component", "item", "list", "form", "the",
                "a", "an", "of", "on", "in", "new", "second", "third",
            }
            tokens = [t for t in _re2.findall(r"[a-z0-9]+", element_label.lower())
                      if t not in _GENERIC and len(t) > 1]
            hay = raw_diff.lower()
            if tokens and all(t in hay for t in tokens):
                return {"ok": True,
                        "reason": (f"element_label tokens {tokens} all "
                                   "present in diff")}
            if not tokens:
                return {"ok": True,
                        "reason": (f"element_label={element_label!r} is "
                                   "entirely generic — nothing checkable")}
            return {
                "ok": False,
                "reason": (
                    f"element_label={element_label!r} does not appear in "
                    f"the diff — the changed lines don't reference the "
                    f"target element."
                ),
                "kind": "wrong_element",
            }

    return {"ok": True, "reason": "target_file + element_label both touched"}


def _build_relevance_corrective(
    turn: int, user_message: str, understanding: dict | None,
    applied_paths: list[str], relevance: dict,
) -> str:
    """Author the next-turn nudge when the relevance gate fails.

    Names the specific gap ("wrong file" vs "wrong element") so Smith
    can course-correct rather than repeating the same cosmetic edit."""
    u = understanding or {}
    header = (
        f"Turn {turn}: your edits landed but the RELEVANCE gate refused "
        f"to mark this resolved.\n"
        f"User ask: {user_message[:200]}\n"
        f"Your extracted target: file={u.get('target_file')!r} "
        f"element={u.get('element_label')!r}\n"
        f"Applied paths: {applied_paths}\n"
        f"Gate reason: {relevance.get('reason')}\n"
    )
    kind = relevance.get("kind")
    if kind == "wrong_file":
        body = (
            "Your diff didn't touch the file you said you would. Either:\n"
            "  a) Re-issue understand_ask with a corrected target_file "
            "(use list_pages/read_page to find the real one), then edit "
            "there.\n"
            "  b) Undo the misplaced edit (edit_file to restore the "
            "unrelated file) and edit the correct file this time.\n"
        )
    elif kind == "wrong_element":
        body = (
            f"Your diff exists but nowhere touches text mentioning "
            f"{u.get('element_label')!r}. You likely edited an unrelated "
            f"node (cosmetic reformat, wrong field). Read the target "
            f"file, find the line whose label/name matches "
            f"{u.get('element_label')!r}, and edit THAT line. "
            f"'ensuring the diff mentions the label' is a HARD requirement, "
            f"not a suggestion.\n"
        )
    else:
        body = (
            "Fix the mismatch between your understanding and your diff, "
            "then retry. If the ask itself is ambiguous, call ask_user.\n"
        )
    return header + "\n" + body


# --------------------------------------------------------------------------- #
# Corrective-context builders — humanize applier rejections for Smith
# --------------------------------------------------------------------------- #

def _build_reject_corrective(
    *, turn: int, reason: str, details: list[Any], diagnosis: dict,
) -> str:
    """Author the next-turn corrective prompt for a rejected propose_fix.

    Special-cases the two most common rejection kinds so Smith gets
    concrete, actionable steering instead of raw applier dicts:

    * ``explanation/patch coherence failed`` — Smith's English explanation
      uses one grammar (add/remove/replace) but his JSON patch does
      another. The corrective spells out the mismatch and instructs him
      to align them or switch to a direct edit tool.
    * ``patch validation failed`` — usually an unresolved JSON path, i.e.
      the target node doesn't exist. Suggests read_file + re-locate."""
    header = (f"Turn {turn}: your propose_fix was REJECTED by the apply "
              f"gate.\nReason: {reason}")

    if "coherence failed" in reason:
        lines = [header, "",
                 "Your written EXPLANATION and your JSON PATCH disagree.",
                 "The gate found these specific grammar mismatches:"]
        for d in details[:5]:
            if not isinstance(d, dict):
                lines.append(f"  - {d}")
                continue
            k = d.get("kind") or "?"
            exp = d.get("expected") or "?"
            act = d.get("actual") or "?"
            lines.append(
                f"  - Your explanation says kind='{k}' with target='{exp}', "
                f"but the patch actually touches '{act}'."
            )
        lines.extend([
            "",
            "COMMON CAUSE: you're CHANGING an existing field's type (e.g. ",
            "Select → FileUpload), which is grammatically a REPLACE, but ",
            "your explanation says 'add a FileUpload'. Either:",
            "  a) Rewrite the explanation as 'change the X field from Y to "
            "Z' or 'replace Y with Z on the X field', keeping the same "
            "patch. This is usually what you want.",
            "  b) Actually add a new field AND remove the old one (two ops "
            "in the same patch) if adding is genuinely what you meant.",
            "  c) Skip propose_fix entirely: call edit_page for schema/field "
            "changes or edit_file for anything else.",
            "Do NOT resubmit the same diagnosis unchanged.",
        ])
        return "\n".join(lines)

    if "validation failed" in reason:
        lines = [header, "",
                 "Your patch references a JSON path that does not exist in "
                 "the target schema. Details:"]
        for d in details[:5]:
            if isinstance(d, dict):
                lines.append("  - " + (d.get("msg") or str(d)))
        lines.extend([
            "",
            "Call read_file on the schema, copy the ACTUAL path of the node "
            "you want to change, and re-issue propose_fix with a patch that "
            "targets that exact path. Or use edit_page which resolves "
            "targets by name/component rather than by JSON path.",
        ])
        return "\n".join(lines)

    # Generic fallback
    lines = [header, "Details:"]
    for d in details[:5]:
        if isinstance(d, dict):
            lines.append("  - " + (d.get("msg") or d.get("kind") or str(d)))
        else:
            lines.append(f"  - {d}")
    lines.extend([
        "",
        "Options: fix the diagnosis and retry, or switch to a direct tool "
        "(edit_page / edit_workflow / edit_file). Do NOT resubmit unchanged.",
    ])
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# propose_fix bridge — apply Smith's diagnosis through the fix_applier seams
# --------------------------------------------------------------------------- #

def _apply_proposed_fix(
    output_dir: str, diagnosis: dict,
) -> tuple[list[str], str | None, list[Any]]:
    """Apply a Diagnosis through :mod:`services.fix_applier`.

    Returns ``(paths, reject_reason, reject_details)``:
      * ``paths``  — files touched (empty ⇒ apply failed).
      * ``reject_reason`` — the string reason when apply refused (or None).
      * ``reject_details`` — the ``verify.remaining`` list from the applier,
        which for a coherence rejection carries the specific mismatch."""
    from services.fix_applier import apply_fix
    try:
        result = apply_fix(output_dir, diagnosis, git=False)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[smith-orch] apply_fix crashed: %r", exc)
        return [], f"apply_fix crashed: {exc!r}", []
    if not result.get("applied"):
        reason = result.get("reason") or "unknown"
        remaining = (result.get("verify") or {}).get("remaining") or []
        logger.info(
            "[smith-orch] apply_fix no-op: seam=%s reason=%s remaining=%s",
            result.get("seam"), reason, remaining,
        )
        return [], reason, remaining
    paths: list[str] = []
    seen: set[str] = set()
    for ch in result.get("changes") or []:
        if not isinstance(ch, dict):
            continue
        p = ch.get("path") or ch.get("artifact")
        if p and p not in seen:
            paths.append(p)
            seen.add(p)
    # Fallback: some seams (workflow_node_config) put the target on the
    # diagnosis' `artifact.path` instead of per-change.
    if not paths:
        art_path = ((diagnosis or {}).get("artifact") or {}).get("path")
        if art_path:
            paths.append(art_path)
    return paths, None, []


# --------------------------------------------------------------------------- #
# Default seam implementations — wired lazily so tests don't pay import cost
# --------------------------------------------------------------------------- #

def _default_smith(*, user_message, output_dir, recall_block, memory_block, max_iters):
    from agents.smith_agent import run_smith_agent
    return run_smith_agent(
        user_message=user_message,
        output_dir=output_dir,
        recall_block=recall_block,
        memory_block=memory_block,
        max_iters=max_iters,
    )


def _default_guards(output_dir: str):
    from services.post_generate_fixes import apply_post_generate_fixes_with_result
    # force=True: this is always a Smith re-apply after an edit, so the
    # in-process idempotency skip ("called twice in the same process")
    # must not surface as a guard failure and roll back a good turn.
    return apply_post_generate_fixes_with_result(output_dir, force=True)


def _default_diff(output_dir: str, paths: list[str]) -> str:
    """Produce a REAL line-level `git diff` for the touched paths (was
    ``--stat`` originally, but that only prints file names + change
    counts which broke the relevance gate). We now emit ``-U1`` so the
    output contains the exact changed lines (labels, values, etc.)
    that the relevance gate greps for."""
    import subprocess
    if not paths:
        return ""
    try:
        out = subprocess.check_output(
            ["git", "-C", output_dir, "diff", "-U1", "HEAD", "--", *paths],
            text=True, timeout=15,
        )
        # Untracked paths produce NO output from `diff HEAD`, which blinded
        # the relevance gate (an edit to an untracked page read as "no
        # diff" and could neither be validated nor caught when clobbered).
        # Emit those as full-file additions via --no-index.
        import os as _os
        tracked = set(subprocess.check_output(
            ["git", "-C", output_dir, "ls-files", "--", *paths],
            text=True, timeout=15,
        ).splitlines())
        extras: list[str] = []
        for p_ in paths:
            if p_ in tracked or not _os.path.isfile(_os.path.join(output_dir, p_)):
                continue
            try:
                extras.append(subprocess.run(
                    ["git", "-C", output_dir, "diff", "-U1", "--no-index",
                     "/dev/null", p_],
                    text=True, timeout=15, capture_output=True,
                ).stdout)
            except Exception:  # noqa: BLE001
                continue
        combined = (out + "\n" + "\n".join(extras)).strip()
        return combined or "(no diff — files may have been staged but not modified)"
    except Exception as exc:  # noqa: BLE001
        return f"(diff unavailable: {exc!r})"


def _default_commit(output_dir: str, msg: str, paths: list[str]) -> str | None:
    """Stage the paths + commit; return short SHA or None on failure."""
    import subprocess
    try:
        subprocess.check_call(["git", "-C", output_dir, "add", "--", *paths],
                              timeout=10)
        subprocess.check_call(["git", "-C", output_dir, "commit", "-m", msg],
                              timeout=10)
        sha = subprocess.check_output(
            ["git", "-C", output_dir, "rev-parse", "--short", "HEAD"],
            text=True, timeout=5,
        ).strip()
        return sha or None
    except Exception:  # noqa: BLE001
        return None


def _default_revert(output_dir: str, paths: list[str]) -> bool:
    """Best-effort restoration of the named paths to HEAD state.
    Uses `git checkout -- <paths>` rather than a revert-commit, so the
    workspace looks like nothing happened."""
    import subprocess
    if not paths:
        return True
    try:
        subprocess.check_call(
            ["git", "-C", output_dir, "checkout", "--", *paths], timeout=15,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def _default_recall(output_dir: str) -> str:
    try:
        from services.smith_recall_enrich import enriched_recall_block
        return enriched_recall_block(output_dir)
    except Exception as exc:  # noqa: BLE001
        return f"(recall unavailable: {exc!r})"
