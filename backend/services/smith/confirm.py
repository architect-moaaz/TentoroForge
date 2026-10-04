"""A yes, remembered between the turn that asks for it and the turn that acts.

"Get rid of complaints" retires the entity, the screens built on it, the
workflows that act on it and their buttons on every other screen. The
dependency set is computed before any of it happens — `entity_change.dependents`
— and it was never shown to anyone. The person found out by looking.

WHY A RECORD AND NOT A FLAG IN THE MESSAGE. The turn that says "go ahead" is a
new request in a new process: read on its own it is the same ask again, so the
gate would fire again and the two of them would loop. What is kept is the
FINGERPRINT of the exact operation that was described — verb and target — so a
yes only lets through the thing that was actually shown, and a yes to
something else is not a yes to this.

Taken as it is read, like `pending_ask`: a permission that outlives its
question is a permission nobody gave.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PENDING_PATH = Path(".forge") / "pending-confirm.json"

#: Whole-message agreement. Not "yes, but change the name first" — that is a
#: new request, and treating it as consent would act on the wrong thing.
_YES = frozenset({
    "yes", "y", "go ahead", "go ahead.", "do it", "confirm", "confirmed",
    "proceed", "ok", "okay", "yes please", "yes do it", "sure", "carry on",
    "go on", "that's fine", "thats fine", "remove it", "delete it", "yes, go ahead",
})

#: Yes in other common languages (WHOLE message only; a word that is also something else is left out).
_YES_OTHER = frozenset({"sí", "si", "oui", "ja", "claro", "vale", "d'accord", "dacord", "हाँ", "हां", "जी हाँ", "ठीक है", "نعم", "はい", "好", "是"})
_YES = _YES | _YES_OTHER

#: What the chips say. The first is the yes the gate is looking for.
YES_LABEL = "Go ahead"
NO_LABEL = "No, leave it"


#: Words a plain yes is made of, besides the thing it is a yes to.
_CONSENT_WORDS = frozenset({
    "yes", "yeah", "yep", "y", "please", "go", "ahead", "do", "it", "delete", "remove", "proceed",
    "ok", "okay", "sure", "confirm", "confirmed", "carry", "on", "that's", "thats", "fine", "the",
    "this", "that", "them", "all", "and", "now", "just", "page", "field", "record", "process",
    "workflow", "rule", "go-ahead",
})
#: At least one of these, so "the page" alone is not a yes.
_AGREEING = frozenset({"yes", "yeah", "yep", "y", "ahead", "do", "delete", "remove", "proceed", "ok",
                       "okay", "sure", "confirm", "confirmed", "fine"})


def is_yes(message: str, target: str = "") -> bool:
    """A whole-message yes — "yes", "go ahead", or a yes made only of
    agreeing words and the name of what it agrees to: "Yes, delete it",
    "yes please remove the about page". Asked to delete F&B's About page,
    "Yes, delete it" was not heard as a yes and the question came back four
    times (2026-10-02). Anything else in it ("yes, but rename it first") is
    a new request, not consent."""
    m = " ".join((message or "").strip().lower().rstrip(".!").split())
    if m in _YES or m == YES_LABEL.lower():
        return True
    import re
    words = re.findall(r"[a-z0-9'’-]+", m)
    named = set(re.findall(r"[a-z0-9]+", str(target or "").lower()))
    return bool(words) and any(w in _AGREEING for w in words) \
        and all(w in _CONSENT_WORDS or w in named for w in words)


def fingerprint(verb: str, target: str) -> str:
    """What was shown, so a yes cannot let something else through."""
    return f"{str(verb or '').strip().lower()}:{' '.join(str(target or '').lower().split())}"


def _path(output_dir: str | Path) -> Path:
    return Path(output_dir) / PENDING_PATH


#: A question nobody answered for this long is not waiting any more (the same
#: bound as `pending_ask.MAX_AGE_S`): a "yes" days later is not a yes to it.
MAX_AGE_S = 2 * 3600


def _read(output_dir: str | Path) -> dict:
    try:
        raw = json.loads(_path(output_dir).read_text("utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return raw if isinstance(raw, dict) else {}


def waiting(output_dir: str | Path) -> bool:
    """Whether a confirmation is waiting for its answer — read, not taken.
    An expired one is not waiting."""
    import time
    raw = _read(output_dir)
    if not raw.get("fingerprint"):
        return False
    at = raw.get("at")
    return not (isinstance(at, (int, float)) and time.time() - at > MAX_AGE_S)


def pending_target(output_dir: str | Path) -> str:
    """The target of the waiting confirmation (what a yes must name or ignore)."""
    return str(_read(output_dir).get("fingerprint") or "").partition(":")[2]


def decline_if_not_yes(output_dir: str | Path, message: str) -> str:
    """A waiting confirmation answered by anything but a yes is over: "no",
    "do not remove it", "leave it", another request entirely - even one phrased
    as a question ("can you rename it instead?"). Only a QUESTION ABOUT THE
    PENDING OPERATION ("what will it take with it?") keeps it waiting. When in
    doubt it is CLEARED: asking again is safer than a stale removal.

    Returns "no" for a clear no (the caller says "Okay, I left it as it was."),
    "dropped" for anything else that cleared it, "" when nothing was waiting,
    the message is its yes, or it is a question about it."""
    if not waiting(output_dir):
        if _path(output_dir).exists():
            clear(output_dir)                 # expired: remove it, it asks nothing
        return ""
    target = pending_target(output_dir)
    if is_yes(message, target):
        return ""
    if is_question_about(message, target):
        return ""            # answered while it still waits; the yes then reaches it
    clear(output_dir)
    return "no" if is_clear_no(message) else "dropped"


#: Openers that are questions even without a "?".
_SURE_OPENERS = re.compile(r"^(?:what|why|will|would|is|are|does|am|was|were|has|tell me|explain|remind me|are you sure|show me what)\b", re.I)
#: Openers that are only questions WITH a "?" ("do not remove it", "when you are done, add...",
#: "who cares, rename it", "have it hidden instead", "which means no").
_NEEDS_QMARK = re.compile(r"^(?:how|which|who|where|when|do|did|have|may|might|can|could|should|shall)\b", re.I)
_VERBS = (r"add|make|rename|hide|change|create|set|turn|move|update|build|put|switch|replace|insert|edit|reorder|sort|filter|"
          r"style|colou?r|publish|launch|connect|import|export|link|translate|show|display|remove|delete|drop|use|open")
#: A REQUEST to do something else - not a question about the pending operation, however it is phrased:
#: an imperative ("add a filter"), "can you / could you / would you / will you <do>", "should I / shall we <do>",
#: "let's <do>", "I want to <do>", or "instead / rather".
_REQUEST_FORM = re.compile(
    rf"^(?:please\s+)?(?:(?:can|could|would|will)\s+you|(?:should|shall)\s+(?:i|we)|let'?s|i(?:\s+want|\s+need|'d like)(?:\s+you)?\s+to)\s+"
    rf"(?:also\s+|just\s+)?(?:{_VERBS})\b|^(?:please\s+)?(?!show me what|tell me)(?:{_VERBS})\b|^(?:why not|how about)\b|\b(?:instead|rather)\b", re.I)
#: A generic question about what the pending operation DOES - needs no target word.
_CONSEQUENCE = re.compile(
    r"\b(?:are you sure|what happens|what will (?:it|that|this)|what does (?:it|that|this)|what would (?:it|that|this)|would (?:that|it|this) (?:delete|remove|lose|erase|break)|"
    r"how many|can (?:it|this|that) be undone|can i undo|undo|is (?:it|that|this) safe|what about|any (?:risk|data)|"
    r"(?:records?|rows?|history|values?|entries|existing|data|doses|everything|screens?|pages?|processes|workflows?|rules?))\b", re.I)
_STRICT_CONSEQUENCE = re.compile(r"\b(?:are you sure|what happens|what will|what does|what would|what about|how many|undo|undone|is (?:it|that|this) safe)\b", re.I)
_DO_VERB = re.compile(r"\b(?:add|make|rename|hide|change|create|set|turn|move|update|build|put|switch|replace|edit|reorder|sort|filter|publish|translate|insert|"
                      r"hid\w*|renam\w*|chang\w*|inst[a-z]{2,4}d)\b", re.I)
_PRONOUN = re.compile(r"\b(?:it|that|this|them|these|those)\b", re.I)


def _target_words(target: str) -> set[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(target or ""))
    return {w for w in re.split(r"[^a-z0-9]+", spaced.lower()) if len(w) > 2}


def is_question(message: str) -> bool:
    """A question, not a request: it ends with "?" or opens with an unambiguous
    interrogative. An ambiguous opener (do, how, which, can ...) needs the "?"."""
    m = " ".join((message or "").strip().split())
    if not m:
        return False
    if m.endswith("?"):
        return True
    return bool(_SURE_OPENERS.match(m))


def is_question_about(message: str, target: str = "") -> bool:
    """A question about the PENDING operation: it is a question, and it names the
    target (or its plural / "records" / "history" / "data"), points at it
    ("it", "that"), or asks what the operation does ("are you sure", "what
    happens", "how many are affected"). A REQUEST to do something else - even
    phrased as a question ("can you make the header blue?", "should I rename it?")
    - is not, and neither is a negation. An action word INSIDE a question about
    the operation ("what happens to preferred time if I change it?", "does it
    filter anything?") does not make it a request. In doubt: not about it."""
    m = " ".join((message or "").strip().split())
    if not is_question(m) or is_clear_no(m) or _REQUEST_FORM.search(m):
        return False
    low = m.lower()
    # A typo-bearing request ("cna you hide it insted?"): not an interrogative opener, not a consequence
    # question, and it names an action to DO - a request, so it clears. In doubt: clear.
    if not _SURE_OPENERS.match(m) and not _STRICT_CONSEQUENCE.search(low) and _DO_VERB.search(low):
        return False
    words = set(re.split(r"[^a-z0-9]+", low))
    squashed = re.sub(r"[^a-z0-9]", "", low)           # "preferred time" names preferredTime, however it is spelled
    parts = [re.sub(r"[^a-z0-9]", "", p.lower()) for p in re.split(r"[.\-> ]+", str(target or ""))]
    named = bool(_target_words(target) & words) or any(len(p) > 3 and (p in squashed or p.rstrip("s") in squashed) for p in parts)
    # a bare "why?" / "what?" / "really?" answers the thing just asked
    return named or bool(_PRONOUN.search(low)) or bool(_CONSEQUENCE.search(low)) or len(re.findall(r"[a-z0-9']+", low)) <= 2


_NEGATION = re.compile(r"^(?:no|nope|nah|n|do not|don'?t|dont|do nothing|never ?mind|stop|wait|hold on|hang on|cancel|leave it|"
                       r"keep it|not now|not yet|forget it|skip it|abort)\b", re.I)


def is_clear_no(message: str) -> bool:
    """A whole-message no: "no", "No, leave it", "do not remove it", "never mind".
    A negation followed by another instruction ("do not delete it, rename it")
    is not whole-message: it clears the confirmation and goes on to the rest."""
    m = " ".join((message or "").strip().lower().rstrip(".!").split())
    if m in _NO or m == NO_LABEL.lower():
        return True
    if not _NEGATION.match(m):
        return False
    return not re.search(r"[,;]\s*\S|\band then\b|\binstead\b|\bbut\b", m)


_NO = frozenset({"non", "nein", "nee", "नहीं", "नही", "لا", "いいえ", "不", "pas maintenant", "no gracias", "no", "n", "nope", "no thanks", "don't", "dont", "cancel", "leave it", "never mind",
                 "nevermind", "stop", "no, leave it", "do not", "do nothing", "wait", "hold on", "keep it", "not now"})


def remember(output_dir: str | Path, fp: str) -> None:
    try:
        path = _path(output_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        import time
        from services.smith.ordering import next_seq
        path.write_text(json.dumps({"fingerprint": fp, "at": time.time(), "seq": next_seq(output_dir)}, indent=2), "utf-8")
    except Exception as exc:  # noqa: BLE001 — a gate that cannot be written asks again
        logger.warning("[smith] could not record the pending confirmation: %s", exc)


def take(output_dir: str | Path) -> str:
    """The fingerprint awaiting a yes, removed as it is read."""
    try:
        raw = json.loads(_path(output_dir).read_text("utf-8"))
        fp = str((raw or {}).get("fingerprint") or "") if isinstance(raw, dict) else ""
    except FileNotFoundError:
        return ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("[smith] pending confirmation unreadable: %s", exc)
        fp = ""
    clear(output_dir)
    return fp


def clear(output_dir: str | Path) -> None:
    try:
        _path(output_dir).unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[smith] could not clear the pending confirmation: %s", exc)


def granted(output_dir: str | Path, message: str, verb: str, target: str) -> bool:
    """Whether THIS operation was described last turn and agreed to now."""
    return same_operation(take(output_dir), fingerprint(verb, target)) and is_yes(message, target)


def _norm_part(p: str, *, plural: bool = False) -> str:
    """Lower-case, no underscores or camel boundaries; a plural 's' is dropped
    ONLY for the entity part - Order.item and Order.items are different fields."""
    p = re.sub(r"[^a-z0-9]", "", p.lower())
    return p[:-1] if plural and len(p) > 3 and p.endswith("s") else p


def same_operation(a: str, b: str) -> bool:
    """The same verb on the same thing, however the model spelled it: case,
    underscores and a plural 's' do not make "Medicine.preferred_time" and
    "medicines.preferredTime" different operations."""
    if a == b:
        return True
    va, _, ta = (a or "").partition(":")
    vb, _, tb = (b or "").partition(":")
    if not va or va != vb:
        return False
    pa = [_norm_part(x, plural=(i == 0)) for i, x in enumerate(y for y in re.split(r"[.\-> ]+", ta) if y)]
    pb = [_norm_part(x, plural=(i == 0)) for i, x in enumerate(y for y in re.split(r"[.\-> ]+", tb) if y)]
    return bool(pa) and pa == pb


def pending_fingerprint(output_dir: str | Path) -> str:
    """The waiting confirmation's fingerprint, or "" (read, not taken)."""
    return str(_read(output_dir).get("fingerprint") or "") if waiting(output_dir) else ""


__all__ = ["decline_if_not_yes", "waiting", "MAX_AGE_S", "granted", "remember", "take", "clear", "is_yes", "fingerprint",
           "YES_LABEL", "NO_LABEL", "PENDING_PATH"]
