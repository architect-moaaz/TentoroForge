"""Planner authoritative-inputs context builder — Phase 2.1.

When a planner recipe runs, it should NOT re-derive entities/actors/features
from the raw prompt — Layer 1 (locked_spec) already did that. This module
formats the LockedSpec + Manifest + Archetype match into a compact block
the planner can paste into its system prompt so it treats those inputs
as authoritative.

Usage inside a planner recipe:

    from services.planner_context import build_authoritative_inputs_block

    block = build_authoritative_inputs_block(output_dir)
    if block:
        prompt = f"{block}\\n\\n{original_prompt}"

The block is markdown-shaped so the LLM parses it reliably. When no
locked spec is present (legacy pipeline path or FORGE_LOCKED_SPEC=false),
`build_authoritative_inputs_block` returns "" and the recipe falls back to
its previous behavior.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.locked_spec import load_locked_spec
from services.scope_card import load_manifest


_HEADER = "# AUTHORITATIVE INPUTS — do not re-derive from the prompt\n"


def _load_archetype(output_dir: Path) -> dict | None:
    """The archetype classifier persists results to
    contracts/archetype.json. Absent → None."""
    for candidate in (
        output_dir / "contracts" / "archetype.json",
        output_dir / "src" / "contracts" / "archetype.json",
    ):
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                return None
    return None


def build_authoritative_inputs_block(output_dir: str | Path) -> str:
    """Render the block. Returns "" when locked spec + manifest are missing."""
    base = Path(output_dir)
    spec = load_locked_spec(base)
    manifest = load_manifest(base)
    archetype = _load_archetype(base)

    if spec is None and manifest is None and archetype is None:
        return ""

    lines: list[str] = [_HEADER]
    lines.append(
        "These sections describe the EXACT set of actors, entities, features, "
        "pages, and workflows the platform will accept. Do NOT add new entries. "
        "Do NOT rename entries. Everything you generate — plan.json, workflow "
        "JSON, page schemas — must reference only what appears below. "
        "Names ARE case-sensitive.\n"
    )

    if archetype and archetype.get("archetype"):
        lines.append(f"## Archetype\n\n- **{archetype['archetype']}**")
        if archetype.get("reason"):
            lines.append(f"  — {archetype['reason']}")
        renames = archetype.get("renames") or {}
        if renames:
            lines.append("\n### Renames (apply verbatim)\n")
            for k, v in sorted(renames.items()):
                lines.append(f"- `{k}` → `{v}`")
        lines.append("")

    if spec is not None:
        if spec.actors:
            lines.append("## Actors\n")
            for a in spec.actors:
                hint = ", ".join(a.permissions_hint) if a.permissions_hint else ""
                if hint:
                    lines.append(f"- **{a.role}** (permissions: {hint})")
                else:
                    lines.append(f"- **{a.role}**")
            lines.append("")

        if spec.entities:
            lines.append("## Entities\n")
            lines.append("| Name | Kind | Cardinality |")
            lines.append("|---|---|---|")
            for e in spec.entities:
                lines.append(f"| `{e.name}` | {e.kind} | {e.cardinality} |")
            lines.append("")
            lines.append(
                "**Rules:** `entity` gets full CRUD; `event` gets list+detail "
                "only (never `new`/`edit`); `role`/`external`/`derived` get "
                "no CRUD pages and no table.\n"
            )

        if spec.features:
            lines.append("## Features\n")
            for f in spec.features:
                target = f" → {f.target_entity}" if f.target_entity else ""
                lines.append(f"- **{f.actor}** *{f.verb}*: {f.name}{target}")
            lines.append("")

        if spec.externals:
            lines.append("## External services\n")
            for x in spec.externals:
                lines.append(f"- {x.type.upper()}: **{x.provider}**")
            lines.append("")

    if manifest is not None:
        if manifest.pages:
            lines.append("## Allowed page routes\n")
            for p in manifest.pages:
                extra = []
                if p.entity:
                    extra.append(f"entity={p.entity}")
                if p.feature:
                    extra.append(f"feature={p.feature}")
                if p.actor:
                    extra.append(f"actor={p.actor}")
                suffix = f" ({', '.join(extra)})" if extra else ""
                lines.append(f"- `{p.path}` [{p.kind}]{suffix}")
            lines.append(
                "\nAny page route not listed above will be rejected by "
                "the contract validator.\n"
            )
        if manifest.entities_with_tables:
            lines.append("## Entities that must get a Postgres table\n")
            for name in manifest.entities_with_tables:
                lines.append(f"- `{name}`")
            lines.append("")
        if manifest.workflows:
            lines.append("## Allowed workflow names\n")
            for w in manifest.workflows:
                lines.append(f"- `{w}`")
            lines.append(
                "\nRuntime primitives (`Login`, `Register`, `Logout`, "
                "`Checkout`) are always allowed even if not listed.\n"
            )

    return "\n".join(lines).strip() + "\n"
