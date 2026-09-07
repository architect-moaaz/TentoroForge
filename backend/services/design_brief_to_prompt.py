"""Flatten a :class:`schemas.design_brief.DesignBrief` into a prose block
suitable for injection into LLM system prompts.

Used by component/page/figma/design agents in Phase 2. The output is
short, scannable, and specifically written so the model treats it as a
hard contract, not a suggestion.

Kept pure: no I/O, no LLM. Test via ``brief_to_prompt(brief) → str``.
"""
from __future__ import annotations

from pathlib import Path

from schemas.design_brief import DesignBrief


def brief_to_prompt(brief: DesignBrief) -> str:
    """Render a DesignBrief as a system-prompt injection block.

    Format is deliberately terse (~15 lines) so it fits comfortably at
    the top of an already-large system prompt. Signature moves and
    antipatterns are the load-bearing lines — everything else the model
    infers from the surrounding architecture.
    """
    p = brief.palette
    t = brief.typography
    l = brief.layout
    i = brief.identity

    sigs = "\n".join(
        f"  - {m.kind}: {m.detail}" for m in brief.signature_moves
    )
    aps = "\n".join(f"  - {a}" for a in brief.anti_patterns) or "  (none)"

    return f"""[DESIGN BRIEF — contract, obey verbatim]

Identity: {i.domain} · register={", ".join(i.register)} · voice={i.voice.value}
Modes: {", ".join(m.value for m in i.modes)}

Palette (use these hexes; do not invent new ones):
  brand={p.brand}  accent={p.accent}
  neutrals={p.neutrals_base} (tint: {p.neutrals_tint.value})
  surface_bg={p.surface_bg}  surface_elevated={p.surface_elevated}
  fg_primary={p.foreground_primary}  fg_muted={p.foreground_muted}

Typography:
  display: {t.display_family} (weights {t.display_weights})
  body: {t.body_family} (weights {t.body_weights})
  utility: {t.utility_family or "(none)"}
  scale: {t.scale}

Layout: density={l.density.value} · radius={l.radius.value} · grid={l.grid}

Signature moves (at least one must appear in generated output):
{sigs}

Anti-patterns (NEVER produce):
{aps}
"""


def load_brief_from_disk(output_dir: str | Path) -> DesignBrief | None:
    """Convenience loader for pipeline sites that need a brief from an
    already-generated app. Reads ``contracts/brief.json``; returns None
    if missing or malformed (caller decides fallback)."""
    path = Path(output_dir) / "contracts" / "brief.json"
    if not path.exists():
        return None
    try:
        return DesignBrief.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


__all__ = ["brief_to_prompt", "load_brief_from_disk"]
