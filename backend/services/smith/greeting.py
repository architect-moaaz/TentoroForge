"""What Smith says before the user says anything — §6, §107 step 1.

§107's first step is Smith welcoming the user and suggesting what to build, and
Smith could not: :meth:`Smith.turn` is one user message in, one turn out, so
there was no way for it to speak first. The UI filled the gap with a fixed
sentence — "What would you like to build?" — shown whenever the transcript was
empty.

Which is the wrong question about half the time. §118 calls Smith the
*persistent* architect, and `smith.py` spends its opening paragraphs on what
persistent means: a Smith constructed tomorrow in a new process is the same
Smith, because every layer it thinks with is on disk. A user coming back to an
application with eighteen pages, parked at the build authorisation gate, was
being asked what they would like to build.

So a greeting is not a welcome string. It is the shortest true answer to "where
am I", and there are only two kinds:

* **Nothing yet.** Then it really is "what would you like to build", and the
  useful part is the openers — a user staring at an empty box needs a way in
  more than they need a greeting.
* **Something already.** Then say what the application is, where §94 has it,
  and what the one next act is. The user has not forgotten what they were
  building; they have forgotten which of the two gates they were standing at.

Deterministic (§116)
--------------------
No model call. Everything here is read off the document and the state machine,
and the wording of a status line is not interpretation — it is the one thing in
a conversation that must say the same thing twice when nothing has changed.
`clarification` sets the precedent in the other direction and for the right
reason: *which* questions to ask is arithmetic, and only their phrasing is
genuine generation. Here there is no phrasing problem to hand over.

Where the openers come from
---------------------------
``shapes/reference_apps.json``, which exists to anchor the planner and says of
itself: "Grow this file (never Python) to teach the planner about new kinds of
apps." Deriving the openers from it rather than listing them here honours that
— the suggestions widen when somebody teaches the planner a new shape, and
there is no second list to keep in agreement with the first.

Ranked by how many reference apps share an interaction kind, so what Smith
offers first is what it has the most anchors for. Suggesting the shapes the
platform is thinnest on would be advertising its weakest work.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

#: §94 state -> (what is true, what the user does next). Declared rather than
#: computed: "which act moves this forward" is a fact about the lifecycle, and
#: deriving it from ``ALLOWED_TRANSITIONS`` would only say which states are
#: reachable, not which of them the user is expected to ask for.
NEXT_ACT: dict[str, tuple[str, str]] = {
    "DISCOVERY": ("I have what you have told me so far.",
                  "Keep describing it, or say `define` when you are ready."),
    "CLARIFICATION": ("I have questions outstanding.",
                      "Answer them, or say `define` to work with what I have."),
    "DEFINITION": ("I am drafting the description.", ""),
    "BLUEPRINT_REVIEW": ("Here is what I understood. Nothing is built yet.",
                         "Say `approve` if that is right, or tell me what to "
                         "change."),
    "PLANNING": ("I am working out the plan.", ""),
    "PLAN_REVIEW": ("The plan is ready and nothing has been built yet.",
                    "Say `build` to authorise it, or tell me what to change."),
    "IMPLEMENTATION": ("The build is running.", ""),
    "DATABASE_PROVISIONING": ("Setting up the database.", ""),
    "BUILD": ("Generating the application.", ""),
    "VERIFICATION": ("Checking what was built against what was agreed.", ""),
    "PREVIEW": ("It is built and running.",
                "Say `preview` for the link, or tell me what to change."),
    "ITERATION": ("I am applying your last change.", ""),
    "READY": ("It is finished and running.",
              "Tell me what to change, or `export` for the source."),
    "EXPORT_DEPLOY": ("It is being published.", ""),
    "MAINTENANCE": ("It is live.", "Tell me what to change."),
}

#: How many openers to offer. Enough to show range, few enough to read — the
#: point is a way in, not a catalogue.
OPENER_COUNT = 5


@dataclass(frozen=True)
class Opener:
    """One kind of application, with a real example of it."""

    kind: str
    example: str

    def __str__(self) -> str:  # pragma: no cover - diagnostics
        return f"{self.kind} — {self.example}"


@dataclass(frozen=True)
class Greeting:
    """Smith's opening line, and what it is based on."""

    state: str
    headline: str
    detail: str
    next_act: str = ""
    #: Only when there is nothing yet. A user with an application does not need
    #: to be told what kinds of application exist.
    openers: list[Opener] = field(default_factory=list)
    #: What the greeting is asserting, so a caller can render it its own way
    #: rather than parsing the sentence back apart.
    facts: dict[str, Any] = field(default_factory=dict)

    @property
    def is_first_visit(self) -> bool:
        return not self.facts.get("named")


def _reference_openers(limit: int = OPENER_COUNT) -> list[Opener]:
    """One opener per interaction kind, commonest kinds first.

    Ties broken by name so the same file always produces the same openers: a
    greeting that reshuffles between page loads reads as indecision.
    """
    try:
        from services.shape_profile import _reference_apps  # type: ignore

        apps = (_reference_apps() or {}).get("reference_apps") or []
    except Exception:  # noqa: BLE001 — a missing anchor file is not a failure
        return []                                # worth refusing to greet over

    by_kind: dict[str, list[dict]] = {}
    for app in apps:
        kind = ((app.get("app_shape") or {}).get("layout") or {}
                ).get("primaryInteraction") or ""
        if kind:
            by_kind.setdefault(kind, []).append(app)

    counts = Counter({k: len(v) for k, v in by_kind.items()})
    ranked = sorted(by_kind, key=lambda k: (-counts[k], k))

    out: list[Opener] = []
    for kind in ranked[:limit]:
        example = min(by_kind[kind], key=lambda a: a.get("name") or "")
        out.append(Opener(kind=kind, example=(example.get("gloss") or "").strip()))
    return out


def _counts(doc: dict) -> dict[str, int]:
    live = [r for r in (doc.get("requirements") or [])
            if r.get("status") != "DEPRECATED"]
    return {
        "requirements": len(live),
        "pages": len(doc.get("pages") or []),
        "entities": len((doc.get("data") or {}).get("entities") or []),
        "workflows": len(doc.get("workflows") or []),
    }


def greet(doc: dict, *, open_questions: int = 0) -> Greeting:
    """The shortest true answer to "where am I"."""
    state = doc.get("state") or "DISCOVERY"
    name = ((doc.get("application") or {}).get("name") or "").strip()
    counts = _counts(doc)
    started = any(counts.values())

    if not started:
        return Greeting(
            state=state,
            headline="What would you like to build?",
            detail=(
                "Describe it in your own words, or show me — a specification, "
                "a design, screenshots of something like it. I will write down "
                "what I understood and check it with you before anything is "
                "built."
            ),
            openers=_reference_openers(),
            facts={"named": False, **counts},
        )

    situation, act = NEXT_ACT.get(state, ("", ""))
    built = ", ".join(
        f"{n} {label}" for label, n in (
            ("requirements", counts["requirements"]),
            ("pages", counts["pages"]),
            ("entities", counts["entities"]),
            ("workflows", counts["workflows"]),
        ) if n
    )

    return Greeting(
        state=state,
        headline=f"{name or 'Your application'} — {built}." if built
        else (name or "Your application"),
        detail=situation,
        next_act=act,
        facts={"named": bool(name), "openQuestions": open_questions, **counts},
    )
