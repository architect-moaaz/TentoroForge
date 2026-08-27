"""UX Spec Generator — produces a domain-specific UX specification document.

Takes the detected domain + plan entities and generates a concrete, actionable
UX spec that Component and Page agents follow. The spec is injected into agent
prompts so every generated component and page reflects domain-appropriate UX.

Example: for Healthcare + entities [Patient, Appointment, Prescription]:
  - Patient list: search by MRN, show status with clinical colors
  - Appointment detail: timeline view with check-in workflow
  - Dashboard: clinical alerts, today's schedule, patient stats
"""

from __future__ import annotations

import json
import logging
from typing import Any

from services.domain_ux_specs import get_domain_ux_spec

logger = logging.getLogger(__name__)


def generate_ux_spec(domain: str, plan: dict, *, output_dir: str | None = None) -> str:
    """Generate a UX spec document string to inject into agent prompts.

    Args:
        domain: Detected domain label (e.g., "Healthcare")
        plan: The full plan dict with data_models, pages, workflows
        output_dir: Optional path — when provided, the brief at
            ``<output_dir>/contracts/brief.json`` is consulted so
            brief-authored ``identity.compliance_flags`` supplement the
            domain's default compliance block. Spec D Wave 1 (round 2).

    Returns:
        A markdown string with domain-specific UX rules, ready for prompt injection.
    """
    spec = get_domain_ux_spec(domain)
    # Spec D Wave 1 (round 2) — brief-first read. Silent fallback when
    # output_dir isn't threaded through the call site yet.
    brief_flags: list[str] = []
    if output_dir:
        try:
            from services.brief_visual_stance import (
                get_compliance_flags,
                load_brief_from,
            )
            brief_flags = get_compliance_flags(load_brief_from(output_dir))
        except Exception:  # noqa: BLE001 — brief is enhancement, never fatal
            brief_flags = []
    models = plan.get("data_models", [])
    workflows = plan.get("workflows", [])

    sections: list[str] = []
    sections.append(f"## ━━ DOMAIN UX SPECIFICATION: {domain.upper()} ━━\n")

    # 1. Dashboard layout
    dash = spec.get("page_archetypes", {}).get("dashboard", {})
    if dash:
        sections.append("### Dashboard Layout")
        sections.append(f"- **Layout**: {dash.get('layout', 'standard')}")
        sections.append(f"- **Hero**: {dash.get('hero', '')}")
        sections.append(f"- **Sections** (in this order):")
        for s in dash.get("sections", []):
            sections.append(f"  1. {s}")
        sections.append("")

    # 2. List page pattern
    list_spec = spec.get("page_archetypes", {}).get("list", {})
    if list_spec:
        sections.append("### List Page Pattern")
        sections.append(f"- **Search**: {list_spec.get('primary_search', 'Search by name')}")
        cols = list_spec.get("key_columns", [])
        if cols:
            sections.append(f"- **Key columns** (show these first): {', '.join(cols)}")
        actions = list_spec.get("row_actions", [])
        if actions:
            sections.append(f"- **Row actions**: {', '.join(actions)}")
        sections.append(f"- **Empty state**: \"{list_spec.get('empty_state', '')}\"")
        sections.append("")

    # 3. Detail page pattern
    detail_spec = spec.get("page_archetypes", {}).get("detail", {})
    if detail_spec:
        sections.append("### Detail Page Pattern")
        sections.append(f"- **Layout**: {detail_spec.get('layout', 'tabbed-detail')}")
        hero = detail_spec.get("hero_fields", [])
        if hero:
            sections.append(f"- **Hero section** (show prominently at top): {', '.join(hero)}")
        tabs = detail_spec.get("tabs", [])
        if tabs:
            sections.append(f"- **Tabs**: {' | '.join(tabs)}")
        sidebar = detail_spec.get("sidebar_summary", [])
        if sidebar:
            sections.append(f"- **Sidebar summary**: {', '.join(sidebar)}")
        sections.append("")

    # 4. Form pattern
    form_spec = spec.get("page_archetypes", {}).get("form", {})
    if form_spec:
        sections.append("### Form Pattern")
        form_sections = form_spec.get("sections", [])
        if form_sections:
            sections.append(f"- **Section grouping**: {' → '.join(form_sections)}")
        sections.append(f"- **Warnings**: {form_spec.get('required_warnings', '')}")
        sections.append(f"- **Validation**: {form_spec.get('validation', '')}")
        sections.append("")

    # 5. Status semantics
    statuses = spec.get("status_semantics", {})
    if statuses:
        sections.append("### Status Color Semantics (use these EXACT colors)")
        sections.append("| Status | Color | Background | Text | Icon |")
        sections.append("|--------|-------|-----------|------|------|")
        for status, meta in statuses.items():
            sections.append(
                f"| {status} | {meta.get('color', '')} | "
                f"`{meta.get('bg', '')}` | `{meta.get('text', '')}` | "
                f"{meta.get('icon', '')} |"
            )
        sections.append("")

    # 6. Domain-specific widgets
    widgets = spec.get("key_widgets", [])
    if widgets:
        sections.append("### Domain-Specific Widgets (implement these)")
        for w in widgets:
            sections.append(
                f"- **{w['name']}**: {w['description']} "
                f"(placement: {w.get('placement', 'dashboard')})"
            )
        sections.append("")

    # 7. Component patterns
    patterns = spec.get("component_patterns", {})
    if patterns:
        sections.append("### Component Styling Rules")
        for comp_type, rule in patterns.items():
            sections.append(f"- **{comp_type}**: {rule}")
        sections.append("")

    # 8. Compliance requirements
    #
    # Spec D Wave 1 (round 2) — brief-first: when brief.identity.compliance_flags
    # is authored, we cite the brief's regime list in the header so agents
    # see BOTH the domain default (HIPAA/SOX/etc) and the brief-requested
    # regimes (which may add PCI/SOC2/GDPR on top). The domain requirement
    # bullets still emit verbatim — we augment, we don't narrow, because
    # the domain rules encode real safety patterns.
    compliance = spec.get("compliance", {})
    if compliance and compliance.get("requirements"):
        domain_std = compliance.get("standard", "N/A")
        if brief_flags:
            brief_regimes = ", ".join(f.upper() for f in brief_flags)
            sections.append(
                f"### Compliance ({domain_std}; brief-requested: {brief_regimes})"
            )
        else:
            sections.append(f"### Compliance ({domain_std})")
        for req in compliance["requirements"]:
            sections.append(f"- {req}")
        sections.append("")
    elif brief_flags:
        # Domain has no compliance block but brief still asked for regimes —
        # surface them so agents at least apply generic safeguards.
        brief_regimes = ", ".join(f.upper() for f in brief_flags)
        sections.append(f"### Compliance (brief-requested: {brief_regimes})")
        sections.append(
            "- Apply standard safeguards for the listed regimes "
            "(audit trail, role-based access, retention policy)."
        )
        sections.append("")

    # 9. Navigation flow
    nav = spec.get("navigation_flow", {})
    if nav:
        sections.append("### Navigation")
        actions = nav.get("primary_actions", [])
        if actions:
            sections.append(f"- **Primary actions** (always visible): {', '.join(actions)}")
        groups = nav.get("sidebar_groups", [])
        if groups:
            sections.append(f"- **Sidebar groups**: {' | '.join(groups)}")
        quick = nav.get("quick_access", "")
        if quick:
            sections.append(f"- **Quick access**: {quick}")
        sections.append("")

    # 10. Entity-specific info hierarchy
    hierarchy = spec.get("info_hierarchy", {})
    if hierarchy:
        sections.append("### Information Hierarchy (show fields in this priority order)")
        for entity, fields in hierarchy.items():
            # Match against plan entities
            matching_model = None
            for m in models:
                model_name = m.get("name", "").lower()
                if entity.lower() in model_name or model_name in entity.lower():
                    matching_model = m
                    break
            if matching_model:
                sections.append(f"- **{matching_model.get('name', entity)}**: {' → '.join(fields)}")
            else:
                sections.append(f"- **{entity}**: {' → '.join(fields)}")
        sections.append("")

    # 11. Map plan entities to domain archetypes
    sections.append("### Entity → Page Archetype Mapping")
    layout_spec = spec.get("page_archetypes", {})
    for m in models:
        name = m.get("name", "")
        name_lower = name.lower()
        # Detect entity type from name
        if any(kw in name_lower for kw in ("dashboard", "report", "analytics")):
            archetype = "dashboard"
        elif any(kw in name_lower for kw in ("log", "entry", "transaction", "activity")):
            archetype = "list (dense, time-sorted)"
        elif any(kw in name_lower for kw in ("setting", "config", "preference")):
            archetype = "form (settings page)"
        else:
            archetype = "list + detail + form (standard CRUD)"
        sections.append(f"- **{name}** → {archetype}")
    sections.append("")

    result = "\n".join(sections)
    logger.info("Generated UX spec for %s (%d chars, %d entities)", domain, len(result), len(models))
    return result


def save_ux_spec(output_dir: str, spec_text: str) -> None:
    """Save the UX spec to disk so agents can reference it."""
    from pathlib import Path
    spec_file = Path(output_dir) / "src" / "contracts" / "ux-spec.md"
    spec_file.parent.mkdir(parents=True, exist_ok=True)
    spec_file.write_text(spec_text, encoding="utf-8")
    logger.info("Saved UX spec to %s", spec_file)
