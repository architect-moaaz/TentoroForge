"""Build a rich, divergence-pressuring context block for the shell layout agent.

Replaces the agent's bare app/brand dump with an information-architecture analysis
(primary vs utility destinations), design-language hints (when present), brand
character, and an explicit directive to choose the frame the domain wants rather
than defaulting to a generic admin sidebar.
"""
from __future__ import annotations

import json

# Route prefixes/names that are utility/admin destinations rather than core workflow.
_UTILITY_PREFIXES = ("admin", "settings")
_UTILITY_EXACT = {"settings", "users", "profile", "account", "billing"}


def _classify_destinations(plan: dict, nav_flow: dict) -> tuple[list[str], list[str]]:
    pages = (nav_flow or {}).get("pages") or (plan or {}).get("pages") or []
    primary: list[str] = []
    utility: list[str] = []
    for p in pages:
        if not isinstance(p, dict):
            continue
        route = (p.get("route") or "").strip("/").lower()
        title = p.get("title") or p.get("name") or (route or "home").split("/")[0].title()
        if not route:  # home/dashboard
            primary.append(title); continue
        head = route.split("/")[0]
        if head in _UTILITY_PREFIXES or head in _UTILITY_EXACT:
            utility.append(title)
        else:
            primary.append(title)
    # de-dup preserving order
    def _dedup(xs):
        seen = set(); out = []
        for x in xs:
            if x not in seen:
                seen.add(x); out.append(x)
        return out
    return _dedup(primary), _dedup(utility)


def build_shell_context(plan: dict, nav_flow: dict,
                        design_spec: dict | None = None,
                        domain_context: dict | None = None) -> str:
    plan = plan or {}
    parts: list[str] = []
    parts.append("## App")
    parts.append(f"Name: {plan.get('name', 'Untitled App')}")
    if plan.get("description"):
        parts.append(f"Description: {plan.get('description')}")

    primary, utility = _classify_destinations(plan, nav_flow or {})
    parts.append("\n## Information architecture")
    parts.append(f"Primary destinations ({len(primary)}): {', '.join(primary) or '(none)'}")
    parts.append(f"Utility / admin destinations ({len(utility)}): {', '.join(utility) or '(none)'}")
    parts.append(
        "Choose a shell whose navigation fits THIS IA: few primaries may suit a top-bar or "
        "command-bar; many grouped destinations a sectioned sidebar; a single focus workflow a "
        "split workspace. Group utility/admin items separately from primary navigation."
    )

    # Design-language hints (produced fully by SP3.3; read what's present, omit when absent)
    ds = design_spec or {}
    layout = ds.get("layout") or {}
    typo = ds.get("typography") or {}
    dl_bits = []
    if layout.get("navigation"): dl_bits.append(f"nav style: {layout['navigation']}")
    if layout.get("density"): dl_bits.append(f"density: {layout['density']}")
    if layout.get("borderRadius"): dl_bits.append(f"radius: {layout['borderRadius']}")
    if typo.get("fontFamily"): dl_bits.append(f"font: {typo['fontFamily']}")
    if dl_bits:
        parts.append("\n## Design language")
        parts.append("; ".join(dl_bits))

    # Brand character from the dossier (not just hex colors)
    dc = domain_context or {}
    character = dc.get("brandCharacter") or dc.get("persona") or dc.get("tone")
    if character:
        parts.append("\n## Brand character")
        parts.append(str(character))

    parts.append(
        "\n## Directive\nDESIGN THE FRAME THE DOMAIN WANTS. Do NOT default to a generic "
        "dark-sidebar admin layout unless this app's IA genuinely calls for a sectioned sidebar. "
        "Two apps in different domains should have structurally different shells."
    )
    return "\n".join(parts)
