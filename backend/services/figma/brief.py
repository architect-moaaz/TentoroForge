"""What the Figma Intelligence Agent is shown (PRD §48, §49, §50).

The agent's job is inference under a stated bound, and the brief is where the
bound is set. §48 draws it: a frame labelled ``Approve Candidate`` proves a
button exists; it does not say who may approve, on what condition, what it
writes, or what happens when it is refused. An agent handed the design and
asked for "the requirements" will answer all four, confidently, from nothing.

So the brief carries three things and withholds one.

Carried:

* **the vocabulary** — every visible label on every screen. §49 infers
  capability from what the design says, and "Schedule Interview" on a button
  is the evidence that interview scheduling is a capability.
* **the shape** — frame names, sizes, and which are screens rather than icon
  sheets, so a requirement can cite the frame it came from (§14).
* **the gaps** — what the extraction could not determine. An agent told the
  prototype links were unavailable proposes navigation as an assumption at low
  confidence; an agent not told simply proposes it (§17, §50).

Withheld: the generated TSX. A screen's source is tens of kilobytes of layout
divs, and the labels are the part that carries meaning. Including it would push
the useful evidence out of the model's attention and bill for the privilege.
"""
from __future__ import annotations

from typing import Any

from services.figma.reference import DesignReference

#: Labels per screen. Enough for a screen's vocabulary to be legible; beyond
#: this it is table rows and placeholder copy, which say nothing new.
_MAX_LABELS = 40


def screen_entry(screen: Any) -> dict[str, Any]:
    structure = screen.structure or {}
    labels = list(structure.get("labels") or [])[:_MAX_LABELS]
    entry: dict[str, Any] = {
        "nodeId": screen.node_id,
        "name": screen.name,
        "canvas": screen.canvas,
    }
    if screen.width:
        entry["size"] = f"{int(screen.width)}x{int(screen.height)}"
    if labels:
        entry["labels"] = labels
    if not screen.looks_like_screen:
        entry["looksLikeScreen"] = False
    return entry


def design_brief(ref: DesignReference) -> dict[str, Any]:
    """Everything the agent gets about one connected design."""
    screens = [s for s in ref.screens if s.looks_like_screen]
    return {
        "source": ref.source_id,
        "provider": ref.provider or "figma",
        "file": ref.target.describe(),
        "counts": ref.summary(),
        "screens": [screen_entry(s) for s in screens],
        # Recorded separately so the agent can see what was deliberately not
        # treated as a screen, and disagree — §49 keeps inference reviewable
        # rather than deciding it upstream.
        "notScreens": [
            s.name for s in ref.screens if not s.looks_like_screen
        ],
        "components": sorted({c.name for c in ref.components if c.name}),
        "interactions": [
            {"from": i.source_node, "to": i.target_node, "trigger": i.trigger}
            for i in ref.interactions
        ],
        "designTokens": {
            "colors": sorted(ref.tokens.colors)[:30],
            "typography": sorted(ref.tokens.typography)[:20],
        },
        # §102 / §50 — the questions the design does not answer.
        "gaps": list(ref.gaps),
    }


def brief_for(doc: dict, source_id: str, output_dir: Any) -> dict[str, Any]:
    """Load the stored reference for ``source_id`` and brief on it.

    Falls back to the Blueprint's own ``designSources`` record when the stored
    payload is gone (§93 — a restored version may name a source whose
    extraction was never copied). The record still carries frame names and
    gaps, which is a thin brief but an honest one; silently briefing on nothing
    would let the agent infer an application from an empty design.
    """
    from services.figma import store

    ref = store.load(source_id, output_dir)
    if ref is not None:
        return design_brief(ref)

    record = next(
        (s for s in (doc.get("designSources") or []) if s.get("id") == source_id),
        None,
    )
    if record is None:
        return {"source": source_id, "gaps": ["this design source is not recorded"]}

    return {
        "source": source_id,
        "file": record.get("fileKey", ""),
        "screens": [
            {"nodeId": f.get("nodeId"), "name": f.get("name")}
            for f in record.get("frames") or []
            if f.get("looksLikeScreen", True)
        ],
        "gaps": list(record.get("gaps") or []) + [
            "the extracted design payload is no longer stored; only frame "
            "names are available, so nothing may be inferred from screen "
            "content"
        ],
    }
