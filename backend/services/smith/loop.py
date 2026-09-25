"""The change turn as a loop: act, observe, act again (S1, `2026-09-24-smith-as-a-loop`).

A turn used to be one interpretation and one move. The model said what the
message meant, deterministic code did it, and the turn ended — so the model
never saw the result of its own change. Two failures follow from that and only
from that:

* "yes please" to Smith's own offer to build a dashboard came back as "I looked
  at what you asked and I don't see anything to change" (`docs/SMITH-VERBS.md`).
  The move reported nothing; nothing read the report.
* "Add a phone number, show it on the form and make it required" did the
  biggest one and dropped the rest, which is why `services.smith.plan` exists.

What this adds is a second look, and only that. **Every step is an existing
verb, executed by the existing seam, through the existing capability check** —
:mod:`services.smith.tools` generates the catalogue from `REQUIRED_BY_VERB`, so
there is no verb here that the dispatcher did not already have. The loop
chooses the next step; it does not widen what may be chosen, and it writes
nothing itself.

WHY THIS IS NOT THE REPAIR CHAIN COMING BACK
--------------------------------------------
The rebuild exists because a 151-pass chain mapped bad output onto plausible
output with no oracle. Iterating on a VERIFIED result is a different thing, and
the project already does it in three places: `ui_engineer` sends compiler errors
back to the page's author (`COMPILE_ROUNDS`), `observer` judges a node and
re-briefs the agent that owns it, `build_repair` returns a failing proof to the
step that owns it (`REPAIR_ROUNDS`). Each has something that can say "no" for a
reason that is not a guess.

The change turn has one too and throws it away: `smith_session` snapshots git
before the move and asks git what actually changed — then uses the finding as a
pass/fail gate and ends the turn on it. Here it becomes an observation. "The
diff did not touch the file you named" is exactly the sentence that makes a
model try the other reading.

Bounded like the others, by :data:`MAX_STEPS`, and what the cap cuts off is
SAID rather than dropped. A cap of 1 is the behaviour that shipped before this
file existed, which is the comparison S1 is for.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from services.smith import tools

logger = logging.getLogger(__name__)

#: How many steps one turn may take. Twelve since the loop can read (S2): a
#: turn that looks before it acts spends two or three steps looking, the
#: longest real multi-ask in a UAT replay is four, and a step re-tried under a
#: different reading costs two. The other loops in the tree cap at 2 and 3; a
#: turn is the one place a person is waiting, so it is not unbounded here
#: either.
MAX_STEPS = 12

#: How many observations the model is shown. The whole turn, in practice —
#: this is a ceiling against a cap that someone later raises.
WINDOW = 12


@dataclass
class Observation:
    """What one step did, in the words the seam used.

    `said` is the seam's own answer. Nothing paraphrases it on the way in: a
    step that reported "I looked for the delete button and could not find it"
    is worth exactly its own sentence to whatever picks next.
    """
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    status: str = ""                       # resolved | no_op | asked | needs_user | error
    said: str = ""
    touched: list[str] = field(default_factory=list)

    def line(self) -> str:
        args = ", ".join(f"{k}={v!r}" for k, v in sorted(self.args.items()) if v)
        head = f"{self.tool}({args})" if args else f"{self.tool}()"
        files = f" [touched: {', '.join(self.touched[:3])}]" if self.touched else ""
        # WHAT WAS READ IS SHOWN AS READ. A file's lines collapsed to one would
        # be a file the model cannot reason from; the read's own layout stays.
        if self.status == "read":
            return f"- {head} ->\n{self.said}"
        return f"- {head} -> {self.status or '?'}: {' '.join((self.said or '').split())}{files}"


#: A step is identified by the fields its verb DECLARES it needs — the same set
#: `missing_fields` holds it to. Projecting onto them is what lets the turn's
#: first step, which carries a whole understanding, be compared with a later
#: one, which carries a tool call; and it keeps the check from depending on
#: fields neither the verb nor the user ever named.
def _identity(tool: str, args: dict) -> str:
    from services.smith.verbs import REQUIRED_BY_VERB

    required = REQUIRED_BY_VERB.get(tool)
    keys = sorted(required) if required else sorted(args or {})
    shown = {k: (args or {}).get(k) for k in keys if (args or {}).get(k)}
    return json.dumps([tool, shown], sort_keys=True, default=str)


def already_done(tool: str, args: dict, observations: list[Observation]) -> bool:
    """Whether this exact call has already been made this turn.

    An identity check, not a policy about which verbs may repeat: `add_field`
    twice with different fields is two steps, `add_field` twice with the same
    one is the model not reading its own observation.
    """
    want = _identity(tool, args)
    return any(_identity(o.tool, o.args) == want for o in observations)


_PROMPT = """You are changing an application someone owns. Decide the NEXT \
step, or end the turn. The steps already taken this turn, if any, are below.

THE CONVERSATION SO FAR:
{history}

WHAT THEY ASKED, in their words:
{ask}

The ask is often a word — "yes please", "go ahead" — and means nothing without
the exchange above it. Read what it is answering before deciding anything. If
the two together still do not say what is wanted, `ask_user`; do not pick a
subject out of the application below and act as though they raised it.

WHAT THE APPLICATION IS, as much of it as is relevant:
{ctx}

WHAT HAS HAPPENED SO FAR THIS TURN:
{observations}

Return ONLY a JSON object with exactly these keys:

  "tool": the name of ONE tool from the list below, or `done`, `answer` or
      `ask_user` to end the turn. A name that is not in the list is an error
      and costs a step.
  "args": an object with that tool's arguments. Only the ones it lists.
  "why": one short sentence, for the person, saying what this step is for.

HOW TO DECIDE

SPEAK THE PERSON'S LANGUAGE. To them it is "your application", "the app",
"what I know about it" — never "the Blueprint", "a section", "a node", "an
agent", "the slice", "the catalogue", or an id like PAGE-014 unless they used
it first. Those names are for tool calls, not replies. "The Blueprint does not
cover that" is a sentence they cannot act on; "that is not something your
application handles" is.

LOOK BEFORE YOU ACT when the application above does not show you what you
need. The context is a slice, not the whole; `read_page_code` shows what a
screen actually runs, `grep` finds where a word appears in the code,
`read_section` opens any part of the Blueprint, `find` turns a name into an
id. A change made to something you have not looked at is a guess. Reading
costs a step; guessing costs the change.

CHANGE CODE FROM WHAT YOU READ. When the ask is a change no verb below
describes — a rule the screen applies, what a control does, the order things
appear in — read the page, then `write_page_code` with a brief that names the
change in the code's own terms: the constant, the component, the line. The
compiler's verdict comes back as an observation; a page that did not compile
is a brief to sharpen, not a reason to stop.

A step that reported it changed nothing is INFORMATION, not a reason to repeat
it. "I looked for X and could not find it" means X is not what it is called, or
the change belongs to a different tool — read what the observation actually
said and pick accordingly. The same tool with the same arguments twice is
refused.

A step that reported the wrong file was edited, or that the diff did not touch
what you named, is the same kind of information: the ask was right and the
target was wrong.

END WITH `done` when every part of what they asked for is covered by a step
above that reported it landed. Do not end while a part of their message has
had no step at all — and do not invent one either: if a part needs a fact
nobody has said, `ask_user` for exactly that fact.

A QUESTION ALREADY ASKED ABOVE WAS ASKED FROM THE SLICE ALONE. "Does the
page already have X?", "which file is it in?", "what is it called?" — the
code answers these. Read, then act. Ask the person only for what nothing in
the application can tell you, and then ask exactly that.

WHAT NON-TECHNICAL OWNERS ACTUALLY SAY, and how to read it:
- EVERY ask, the layout ones too: "grid view with images", "make it scrollable", "a home page listing the tools" are asks, each about a screen — name the screen in the ask. SEVERAL ASKS ABOUT ONE SCREEN ARE ONE STEP: "grid view, with the photo, the name as 'Product', the description and the area" on Discover is one ask about Discover, not four — so a long message fits the list and nothing falls off its end. Data-model changes come before the screens that show them. A step is a change still to make: what the Blueprint already has (a field that exists) is not a step. "Good visuals", "look nicer", "with images" on a screen are asks about what that screen SHOWS (photos, cards) — part of that screen's step, not a restyle; a restyle is only for named colours, fonts or an overall look. A long message that is hard to follow is still a list of asks; list what you can read and ask about the rest, rather than answering that you did not follow. WHAT A SCREEN CALLS A THING IS NOT WHAT THE DATA MODEL CALLS IT. "The title should be named as product", "call them products on the page" are the WORDING on screens — never a rename of the entity, which rewrites the data, the processes and every page. Only an explicit "the records should be called X in the data" is that. WHAT THE APPLICATION CANNOT DO IS SAID, NOT DROPPED. It cannot fetch pictures or facts from the internet: photos come from the people who list things (an image field they upload to). Say so in `clarification_needed` and offer the nearest thing; do not silently leave the ask out. It CAN take a person's current location: a `location` field ({{lat, lng}}, shared from the browser) and distances ("0.4 mi away") in place of coordinates — latitude and longitude fields are replaced by one `location` field plus an area name. "clarification_options": when the question offers CHOICES, the choices as short labels, 2 to 5, each a complete answer on its own that they can pick with one click — ["A new page of its own", "A panel on the screen they named", "Both"]. Draw them from THIS application: a choice between screens names its own screens and their routes. Put the choices here rather than spelling them out in the question; the question then asks. [] when the question is open (a name, a URL, a value). "verb": WHICH KIND OF CHANGE this is. Exactly one of:
- WHAT A SCREEN CALLS A THING IS NOT WHAT THE DATA MODEL CALLS IT. "The title should be named as product", "call them products on the page" are the WORDING on screens — never a rename of the entity, which rewrites the data, the processes and every page. Only an explicit "the records should be called X in the data" is that. WHAT THE APPLICATION CANNOT DO IS SAID, NOT DROPPED. It cannot fetch pictures or facts from the internet: photos come from the people who list things (an image field they upload to). Say so in `clarification_needed` and offer the nearest thing; do not silently leave the ask out. It CAN take a person's current location: a `location` field ({{lat, lng}}, shared from the browser) and distances ("0.4 mi away") in place of coordinates — latitude and longitude fields are replaced by one `location` field plus an area name. "clarification_options": when the question offers CHOICES, the choices as short labels, 2 to 5, each a complete answer on its own that they can pick with one click — ["A new page of its own", "A panel on the screen they named", "Both"]. Draw them from THIS application: a choice between screens names its own screens and their routes. Put the choices here rather than spelling them out in the question; the question then asks. [] when the question is open (a name, a URL, a value). "verb": WHICH KIND OF CHANGE this is. Exactly one of:
- WHAT THE APPLICATION CANNOT DO IS SAID, NOT DROPPED. It cannot fetch pictures or facts from the internet: photos come from the people who list things (an image field they upload to). Say so in `clarification_needed` and offer the nearest thing; do not silently leave the ask out. It CAN take a person's current location: a `location` field ({{lat, lng}}, shared from the browser) and distances ("0.4 mi away") in place of coordinates — latitude and longitude fields are replaced by one `location` field plus an area name. "clarification_options": when the question offers CHOICES, the choices as short labels, 2 to 5, each a complete answer on its own that they can pick with one click — ["A new page of its own", "A panel on the screen they named", "Both"]. Draw them from THIS application: a choice between screens names its own screens and their routes. Put the choices here rather than spelling them out in the question; the question then asks. [] when the question is open (a name, a URL, a value). "verb": WHICH KIND OF CHANGE this is. Exactly one of:
- WRONG BEHAVIOUR IS NOT A CRASH. "After login it takes me to the signup page", "the button goes to the wrong screen", "the list is empty" — the app did something other than they expected, without an error. That is NOT explain_crash: put in `answer` what the application is defined to do there (the Accounts section says where signing in and signing up land; the workflows say what each button runs), whether that matches what they saw, and what can be changed — and if the definition is right but they saw otherwise, say that a page review ("verify & fix") signs in and checks it.

BEFORE THERE IS AN APPLICATION the page above says so. Then the verbs do not
apply: `open_decisions` says what the brief leaves unsaid; ask ONE open
decision per turn with `ask_user` and its options as chips; when it says the
brief stands on its own, `define_application`. Defining runs a dozen agents
and costs minutes, so do not define twice in a turn, and do not define what
a question would change.

A CREDENTIAL IS NEVER A VALUE IN A CALL. `token_env` and `key_env` take the
NAME of an environment variable — `FIGMA_TOKEN`, `UXPILOT_API_KEY` — never
the secret. A pasted Figma token (`figd_…`) or UX Pilot key (`ep_…`) is the
person answering the wrong question: do not pass it on; `ask_user` for the
variable's name, and say that what they typed is written to the conversation
and must not be a secret.

SEVERAL ASKS IN ONE MESSAGE ARE A PLAN, NOT A GUESS ABOUT WHICH ONE. "Add a
phone number, show it on the form and make it required" is three; end the
turn with `propose_plan` and every ask in their words, and they agree once.
One thing asked for in several words is not a plan: "rename the delete
button to archive" is one step. A yes to a plan already shown is not a plan.

END WITH `answer` when they asked a question rather than for a change, or when
the honest outcome is that nothing needed doing. AN ANSWER ALREADY GIVEN ABOVE
WAS WRITTEN FROM THE SLICE ALONE. If the question is about what the code does
— which rows a screen shows, what a button runs, what a value is mapped to —
the slice cannot say and the code can: `read_page_code` or `grep`, then
`answer` from what you read. An answer that amounts to "I cannot see that
part of the application" is the signal to look, not the end.

Do not describe work in "why" that no step above performed.

THE TOOLS

{catalogue}
"""


def _render(observations: list[Observation]) -> str:
    if not observations:
        return "(nothing yet — this is the first step)"
    return "\n".join(o.line() for o in observations[-WINDOW:])


def next_step(ask: str, ctx: str, observations: list[Observation],
              history: list | None = None, *,
              provider: Callable[[str], str] | None = None,
              reasoning: Callable[[str], None] | None = None) -> dict[str, Any]:
    """The next step, or a terminal move. Never raises.

    `history` is the exchange, rendered the way `understand_ask` renders it.
    Step one gets it and the steps after it did not, so a turn whose ask was
    "yes please" reached this function with the word alone and no idea what it
    answered. It filled the gap from the Blueprint slice and answered a
    question about identity documents that nobody had asked.

    An unreachable or unparseable model ends the turn on what has already
    landed rather than failing it: the steps above this one are real changes
    that were verified when they were made, and throwing the turn away would
    not unmake them.
    """
    from services.smith.understand_ask import (_default_provider, _parse,
                                                _render_history)

    call = provider or (lambda prompt: _default_provider(prompt, reasoning))
    try:
        raw = call(_PROMPT.format(ask=(ask or "").strip(),
                                  history=_render_history(history),
                                  ctx=ctx or "(nothing yet)",
                                  observations=_render(observations),
                                  catalogue=tools.render()))
    except Exception:  # noqa: BLE001 — a turn degrades, it does not crash
        logger.warning("smith loop: provider unreachable; ending the turn")
        return {"tool": "done", "args": {},
                "why": "I could not reach my reasoning service for the next step."}

    data = _parse(raw)
    if data is None:
        logger.warning("smith loop: unparseable next step; ending the turn")
        return {"tool": "done", "args": {}, "why": ""}

    tool = str(data.get("tool") or "").strip()
    args = data.get("args")
    return {
        "tool": tool,
        "args": args if isinstance(args, dict) else {},
        "why": str(data.get("why") or "").strip(),
    }


def remaining_note(observations: list[Observation], *, capped: bool) -> str:
    """What the cap cut off, said rather than dropped.

    `build_repair` ends the same way — what is still wrong after the rounds is
    recorded as an issue of the application rather than quietly left.
    """
    if not capped:
        return ""
    return ("\n\nI stopped after "
            f"{MAX_STEPS} steps in one turn. Tell me what is still missing and "
            "I will carry on from there.")


__all__ = ["MAX_STEPS", "WINDOW", "Observation", "already_done", "next_step",
           "remaining_note"]
