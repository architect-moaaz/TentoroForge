"""The owner's phrasebook, classified against the code rather than by hand.

The phrasebook is a list of sentences a business owner would type, each
coloured by what Smith does with it: acts, asks something back, answers with a
reason and changes nothing, or reaches nothing at all. Its closing section is
the list of sentences that reach nothing — and that list is the one part of the
document that cannot be maintained by hand, because it is a claim about what
the product CANNOT do and it is falsified the moment anyone adds a verb.

It had already gone stale. It named "Put it back how it was — no undo and no
restore point" while `services.smith.revert` was shipped and `VERB_HELP`
quoted the words "put it back" as an example of asking for it. A document that
says the product cannot do a thing it does is worse than no document.

SO THE COLOUR IS COMPUTED. The corpus beside this module holds the sentences
and, per sentence, two things that are properties OF THE SENTENCE and do not
move when the code moves: which verb or command it is asking for, and which of
that verb's facts the sentence itself states. Everything that moves — whether
the verb exists, what it now requires, whether it is dispatched to a handler or
answered with a reason — is read here, from the code, on every run.

The colour IS written back into the corpus, as `checked`, and nothing ever
reads it to decide anything. It is there to be contradicted: the test compares
it with what the code answers now and fails on a difference in either
direction, so a sentence newly answered and a verb that quietly stopped
answering one both arrive as a one-line diff rather than as a document nobody
noticed had gone false.

NO HEURISTICS, AND NOTHING TO EXEMPT. Nothing in this module guesses a verb
from words in a sentence; the corpus declares it and the code decides what
happens to it. If a sentence cannot be classified without an exception, that is
a finding about the verb set — `findings()` returns those rather than hiding
them — not a case to special-case here.

WHERE EACH FACT COMES FROM

* `verbs.REQUIRED_BY_VERB` — whether the verb exists and what it now needs.
  A slot added to a verb turns every sentence that does not state it from
  `acts` into `asks`, which is the "quietly stopped answering one" direction.
* `services.smith_session.SmithSession._iterate` — read as a syntax tree: which
  verbs reach a handler (they change the application), and which are answered
  where they are dispatched and change nothing. This is the only place that
  knows, and it knows it in control flow rather than in a table.
* `limits.cannot` / `limits.answer` — the verbs the code itself declares it
  recognises and cannot serve. Called, not copied.
* `verbs.VERB_HELP` and `understand_ask._PROMPT` — every sentence the code
  quotes as an example of asking for something. A sentence the phrasebook
  calls dead that the code now quotes is the exact shape of the revert
  staleness, caught by name.
* `routers.blueprint_generate` — the lifecycle commands and the build and
  verify consent gates, which are not verbs and were missing from every list
  built out of the verb table.

RUNNING IT

    python -m services.smith.phrasebook                   # section 08, as markdown
    python -m services.smith.phrasebook --report          # every sentence and its colour
    python -m services.smith.phrasebook --rewrite-checked # after an intended change

`tests/services/test_phrasebook.py` is what makes any of it load-bearing.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field as _dc_field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from services.smith import limits
from services.smith.verbs import REQUIRED_BY_VERB, VERB_HELP, missing_fields

#: The corpus. A data file, because the sentences are evidence: they are what
#: people actually typed, and rewording one into product language loses the
#: only thing it was collected for.
CORPUS_PATH = Path(__file__).with_name("phrasebook_corpus.yaml")

#: The module whose control flow decides what a verb does, and the method that
#: holds all of it. Named rather than searched: if either moves, this fails
#: loudly, which is the right way for a drift detector to meet a refactor.
DISPATCH_MODULE = Path(__file__).resolve().parents[1] / "smith_session.py"
DISPATCH_METHOD = "_iterate"

#: A sentence the code quotes as an example of asking for something. This is
#: `capabilities._EXAMPLE` — the code's own rule for "a quoted example long
#: enough to say what is meant" — and a test asserts the two stay identical.
#: The floor is what keeps `quoted_under` from matching a phrasebook sentence
#: on a word: "undo" is four characters and is inside a great many sentences.
_QUOTE = re.compile(r"[\"“]([^\"“”]{8,70})[\"”]")

#: Anything in quotation marks at all, however short. Used only for
#: PROVENANCE — whether a sentence marked `source: code` is still written in
#: the code, compared whole rather than by containment — because "undo" and
#: "go back" are real examples of asking for `revert` and are under the floor.
_ANY_QUOTE = re.compile(r"[\"“]([^\"“”]{1,80})[\"”]")

#: The four colours. `answers` is its own colour on purpose: a recognised ask
#: that is refused with a reason is neither a success nor a silent gap, and
#: scoring it as either is what made the hand-written list wrong in both
#: directions at once.
ACTS = "acts"
ASKS = "asks"
ANSWERS = "answers"
NOTHING = "nothing"


# ---------------------------------------------------------------------------
# What the dispatcher does with a verb, read from the dispatcher.
# ---------------------------------------------------------------------------

#: A verb reaches a handler that changes the application.
VIA_HANDLER = "handler"
#: A verb is answered where it is dispatched, with a reason, and returns.
VIA_DISPATCH_ANSWER = "dispatch-answer"
#: A verb the code declares it recognises and cannot serve (`limits.cannot`).
VIA_LIMIT = "limit"
#: A verb no branch returns for: it falls through to the move at the end of
#: the method, which edits the screen. `rename` and `remove` are these.
VIA_MOVE = "move"
#: A lifecycle word the router answers before any understanding runs.
VIA_COMMAND = "command"
#: A consent gate in the router: the words that start a build or a verify.
VIA_GATE = "gate"
#: No verb: nothing in the code takes this.
VIA_NONE = "none"


@dataclass(frozen=True)
class VerbFacts:
    """What the code currently does with one verb."""

    verb: str
    via: str
    #: The method the branch returns, when it returns one.
    handler: str = ""
    #: The verbs whose branch guards this one — for the report, not the logic.
    branch_line: int = 0


@dataclass(frozen=True)
class Classified:
    """One sentence, and what the code does with it today."""

    entry: dict[str, Any]
    category: str
    via: str
    #: Slots the verb needs that the sentence does not state.
    missing: tuple[str, ...] = ()
    #: Why, in one clause, when the category is not `acts`.
    because: str = ""

    @property
    def say(self) -> str:
        return str(self.entry.get("say") or "")

    @property
    def id(self) -> str:
        return str(self.entry.get("id") or "")


def _dispatch_tree() -> ast.FunctionDef:
    source = DISPATCH_MODULE.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == DISPATCH_METHOD:
            return node
    raise LookupError(
        f"{DISPATCH_MODULE.name} has no {DISPATCH_METHOD}: the dispatcher this "
        "reads has moved, and every classification below is guesswork until "
        "this points at it again.")


def _verbs_in_test(test: ast.expr) -> tuple[str, frozenset[str]]:
    """The verbs a branch condition selects, and how it selects them.

    `("eq" | "in", verbs)` for a branch about named verbs, `("ne", verbs)` for
    one that EXCLUDES them — the slot gate is written that way — and
    `("call:<name>", ())` for a branch guarded by a predicate, which is how
    the refusals are selected.
    """
    if isinstance(test, ast.Compare) and isinstance(test.left, ast.Name) \
            and test.left.id == "verb" and len(test.ops) == 1:
        op, comparator = test.ops[0], test.comparators[0]
        if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
            if isinstance(op, ast.Eq):
                return "eq", frozenset({comparator.value})
            if isinstance(op, ast.NotEq):
                return "ne", frozenset({comparator.value})
        if isinstance(op, ast.In) and isinstance(comparator, (ast.Tuple, ast.List, ast.Set)):
            return "in", frozenset(
                e.value for e in comparator.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str))
    if isinstance(test, ast.Call) and isinstance(test.func, ast.Name):
        return f"call:{test.func.id}", frozenset()
    return "", frozenset()


def _returned_handler(body: list[ast.stmt]) -> str:
    """The `self._x(...)` a branch RETURNS, or "".

    Returned, not merely called: `rebuild` calls `self._stale_plan_reason()`
    to decide which sentence to say, and saying a sentence is not doing the
    thing. What separates a verb that changes the application from one that
    explains why it will not is whether the turn's result IS a handler's.
    """
    for node in ast.walk(ast.Module(body=list(body), type_ignores=[])):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) \
                    and func.value.id == "self":
                return func.attr
    return ""


def _returns_result_literal(body: list[ast.stmt]) -> bool:
    for node in ast.walk(ast.Module(body=list(body), type_ignores=[])):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Call) \
                and isinstance(node.value.func, ast.Name) \
                and node.value.func.id == "TurnResult":
            return True
    return False


@lru_cache(maxsize=1)
def dispatch_facts() -> dict[str, VerbFacts]:
    """Every verb, and what the dispatcher does with it now.

    Read in source order, because the dispatcher is read in source order: the
    first branch for a verb that ALWAYS returns is the one that decides it.
    `remove_field` matches two branches — a confirmation gate that may return
    and the definition handler that always does — and it is the second that
    says what the verb is.
    """
    facts: dict[str, VerbFacts] = {}
    refused = frozenset(v for v in REQUIRED_BY_VERB if limits.cannot(v))
    for statement in _dispatch_tree().body:
        if not isinstance(statement, ast.If):
            continue
        how, verbs = _verbs_in_test(statement.test)
        if how not in ("eq", "in") or not verbs:
            continue
        if not isinstance(statement.body[-1], ast.Return):
            continue                     # may fall through; not decisive
        handler = _returned_handler(statement.body)
        for verb in verbs:
            if verb in facts:
                continue
            if handler:
                facts[verb] = VerbFacts(verb, VIA_HANDLER, handler, statement.lineno)
            elif _returns_result_literal(statement.body):
                facts[verb] = VerbFacts(verb, VIA_DISPATCH_ANSWER, "", statement.lineno)
    for verb in sorted(REQUIRED_BY_VERB):
        if verb in facts:
            continue
        # THE CODE'S OWN DECLARATION, CALLED. `limits.cannot` names the asks
        # it recognises and will not serve, and the branch that serves them is
        # guarded by that predicate rather than by the verb's name — so there
        # is nothing in the syntax tree to read, and the right thing to read
        # is the predicate.
        facts[verb] = VerbFacts(verb, VIA_LIMIT if verb in refused else VIA_MOVE)
    return facts


@lru_cache(maxsize=1)
def slot_gate_skips() -> frozenset[str]:
    """Verbs the dispatcher does NOT hold to `missing_fields` before acting.

    Written in the code as `if verb != "rename"`, because a rename's fields are
    enforced earlier, in the understanding. Read rather than assumed: a second
    verb added to that exemption changes what a bare sentence does, and the
    document would otherwise go on saying it asks.
    """
    for statement in _dispatch_tree().body:
        if not isinstance(statement, ast.If):
            continue
        how, verbs = _verbs_in_test(statement.test)
        if how == "ne" and any(
                isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "missing_fields"
                for node in ast.walk(statement)):
            return frozenset(verbs)
    return frozenset()


# ---------------------------------------------------------------------------
# The sentences the code itself quotes.
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    """A sentence reduced to the words in it, for comparing one to another."""
    return " ".join(re.sub(r"[^a-z0-9<>/]+", " ", (text or "").lower()).split())


@lru_cache(maxsize=2)
def _quoted(pattern_source: str) -> dict[str, tuple[str, ...]]:
    """Every sentence the code quotes, and the verbs it is quoted under.

    Two surfaces, because a sentence reaches a verb through either: the help
    text, which is what the chips offer and what `capabilities.nearest` ranks,
    and the understanding prompt, which is what the model reads when it picks
    a verb. A phrasebook sentence that appears in either is a sentence the
    code claims to serve.
    """
    from services.smith.understand_ask import _PROMPT

    pattern = re.compile(pattern_source)
    found: dict[str, set[str]] = {}

    def keep(quote: str, verb: str) -> None:
        # A quote with no words in it — a stray pair of quotation marks around
        # punctuation — normalises to nothing, and nothing is contained in
        # every sentence. Dropped here rather than guarded at every use.
        said = _normalise(quote)
        if said:
            found.setdefault(said, set()).add(verb)

    for verb, help_text in VERB_HELP.items():
        for quote in pattern.findall(help_text):
            keep(quote, verb)
    # WRAPPED, THEN READ AS ONE LINE. The prompt is a wrapped string literal,
    # so half its examples are split across a line break and eleven spaces of
    # indent — "I cannot see fathersName on the registration\n     page" is
    # over seventy characters and was silently not an example at all.
    prompt = " ".join(_PROMPT.split())
    # The prompt names each verb and then quotes examples of it, in that
    # order, so a quote belongs to the last verb named before it.
    verb_at: list[tuple[int, str]] = []
    for verb in REQUIRED_BY_VERB:
        for hit in re.finditer(rf'"{re.escape(verb)}"', prompt):
            verb_at.append((hit.start(), verb))
    verb_at.sort()
    for hit in pattern.finditer(prompt):
        owner = ""
        for position, verb in verb_at:
            if position < hit.start():
                owner = verb
            else:
                break
        if owner:
            keep(hit.group(1), owner)
    return {sentence: tuple(sorted(verbs)) for sentence, verbs in found.items()}


def quoted_examples() -> dict[str, tuple[str, ...]]:
    """Every sentence the code quotes as an EXAMPLE, and its verbs."""
    return _quoted(_QUOTE.pattern)


def quoted_verbatim(say: str) -> tuple[str, ...]:
    """The verbs whose text contains this sentence WHOLE, or ().

    Provenance, not routing: it answers "is this sentence still written in the
    code?" for the half of the corpus that was copied out of it.
    """
    return _quoted(_ANY_QUOTE.pattern).get(_normalise(say), ())


#: A quote has to be a PHRASE before one sentence containing it means
#: anything. `import_data`'s help says the record kind it needs is a word like
#: "customers", and nine characters clears the length floor — so every
#: phrasebook sentence with the word customers in it was read as a sentence the
#: code quotes. A word is a value; three words is a way of asking. Exact
#: matches are exempt because they are the whole sentence however short it is
#: ("undo", "go back").
MIN_PHRASE_WORDS = 3


def quoted_under(say: str) -> tuple[str, ...]:
    """The verbs whose examples include this sentence, or ().

    Two ways in. The code quotes the sentence WHOLE — "undo" is the whole of
    what someone typed. Or the code quotes the PHRASE inside it that names the
    ask: the phrasebook's sentence is "Put it back how it was" and `revert`'s
    help quotes "put it back".
    """
    said = _normalise(say)
    if not said:
        return ()
    hits: set[str] = set()
    for quote, verbs in quoted_examples().items():
        if quote == said:
            hits.update(verbs)
        elif len(quote.split()) >= MIN_PHRASE_WORDS and (quote in said or said in quote):
            hits.update(verbs)
    return tuple(sorted(hits))


# ---------------------------------------------------------------------------
# The commands and gates that are not verbs.
# ---------------------------------------------------------------------------

#: The router module that answers the lifecycle words and holds the consent
#: gates. Named for the same reason `DISPATCH_MODULE` is.
ROUTER_MODULE = Path(__file__).resolve().parents[2] / "routers" / "blueprint_generate.py"


@lru_cache(maxsize=1)
def commands() -> dict[str, str]:
    """Each lifecycle word, and whether the router answers it.

    Not verbs — `status`, `preview`, `export`, `deploy` and `help` are answered
    before any understanding runs — and they were missing from every capability
    list built out of the verb table. `deploy` is among them and is a refusal,
    which is why it counts as answered rather than as a gap.

    Read from the router the same way the dispatcher is read, because the list
    of words (`_LIFECYCLE_VERBS`) and the branches that answer them are two
    different places and have already disagreed: `define` and `approve` are
    declared commands with no branch at all.
    """
    from routers import blueprint_generate as bg

    answered: set[str] = set()
    for node in ast.walk(ast.parse(ROUTER_MODULE.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.If):
            continue
        how, words = _verbs_in_test(node.test)
        if how == "eq" and words and isinstance(node.body[-1], ast.Return):
            answered |= set(words)
    return {word: (ANSWERS if word in answered else NOTHING)
            for word in sorted(bg._LIFECYCLE_VERBS)}


@lru_cache(maxsize=1)
def gates() -> dict[str, Any]:
    """The typed sentences the router takes as consent rather than as a change.

    A build and a verify are started by pressing a card, and a person types the
    words instead. Each gate here is the router's OWN predicate, called with
    the sentence — nothing is re-implemented, so a phrase added to the consent
    set is taken by this on the same day it is taken by the product. Each
    returns the colour, or ``None`` when the gate does not take the sentence.
    """
    from routers import blueprint_generate as bg

    def build(message: str) -> str | None:
        return ACTS if bg._is_build_consent(message) else None

    def verify(message: str) -> str | None:
        if not bg._is_verify_consent(message):
            return None
        # THE SCOPE IS ASKED BEFORE IT IS SPENT. A verify that names no scope
        # is answered with the question and its three options; one that names
        # a scope runs. Both are the gate taking the sentence.
        chosen = bg._verify_scope(message) is not None or bg._scope_was_chosen(message)
        return ACTS if chosen else ASKS

    def declined(message: str) -> str | None:
        said = " ".join((message or "").strip().lower().rstrip(".!").split())
        return ANSWERS if said in bg._DECLINED else None

    return {"build_consent": build, "verify_consent": verify, "declined": declined}


@lru_cache(maxsize=1)
def move_requires() -> frozenset[str]:
    """What the move at the end of the dispatcher asks for before it runs.

    `rename` is the one verb the slot gate is skipped for, so the only thing
    standing between a bare "rename it" and an edit is the dispatcher's own
    `if not target_file: ... status="asked"`. Read, so that a sentence naming
    no screen is coloured the way the product colours it.
    """
    wanted: set[str] = set()
    for statement in _dispatch_tree().body:
        if not isinstance(statement, ast.If):
            continue
        test = statement.test
        if not (isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)
                and isinstance(test.operand, ast.Name)):
            continue
        for node in ast.walk(statement):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "TurnResult" \
                    and any(kw.arg == "status"
                            and getattr(kw.value, "value", "") == "asked"
                            for kw in node.keywords):
                wanted.add(test.operand.id)
    return frozenset(wanted)


# ---------------------------------------------------------------------------
# Classifying one sentence.
# ---------------------------------------------------------------------------

def classify(entry: dict[str, Any]) -> Classified:
    """What the code does with this sentence today."""
    reaches = entry.get("reaches") or {}
    states = tuple(reaches.get("states") or ())
    say = str(entry.get("say") or "")

    if "verb" in reaches:
        return _classify_verb(entry, str(reaches["verb"]), states)

    if "command" in reaches:
        word = str(reaches["command"])
        how = commands().get(word)
        if how is None:
            return Classified(entry, NOTHING, VIA_NONE,
                              because=f"`{word}` is not a lifecycle command any more")
        if how == NOTHING:
            return Classified(entry, NOTHING, VIA_NONE,
                              because=f"`{word}` is declared a command and answered nowhere")
        return Classified(entry, ANSWERS, VIA_COMMAND,
                          because=f"answered by the `{word}` command")

    if "gate" in reaches:
        name = str(reaches["gate"])
        gate = gates().get(name)
        if gate is None:
            return Classified(entry, NOTHING, VIA_NONE,
                              because=f"the {name} gate no longer exists")
        colour = gate(say)
        if colour is None:
            return Classified(entry, NOTHING, VIA_NONE,
                              because=f"the {name} gate no longer takes these words")
        return Classified(entry, colour, VIA_GATE, because=f"taken by the {name} gate")

    # Declared as reaching nothing. The claim is only worth making while the
    # code does not contradict it, and the contradiction that has actually
    # happened is the code quoting the sentence as an example of a verb.
    said_by = quoted_under(say)
    if said_by:
        return Classified(
            entry, ANSWERS if all(limits.cannot(v) for v in said_by) else ACTS,
            VIA_HANDLER,
            because=("the code now quotes this sentence as an example of "
                     + ", ".join(f"`{v}`" for v in said_by)))
    for name, gate in gates().items():
        colour = gate(say)
        if colour is not None:
            return Classified(entry, colour, VIA_GATE,
                              because=f"the {name} gate now takes these words")
    return Classified(entry, NOTHING, VIA_NONE,
                      because=str(entry.get("because") or ""))


def _classify_verb(entry: dict[str, Any], verb: str, states: tuple[str, ...]) -> Classified:
    if verb not in REQUIRED_BY_VERB:
        return Classified(entry, NOTHING, VIA_NONE,
                          because=f"`{verb}` is not a verb any more")
    understanding = _understanding(verb, states)
    gaps = tuple(missing_fields(understanding))
    gated = gaps if verb not in slot_gate_skips() else ()
    facts = dispatch_facts()[verb]
    # THE MOVE ASKS FOR ITSELF. `rename` is the verb the slot gate is skipped
    # for, so what stops a sentence naming no screen is the move's own check.
    if facts.via == VIA_MOVE:
        gated = gated or tuple(sorted(move_requires() - set(states)))
    if gated:
        return Classified(entry, ASKS, VIA_NONE, missing=gated,
                          because="the sentence does not state "
                                  + ", ".join(f"`{g}`" for g in gated))
    if facts.via == VIA_LIMIT:
        said, _options = limits.answer(verb, understanding, {})
        if not said:
            return Classified(entry, NOTHING, VIA_NONE, missing=gaps,
                              because=f"`{verb}` is declared a refusal and answers nothing")
        return Classified(entry, ANSWERS, VIA_LIMIT, missing=gaps,
                          because=f"`{verb}` is answered with a reason and changes nothing")
    if facts.via == VIA_DISPATCH_ANSWER:
        return Classified(entry, ANSWERS, VIA_DISPATCH_ANSWER, missing=gaps,
                          because=f"`{verb}` is answered where it is dispatched "
                                  "and changes nothing")
    return Classified(entry, ACTS, facts.via, missing=gaps)


def _understanding(verb: str, states: tuple[str, ...]) -> dict[str, Any]:
    """An understanding carrying exactly the facts the sentence states.

    `limits.answer` reads the slots to name the thing it is refusing, so it is
    handed the same slots the sentence supplies rather than a blank dict —
    otherwise a refusal that could not be worded would read as no refusal.
    """
    out: dict[str, Any] = {slot: f"the {slot}" for slot in states}
    out["verb"] = verb
    return out


# ---------------------------------------------------------------------------
# The corpus.
# ---------------------------------------------------------------------------

def document(path: Path | None = None) -> dict[str, Any]:
    """The corpus file, whole — the sentences and the open findings."""
    return yaml.safe_load((path or CORPUS_PATH).read_text(encoding="utf-8")) or {}


def corpus(path: Path | None = None) -> list[dict[str, Any]]:
    """Every sentence, in the order the document says them."""
    return list(document(path).get("sentences") or [])


def recorded_findings(path: Path | None = None) -> set[tuple[str, tuple[str, ...]]]:
    """The defects in the verb set the corpus says are open today."""
    return {(str(f.get("about")), tuple(f.get("verbs") or ()))
            for f in document(path).get("open_findings") or []}


def checked_line(row: Classified) -> str:
    """One sentence's colour, as the corpus writes it down."""
    bits = [f"colour: {row.category}", f"via: {row.via}"]
    if row.missing:
        bits.append("missing: [" + ", ".join(row.missing) + "]")
    return "    checked: {" + ", ".join(bits) + "}"


def rewrite_checked(path: Path | None = None) -> int:
    """Put today's colours back into the corpus, leaving everything else alone.

    The corpus is edited as TEXT, not round-tripped through the loader: the
    comments beside the sentences are half of what the file is for, and a
    dump would throw them away.
    """
    target = path or CORPUS_PATH
    by_id = {row.id: row for row in classified(target)}
    out: list[str] = []
    current = ""
    for line in target.read_text(encoding="utf-8").splitlines():
        marker = re.match(r"  - id: (\S+)\s*$", line)
        if marker:
            current = marker.group(1)
        if line.startswith("    checked: ") and not current:
            continue                   # replaced already, drop the stale one
        out.append(line)
        if current and line.startswith("    say: "):
            out.append(checked_line(by_id[current]))
            current = ""
    target.write_text("\n".join(out) + "\n", encoding="utf-8")
    return len(by_id)


def classified(path: Path | None = None) -> list[Classified]:
    return [classify(entry) for entry in corpus(path)]


# ---------------------------------------------------------------------------
# What the verb set itself says, when it is read as a whole.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Finding:
    """Something true of the verb set that no sentence can be blamed for."""

    about: str
    said: str
    verbs: tuple[str, ...] = _dc_field(default_factory=tuple)


def findings(path: Path | None = None) -> list[Finding]:
    """Everything wrong with the verb set that a sentence would need an
    exception to paper over.

    This is where an exception would have gone. A classification that only
    works if one verb is excused is not a special case, it is a defect in the
    verb set, and it is reported here under its own name.
    """
    from services.smith import capabilities
    from services.smith.understand_ask import _PROMPT

    out: list[Finding] = []

    unchosen = tuple(sorted(v for v in REQUIRED_BY_VERB if f'"{v}"' not in _PROMPT))
    if unchosen:
        out.append(Finding(
            "verb the model is never offered",
            "in the verb table and not named in the understanding prompt, so "
            "nothing can ever be classified as it",
            unchosen))

    unhelped = tuple(sorted(set(REQUIRED_BY_VERB) - set(VERB_HELP)))
    if unhelped:
        out.append(Finding("verb with no help text",
                           "the tool description does not describe it", unhelped))

    ungrouped = tuple(sorted(capabilities.unaccounted()))
    if ungrouped:
        out.append(Finding("verb no capability group mentions",
                           "\"what can you do?\" does not say it exists", ungrouped))

    facts = dispatch_facts()
    answered_off_table = tuple(sorted(
        v for v, f in facts.items()
        if f.via == VIA_DISPATCH_ANSWER and not limits.cannot(v)))
    if answered_off_table:
        out.append(Finding(
            "verb refused outside the refusal table",
            "answered with a reason and changing nothing, but absent from "
            "`limits.cannot`, so every list built from that table advertises "
            "it as something the chat can do",
            answered_off_table))

    taken = tuple(sorted(
        word for word, how in commands().items()
        if how == NOTHING and all(gate(word) is None for gate in gates().values())))
    if taken:
        out.append(Finding(
            "command declared and answered nowhere",
            "named in `_LIFECYCLE_VERBS`, so it is excluded from being read as "
            "an edit, and no branch answers it and no gate takes it — typed on "
            "its own it reaches the architect as a change to reason about",
            taken))

    covered = {str((e.get("reaches") or {}).get("verb")) for e in corpus(path)}
    uncovered = tuple(sorted(set(REQUIRED_BY_VERB) - covered))
    if uncovered:
        out.append(Finding("verb no sentence exercises",
                           "nothing in the phrasebook asks for it, so the "
                           "document cannot say what it does", uncovered))
    return out


def contract_gaps() -> list[Finding]:
    """Verbs whose required slots and prompted slots are different sets.

    `REQUIRED_BY_VERB["rename"]` demands `current_behavior` and
    `desired_behavior`; the prompt asks the model for `new_value`, which the
    table does not list, and never mentions the other two. Today it is
    harmless only because the dispatcher skips the slot gate for exactly that
    verb — which is the exemption `slot_gate_skips` reads, and the reason this
    is reported rather than worked around.
    """
    from services.smith.understand_ask import SHAPE

    out: list[Finding] = []
    for verb in sorted(slot_gate_skips()):
        unasked = tuple(sorted(REQUIRED_BY_VERB.get(verb, set()) - set(SHAPE)))
        if unasked:
            out.append(Finding(
                "required slot the understanding cannot carry",
                f"`{verb}` requires " + ", ".join(f"`{s}`" for s in unasked)
                + ", which is not a field of an understanding — so the slot "
                  "gate is skipped for it rather than never passing",
                (verb,)))
    return out


# ---------------------------------------------------------------------------
# Section 08.
# ---------------------------------------------------------------------------

SECTION_08_TITLE = "08 · The sentences that reach nothing today"


def section_08(path: Path | None = None) -> str:
    """The closing section of the phrasebook, as markdown, from the code.

    Generated so it is true on the day it is read. A sentence leaves this list
    the moment something takes it, and nobody has to remember to strike it.
    """
    rows = [c for c in classified(path) if c.category == NOTHING]
    lines = [f"## {SECTION_08_TITLE}", ""]
    if not rows:
        lines += ["Nothing in the phrasebook reaches nothing. Every sentence "
                  "collected is acted on, asked about, or answered with a "
                  "reason.", ""]
        return "\n".join(lines)
    lines += [
        f"{len(rows)} of {len(corpus(path))} sentences reach nothing: no verb "
        "recognises them, no command answers them, and no gate takes them. "
        "They are not refusals — a refusal says why. These fall to “I did "
        "not recognise that as something I can do”.",
        "",
    ]
    for gap, group in _by_gap(rows):
        lines += [f"**{gap}**", ""]
        for row in group:
            because = row.because or row.entry.get("because") or ""
            lines.append(f"- “{row.say}”" + (f" — {because}" if because else ""))
        lines.append("")
    answered = [c for c in classified(path) if c.category == ANSWERS and c.via == VIA_LIMIT]
    if answered:
        lines += [
            "**Recognised, and refused with a reason.** These are not in the "
            "list above: the application does not change, but the person is "
            "told why and offered the nearest thing that works.",
            "",
        ]
        lines += [f"- “{row.say}” — {row.because}" for row in answered]
        lines.append("")
    return "\n".join(lines)


def _by_gap(rows: list[Classified]) -> list[tuple[str, list[Classified]]]:
    order: list[str] = []
    grouped: dict[str, list[Classified]] = {}
    for row in rows:
        gap = str(row.entry.get("gap") or "Unsorted")
        if gap not in grouped:
            order.append(gap)
            grouped[gap] = []
        grouped[gap].append(row)
    return [(gap, grouped[gap]) for gap in order]


def report(path: Path | None = None) -> str:
    """Every sentence and its colour, plus what the verb set itself says."""
    rows = classified(path)
    tally: dict[str, int] = {}
    for row in rows:
        tally[row.category] = tally.get(row.category, 0) + 1
    lines = [f"{len(rows)} sentences: " + ", ".join(
        f"{tally.get(c, 0)} {c}" for c in (ACTS, ASKS, ANSWERS, NOTHING)), ""]
    for row in rows:
        lines.append(f"  {row.category:8} {row.via:15} {row.say}")
    every = findings(path) + contract_gaps()
    if every:
        lines += ["", "Findings about the verb set:"]
        for finding in every:
            lines.append(f"  - {finding.about}: {finding.said}"
                         + (f" — {', '.join(finding.verbs)}" if finding.verbs else ""))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", action="store_true",
                        help="every sentence and its colour, not just section 08")
    parser.add_argument("--rewrite-checked", action="store_true",
                        help="write today's colours back into the corpus")
    parser.add_argument("--corpus", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.rewrite_checked:
        print(f"{rewrite_checked(args.corpus)} sentences re-checked")
        return 0
    print(report(args.corpus) if args.report else section_08(args.corpus))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
