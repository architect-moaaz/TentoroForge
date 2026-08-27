"""Product standards — the canonical acceptance rubric for generated apps.

One authoritative document, threaded through three enforcement surfaces so
they cannot drift:

  1. **Prompt injection** (this module + product_standards_context) — the
     design and page-schema LLM agents see the standards up front so they
     author correct output first-pass, not "author + guard-repair".

  2. **Post-gen guards** (services/post_generate_fixes and friends) —
     deterministic repair passes catch what the LLM still misses.

  3. **Self-Verify Pass** (services/self_verify_pass) — the Playwright
     runner asserts each bullet against the rendered app.

Bullets that are already enforced deterministically (data-engine as the
sole CRUD path, auth middleware, Tailwind + library components, seed
synthesis) are NOT re-stated to the LLM — the deterministic guarantee is
stronger than a prompt reminder, and repeating them wastes tokens. What
IS re-stated is the class of standard the LLM decides on its own:
visual style (design agent) and page-level completeness (page schema).

Update this single file to change the standards anywhere in the system.
"""
from __future__ import annotations

from typing import Literal

# The canonical rubric. Read by product_standards_context.render_for(),
# by the standards report writer (post-gen), and by the Self-Verify Pass
# assertion builder.
STANDARDS: dict[str, list[str]] = {
    "architecture": [
        "Business logic must not live inside React components — it belongs "
        "in the workflow engine (workflow JSON) or the data-engine catch-all.",
        "All database access goes through the data-engine catch-all "
        "(/api/data/[...path]) — never hand-write per-entity routes.",
        "Auth + authorization use the existing middleware — never inline "
        "role checks in a page component.",
    ],
    "frontend": [
        "Use only components from @tentoroforge/library — never author "
        "one-off Tailwind-only JSX in a page schema.",
        "Use Lucide icons via IconButton / library components — never emoji "
        "as icons.",
        "Every screen renders correctly at mobile (375), tablet (768), "
        "and desktop (1280) viewport widths.",
        "Maintain consistent spacing via design tokens — no arbitrary px "
        "values, no ad-hoc margin/padding.",
        "Avoid excessive gradients and oversized hero cards — restraint "
        "over decoration.",
    ],
    "completeness": [
        "Every button must be wired to a real action — a workflow, a "
        "navigate, or a declared handler. No dead buttons.",
        "Every data-bound component (Table / List / Chart / Stat) must "
        "have an isLoading skeleton state.",
        "Every list/table must have a real empty state (icon + message + "
        "CTA when appropriate) — not just an empty container.",
        "Every mutating action must have an error surface (toast / "
        "inline error) and a success signal.",
        "Every form field must declare validation (required, type, "
        "min/max) matching the underlying column.",
        "Every schema binding must reference a real registered dataSource — "
        "never a placeholder like `{{items}}` or a made-up entity name.",
    ],
    "content": [
        "No hard-coded production data in schemas — sample data lives in "
        "the seed synthesizer, not in `props.rows` or `props.items`.",
        "Labels, headings, and empty-state copy must be domain-specific — "
        "no generic 'Total Items' or 'Recent Records'.",
    ],
}

_Phase = Literal["design", "page_schema"]

# Which standard sections each LLM phase should actually see. The rest
# are enforced deterministically (guards / templates / injectors) and
# would just be prompt noise here.
_PHASE_SECTIONS: dict[_Phase, tuple[str, ...]] = {
    "design": ("frontend",),
    "page_schema": ("frontend", "completeness", "content"),
}


def render_for(phase: _Phase) -> str:
    """Return the standards block to append to a phase's system/user prompt.

    Returns a heading + bulleted subsections restricted to the standards
    that phase actually decides. Callers append the return value verbatim
    to their prompt.

    Empty string when the phase has no applicable sections (defensive:
    a future caller passing a phase we haven't registered gets nothing
    rather than a crash).
    """
    sections = _PHASE_SECTIONS.get(phase)
    if not sections:
        return ""
    lines: list[str] = []
    lines.append("## Product standards")
    lines.append(
        "These are the acceptance criteria for this app. The Self-Verify "
        "Pass will assert them against the rendered output. Authoring to "
        "these first-pass avoids a post-gen repair round."
    )
    for section in sections:
        bullets = STANDARDS.get(section) or []
        if not bullets:
            continue
        lines.append(f"\n### {section.title()}")
        for b in bullets:
            lines.append(f"- {b}")
    return "\n".join(lines)


def all_sections() -> dict[str, list[str]]:
    """Read-only accessor for the full rubric. Used by the standards
    report writer + the Self-Verify assertion builder."""
    return {k: list(v) for k, v in STANDARDS.items()}
