"""Design stance for the phases that still author with an LLM.

``product_standards`` states what the app must *do*; this states how it
should *look and feel* when a human, not a builder, is making the call.
It exists because most of the visual variety in a generated app comes from
the archetypes with no deterministic composer — dashboards, collections
and records are built in code, everything else is authored.

Adapted from the Taste Skill framework (tasteskill.dev). Deliberately NOT
adopted from it:

* Its design-system mapping (when to use Material / Carbon / Polaris /
  shadcn). This platform ships its own component library; naming foreign
  systems in a prompt invites the model to reference components that do
  not exist here, which is the failure the component contracts exist to
  prevent.
* Its pre-flight checklist. A checklist an agent grades itself against is
  a hope; the same rules belong in the gates, where a build can fail on
  them. See ``motion_authority.check_css`` for that shape.

Kept deliberately short. ``schema_prompt`` already logs a warning when the
assembled prompt crosses its 25k-token budget, and every token spent here
displaces component contracts and registry context — the material that
stops the model inventing components and bindings. Terse and load-bearing
beats thorough.
"""
from __future__ import annotations

from typing import Literal

_Phase = Literal["design", "page_schema", "compose"]

# ── the stance vocabulary ──────────────────────────────────────────────────
# A stance is CHOSEN once per app and stated to the agent as a decision
# already made. Offering a menu invites the model to average across them,
# which is how every app ends up looking like the midpoint of three.
STANCES: dict[str, str] = {
    "soft": (
        "Calm and expensive-looking. Softer contrast, generous whitespace, "
        "restrained motion. Nothing shouts; hierarchy comes from space and "
        "weight rather than colour."
    ),
    "minimalist": (
        "Editorial and structural. Restrained colour, sharp alignment, "
        "tight hierarchy. Type does the work; ornament is absent rather "
        "than subtle."
    ),
    "brutalist": (
        "Mechanical and direct. Swiss typography, raw structure, hard "
        "contrast, visible grid. Confidence over comfort."
    ),
}

# What the agent should infer about the product before it picks anything.
# Stated as questions because an answered question shapes output; an
# adjective list just gets echoed back.
_INFERENCE = [
    "Who uses this, how often, and are they doing a job or making a choice?",
    "Is the work scanned (operational) or read (informational)?",
    "What is the one moment on each page that matters most?",
]

# Non-negotiables — phrased as properties of the output, not as advice.
_INVARIANTS = [
    "Both themes are designed. Contrast and hierarchy must hold in light "
    "and dark; a dark mode that merely inverts is not designed.",
    "Scanability outranks expression on operational screens. On a screen "
    "someone uses all day, the striking choice is the wrong one.",
    "Structure encodes meaning. Numbering, dividers and eyebrows are used "
    "only where the content genuinely is a sequence or a set.",
    "Every state is authored — empty, loading, error, and one-row — not "
    "just the populated happy path.",
]

_PHASE_SECTIONS: dict[str, tuple[bool, bool, bool]] = {
    #            inference, stance, invariants
    "design":      (True,  True,  True),
    "page_schema": (False, True,  True),
    "compose":     (False, True,  True),
}


def stance_for(brief: dict | None) -> str:
    """Pick one stance from the design brief. Never returns a menu.

    Reads the brief's own vocabulary rather than re-deriving tone: the
    brief is the naming authority for how the app should feel, and a
    second opinion computed here would drift from it.
    """
    b = brief or {}
    explicit = str(((b.get("visual_stance") or {}).get("stance")
                    or b.get("stance") or "")).strip().lower()
    if explicit in STANCES:
        return explicit
    identity = b.get("identity") or {}
    register = str(identity.get("register") or "").lower()
    temp = str((b.get("visual_stance") or {}).get("temperature") or "").lower()
    if any(w in register or w in temp for w in ("warm", "calm", "soft", "gentle")):
        return "soft"
    if any(w in register for w in ("bold", "raw", "technical", "industrial")):
        return "brutalist"
    return "minimalist"


def render_for(phase: _Phase, brief: dict | None = None) -> str:
    """The stance block to append to a phase's prompt, or ''.

    Mirrors ``product_standards.render_for`` so call sites stay uniform.
    Unknown phase → empty string, not a crash.
    """
    sections = _PHASE_SECTIONS.get(phase)
    if not sections:
        return ""
    want_inference, want_stance, want_invariants = sections
    out: list[str] = ["## Design stance"]

    if want_stance:
        name = stance_for(brief)
        out.append(f"**Stance: {name}.** {STANCES[name]}")
        out.append("This is decided. Author to it rather than averaging "
                   "across alternatives.")
    if want_inference:
        out.append("")
        out.append("Answer these before choosing anything:")
        out.extend(f"- {q}" for q in _INFERENCE)
    if want_invariants:
        out.append("")
        out.extend(f"- {r}" for r in _INVARIANTS)
    return "\n".join(out)
