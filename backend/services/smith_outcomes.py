"""Smith reward/punishment ledger — outcome feedback that compounds.

Every consequential Smith action gets SCORED, and the aggregate scoreboard
is distilled into a playbook block injected into Smith's system prompt.
Rewarded moves become preferred plays; punished moves demand verification
or an alternative route. This is the platform's pragmatic version of
reinforcement: the model doesn't retrain, but its per-project working
memory carries an explicit record of what worked and what got punished,
and the prompt contract makes that record binding on behaviour.

Signals and scores (a ledger entry per event):

    apply_ok        +1   mutating tool ran without error
    apply_error     -2   tool crashed / validator rejected the change
    verified        +2   a verifying tool passed after the mutation
    regression      -3   verification failed after the mutation
    user_praise     +3   next user message thanks/approves the result
    user_complaint  -3   next user message says it broke / didn't work
    re_ask          -1   user repeats the same ask (silent dissatisfaction)

Storage: JSONL at ``<output_dir>/contracts/smith-outcomes.jsonl`` — the
project directory is Smith's long-term memory boundary, survives backend
restarts, and travels with the app.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

SCORES = {
    "apply_ok": 1,
    "apply_error": -2,
    "verified": 2,
    "regression": -3,
    "user_praise": 3,
    "user_complaint": -3,
    "re_ask": -1,
}

# How many most-recent entries the scoreboard considers. Old lessons decay
# by falling out of the window rather than by fractional weighting.
_WINDOW = 200

_PRAISE_RE = re.compile(
    r"\b(perfect|great|awesome|amazing|works now|it works|working now|"
    r"well done|nice|love it|thank you|thanks|good job|exactly)\b", re.I)
_COMPLAINT_RE = re.compile(
    r"\b(didn'?t work|doesn'?t work|not work(ing)?|broke(n)?|"
    r"still (the same|broken|not|wrong)|went wrong|is wrong|failed|worse|"
    r"revert|undo (that|this|it)|messed up|screwed up|ruined)\b", re.I)

_STOPWORDS = frozenset(
    "the a an to of in on for and or is are it this that please can you my "
    "me i want need make add with from at be do".split())


def _ledger_path(output_dir: str) -> Path:
    return Path(output_dir) / "contracts" / "smith-outcomes.jsonl"


def classify_intent_kind(text: str) -> str:
    """Coarse bucket for the ask — the ledger key alongside the tool name."""
    low = (text or "").lower()
    for kind, pat in (
        ("fix", r"\b(fix|broken|bug|error|crash|wrong|doesn'?t|didn'?t|not work)\b"),
        ("style", r"\b(color|colour|style|font|theme|look|design|layout|spacing|dark|light)\b"),
        ("nav", r"\b(menu|nav|sidebar|link|route|page url|redirect)\b"),
        ("workflow", r"\b(workflow|automation|approv|notif|email|trigger)\b"),
        ("data", r"\b(field|column|table|record|database|entity|dropdown|form)\b"),
        ("build", r"\b(add|create|build|new page|new screen|generate|feature)\b"),
    ):
        if re.search(pat, low):
            return kind
    return "other"


def record_outcome(
    output_dir: str,
    *,
    tool: str,
    signal: str,
    intent_kind: str = "other",
    intent_text: str = "",
    evidence: str = "",
    turn: int | None = None,
    score: int | None = None,
) -> None:
    """Append one scored event. Never raises."""
    try:
        path = _ledger_path(output_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": round(time.time(), 2),
            "turn": turn,
            "tool": tool,
            "intent_kind": intent_kind,
            "intent_text": (intent_text or "")[:200],
            "signal": signal,
            "score": SCORES.get(signal, 0) if score is None else score,
            "evidence": (evidence or "")[:300],
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception as exc:  # noqa: BLE001 — feedback must never break a turn
        logger.warning("smith_outcomes: record failed: %s", exc)


def _read(output_dir: str) -> list[dict]:
    path = _ledger_path(output_dir)
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        return []
    return out


def next_turn_id(output_dir: str) -> int:
    entries = _read(output_dir)
    turns = [e.get("turn") for e in entries if isinstance(e.get("turn"), int)]
    return (max(turns) + 1) if turns else 1


def last_turn_entries(output_dir: str) -> tuple[int | None, list[dict]]:
    entries = _read(output_dir)
    turns = [e.get("turn") for e in entries if isinstance(e.get("turn"), int)]
    if not turns:
        return None, []
    last = max(turns)
    return last, [e for e in entries if e.get("turn") == last]


def scoreboard(output_dir: str) -> dict[tuple[str, str], dict]:
    """Aggregate the recent window into {(intent_kind, tool): stats}."""
    board: dict[tuple[str, str], dict] = {}
    for e in _read(output_dir)[-_WINDOW:]:
        key = (e.get("intent_kind") or "other", e.get("tool") or "?")
        rec = board.setdefault(key, {"score": 0, "n": 0, "last_fail": ""})
        rec["score"] += int(e.get("score") or 0)
        rec["n"] += 1
        if int(e.get("score") or 0) < 0:
            rec["last_fail"] = (e.get("evidence") or e.get("signal") or "")[:160]
    return board


def score_user_message(text: str) -> tuple[str | None, int]:
    """Detect chat-native feedback about the PREVIOUS turn.

    Complaint wins over praise when both match ("thanks but it's still
    broken" is a complaint)."""
    if _COMPLAINT_RE.search(text or ""):
        return "user_complaint", SCORES["user_complaint"]
    if _PRAISE_RE.search(text or ""):
        return "user_praise", SCORES["user_praise"]
    return None, 0


def is_re_ask(prev_intent_text: str, new_text: str) -> bool:
    """Token-overlap heuristic: the user asking the same thing again means
    the previous attempt silently failed them."""
    def toks(s: str) -> set[str]:
        return {t for t in re.findall(r"[a-z0-9']+", (s or "").lower())
                if t not in _STOPWORDS and len(t) > 2}
    a, b = toks(prev_intent_text), toks(new_text)
    if len(a) < 3 or len(b) < 3:
        return False
    overlap = len(a & b) / max(1, len(a | b))
    return overlap >= 0.6


def apply_feedback_to_last_turn(output_dir: str, user_message: str) -> dict:
    """Turn-entry hook: score the previous turn's moves from this message.

    Praise/complaint apply to every distinct (tool, intent) the last turn
    recorded; a re-ask (same intent, no explicit sentiment) is a smaller
    punishment. Returns a summary for logging. Never raises."""
    try:
        last, entries = last_turn_entries(output_dir)
        if last is None:
            return {"applied": None}
        acted = [(e.get("tool"), e.get("intent_kind"), e.get("intent_text"))
                 for e in entries
                 if e.get("signal") in ("apply_ok", "apply_error",
                                        "verified", "regression")]
        if not acted:
            return {"applied": None}
        seen: set[tuple[str, str]] = set()
        signal, _ = score_user_message(user_message)
        if signal is None:
            prev_text = next((t for _, _, t in acted if t), "")
            if prev_text and is_re_ask(prev_text, user_message):
                signal = "re_ask"
        if signal is None:
            return {"applied": None}
        for tool, kind, text in acted:
            key = (tool or "?", kind or "other")
            if key in seen:
                continue
            seen.add(key)
            record_outcome(
                output_dir, tool=tool or "?", signal=signal,
                intent_kind=kind or "other", intent_text=text or "",
                evidence=f"user said: {(user_message or '')[:120]}", turn=last)
        return {"applied": signal, "moves": sorted(seen)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("smith_outcomes: feedback hook failed: %s", exc)
        return {"applied": None, "error": str(exc)}


def render_playbook(output_dir: str, max_rows: int = 6) -> str:
    """Distill the scoreboard into the prompt block that changes behaviour."""
    board = scoreboard(output_dir)
    if not board:
        return ""
    ranked = sorted(board.items(), key=lambda kv: kv[1]["score"], reverse=True)
    proven = [(k, v) for k, v in ranked if v["score"] >= 2][:max_rows]
    punished = [(k, v) for k, v in reversed(ranked) if v["score"] <= -2][:max_rows]
    if not proven and not punished:
        return ""
    lines = ["<smith-playbook>",
             "Your outcome ledger for THIS project (rewards and punishments "
             "earned from real results and user reactions):"]
    if proven:
        lines.append("PROVEN MOVES — prefer these; they earned rewards:")
        for (kind, tool), v in proven:
            lines.append(f"  • {kind} via {tool}: +{v['score']} over {v['n']} event(s)")
    if punished:
        lines.append("PUNISHED MOVES — these failed or drew complaints:")
        for (kind, tool), v in punished:
            why = f" (last failure: {v['last_fail']})" if v["last_fail"] else ""
            lines.append(f"  • {kind} via {tool}: {v['score']} over {v['n']} event(s){why}")
        lines.append(
            "Consequences you MUST honor: after using a punished move, run a "
            "verifying tool before answering. If a move is at -4 or below, "
            "choose a different tool or approach for that intent, and say "
            "why. A repeated user complaint on the same move means your "
            "previous strategy is wrong — change strategy, don't retry it.")
    lines.append("</smith-playbook>")
    return "\n".join(lines)
