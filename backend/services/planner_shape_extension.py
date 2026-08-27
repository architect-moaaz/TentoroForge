"""Planner shape extension (M1-T1 + M1-T10 + M0-T1 compat bridge).

Ships three pieces:

1. **Prompt block** — appended to ``PLANNER_SYSTEM_PROMPT``. Instructs
   the LLM to emit the four-axes + coverage-verdict alongside the
   existing plan fields. Rendered from the JSON vocabularies so the
   prompt stays in sync with the closed sets.

2. **Post-parse enrichment** — ``enrich_plan(plan, brief)``. Runs on
   every plan just after extraction:
   - Fills any missing axis field with the keyword detector
     (M1-T6/T7).
   - Copies ``plan["industry"]`` ↔ ``plan["domain"]`` in both
     directions (M0-T1 compat bridge — the industry rename is a
     read-both/write-both pattern until a full sweep can be
     scheduled; ``industry`` is the canonical field, ``domain`` is
     the legacy field). No hard rename because ``"domain"`` is
     overloaded elsewhere (FK-role vocabulary, intent classifier).
   - Runs ``validate_all`` + ``check_plan_coherence`` and returns
     the findings for the REVISE loop (M1-T10).

3. **REVISE prompt builder** — ``format_findings_for_revise(findings)``.
   Formats findings as the "GAPS TO FIX" block the planner's existing
   REVISE MODE already understands. Reuses the same contract, no new
   flow.

Nothing here changes what the LLM sees for the existing plan schema
— strictly additive. The planner's structured output for entities,
pages, workflows, actors, etc. stays untouched.
"""
from __future__ import annotations

from typing import Any

from services.shape_profile import (
    Finding,
    render_planner_prompt_capabilities,
    render_planner_prompt_runtime_capabilities,
    render_planner_prompt_vocabulary,
    validate_all,
)


# ══════════════════════════════════════════════════════════════════
# Prompt block — appended to PLANNER_SYSTEM_PROMPT
# ══════════════════════════════════════════════════════════════════


def build_prompt_block() -> str:
    """Return the four-axes + coverage-verdict instruction block.

    Rendered from vocabulary JSON so the prompt tracks the vocabulary
    without a code change. Reference apps are shown as short
    compositions to anchor the LLM.
    """
    shape_vocab = render_planner_prompt_vocabulary()
    cap_vocab = render_planner_prompt_capabilities()
    runtime_vocab = render_planner_prompt_runtime_capabilities()

    return (
        "\n\n"
        "═══════════════════════════════════════════════════════════════\n"
        "FOUR-AXIS TOPOLOGY (INTELLIGENT+RICH SUBSTRATE — IRF-M1-T1)\n"
        "═══════════════════════════════════════════════════════════════\n"
        "\n"
        "**THESE ARE REQUIRED TOP-LEVEL KEYS OF YOUR plan-json OUTPUT.**\n"
        "\n"
        "Emit `app_shape`, `archetypes`, `industry`, `runtime_context`,\n"
        "and `coverage_verdict` as siblings of `module_name`, `data_models`,\n"
        "`pages`, `workflows`, `actors` in the plan-json object. NOT as\n"
        "decoration inside another field. The example schema above shows\n"
        "the classic keys (`module_name`, `data_models`, `pages`, …); the\n"
        "IRF fields defined here belong at that same top level.\n"
        "\n"
        "Every generation must emit all five. When the four axes are\n"
        "absent the pipeline falls back to a generic sidebar-list app\n"
        "shape and the design/quality dashboard marks the run as\n"
        "'degraded / LLM_UNAVAILABLE'. Emit them.\n"
        "\n"
        "Each is validated against a closed vocabulary — invalid values\n"
        "fall back to keyword detectors and tag the generation as degraded.\n"
        "\n"
        "── AXIS 1: app_shape ──────────────────────────────────────────\n"
        "\n"
        "A composed profile of 12 primitives that decides the app's\n"
        "topology (shell, hero, auth, nav, workflow-execution, data-\n"
        "read-shape, identity). Emit as a nested object; each primitive\n"
        "value MUST be in the closed set below.\n"
        "\n"
        f"{shape_vocab}\n"
        "\n"
        "You MAY add an optional `label` (short human descriptor) —\n"
        "the pipeline reads primitives only; the label is for humans.\n"
        "\n"
        "Example shape (Snap2App-style camera utility):\n"
        '  \"app_shape\": {\n'
        '    \"layout\":     {\"shell\":\"none\", \"hero\":\"full-bleed-gradient\", \"primaryInteraction\":\"capture\", \"density\":\"spacious\"},\n'
        '    \"auth\":       {\"surface\":\"modal\", \"gating\":\"on-action\"},\n'
        '    \"nav\":        {\"menu\":\"none\", \"back\":\"history\"},\n'
        '    \"workflows\":  {\"executionMode\":\"fire-and-forget\"},\n'
        '    \"data\":       {\"readShape\":\"list\", \"denormalization\":\"aggressive\"},\n'
        '    \"identity\":   {\"usageMode\":\"single-session\"}\n'
        '  }\n'
        "\n"
        "── AXIS 2: archetypes ─────────────────────────────────────────\n"
        "\n"
        "Plural list of ArchetypeInstance objects — one per functional\n"
        "module in the app. Each instance MUST set EITHER `recipe`\n"
        "(name from recipes.json) OR `capabilities` (composed from\n"
        "primitives) OR both (recipe as starting point + local twist).\n"
        "\n"
        f"{cap_vocab}\n"
        "\n"
        "Each instance also declares `entities` (list of entity slugs\n"
        "it reads/writes) and `routes` (list of app routes it owns).\n"
        "May declare `local_shape` (partial override of the outer\n"
        "app_shape for this module's routes only).\n"
        "\n"
        "Example (Snap2App):\n"
        '  \"archetypes\": [\n'
        '    {\"name\":\"scan\", \"recipe\":\"visual_product_search\",\n'
        '     \"entities\":[\"scan_session\", \"price_result\"], \"routes\":[\"/\", \"/scan\"]}\n'
        '  ]\n'
        "\n"
        "── AXIS 3: industry ───────────────────────────────────────────\n"
        "\n"
        "Open string identifying the semantic domain (palette bias,\n"
        "terminology). Examples: consumer-retail, hr-payroll,\n"
        "fintech-brokerage, healthcare, legal, consumer-food-delivery.\n"
        "May invent a new value when nothing fits.\n"
        "\n"
        '  \"industry\": \"consumer-retail\"\n'
        "\n"
        "── AXIS 4: runtime_context ────────────────────────────────────\n"
        "\n"
        "Multi-select from the closed vocabulary. Each declared\n"
        "capability triggers gen-time emission of permissions +\n"
        "providers + integration keys. Do NOT declare capabilities the\n"
        "app doesn't actually use — every one triggers permission\n"
        "prompts and native-module weight.\n"
        "\n"
        f"{runtime_vocab}\n"
        "\n"
        '  \"runtime_context\": [\"camera\"]\n'
        "\n"
        "── COVERAGE VERDICT ───────────────────────────────────────────\n"
        "\n"
        "Before authoring the four axes, honestly assess whether the\n"
        "brief fits Forge's substrate. Emit as `coverage_verdict`:\n"
        "\n"
        "  status: `in_scope` — the brief composes cleanly. Almost\n"
        "                       always.\n"
        "  status: `extension_needed` — the substrate is close but one\n"
        "                       dimension is missing (e.g. Chrome-\n"
        "                       extension deployment target, CRDT\n"
        "                       real-time collaboration, tenancy shape).\n"
        "                       Author the nearest-supported\n"
        "                       composition AND list what would need\n"
        "                       to be added in `suggested_extensions`.\n"
        "  status: `out_of_scope` — the brief asks for something\n"
        "                       structurally outside Forge: games,\n"
        "                       creative authoring (Photoshop, Ableton,\n"
        "                       video editors, IDEs, DAWs), spatial/\n"
        "                       AR/VR/voice-only, embedded firmware,\n"
        "                       browsers, emulators. DO NOT fabricate\n"
        "                       an app. Emit the verdict with a clear\n"
        "                       `reason` and `nearest_supported` — the\n"
        "                       pipeline halts and surfaces a refusal\n"
        "                       card to the user.\n"
        "\n"
        "Fields:\n"
        '  \"coverage_verdict\": {\n'
        '    \"status\": \"in_scope|extension_needed|out_of_scope\",\n'
        '    \"reason\": \"<one sentence>\",\n'
        '    \"nearest_supported\": \"<required unless in_scope>\",\n'
        '    \"missing_dimensions\": [\"<required for extension_needed>\"],\n'
        '    \"suggested_extensions\": [\"<optional>\"]\n'
        '  }\n'
        "\n"
        "Never quietly settle for a poor fit; a truthful `out_of_scope`\n"
        "is more useful than a broken app.\n"
        "\n"
        "═══════════════════════════════════════════════════════════════\n"
    )


# ══════════════════════════════════════════════════════════════════
# Post-parse enrichment
# ══════════════════════════════════════════════════════════════════


def enrich_plan(plan: dict[str, Any], brief: str = "") -> tuple[dict[str, Any], list[Finding]]:
    """Post-parse pass over a plan the LLM just emitted.

    - Runs the four axis validators + the coherence check.
    - For any invalid/missing field, fills from the keyword detector
      (per-field surgery — never overwrites a valid LLM emission).
    - Applies the industry ↔ domain compat bridge (M0-T1).

    Returns the (possibly repaired) plan and the list of findings.
    Empty findings = plan validates cleanly and is coherent.
    """
    findings: list[Finding] = []
    plan = dict(plan)  # never mutate caller's dict

    # ── M0-T1 compat bridge ──────────────────────────────────────
    plan = _bridge_industry_and_domain(plan)

    # ── Per-field repair from detectors ─────────────────────────
    if brief:
        _repair_shape_profile(plan, brief, findings)
        _repair_runtime_context(plan, findings)
        _repair_archetypes(plan, brief, findings)
        _ensure_coverage_verdict(plan, findings)

    # ── Validation pass (M1-T2..T5) ──────────────────────────────
    findings.extend(validate_all(plan))

    # ── Coherence check (M1-T9) ──────────────────────────────────
    from services.plan_coherence import check_plan_coherence
    findings.extend(check_plan_coherence(plan))

    # ── Compat bridge again after enrichment (industry might have
    # been filled by the detector) ──────────────────────────────
    plan = _bridge_industry_and_domain(plan)

    return (plan, findings)


def _bridge_industry_and_domain(plan: dict[str, Any]) -> dict[str, Any]:
    """M0-T1 compat bridge — read-both, write-both.

    `industry` is the canonical field going forward. `domain` is the
    legacy field, still read by many downstream stages (industry_design.py,
    fidelity_runner.py, ir_pipeline.py, etc). A hard rename is unsafe
    because `domain` is overloaded elsewhere (FK-role vocabulary,
    intent classifier's category). So we shadow both fields:

    - If only `industry` set → copy to `domain`.
    - If only `domain` set → copy to `industry`.
    - If both differ → `industry` wins (LLM's canonical answer).

    Never removes either field."""
    industry = plan.get("industry")
    domain = plan.get("domain")

    if industry and not domain:
        plan["domain"] = industry
    elif domain and not industry:
        plan["industry"] = domain
    elif industry and domain and industry != domain:
        # Both set to different values — industry is canonical.
        plan["domain"] = industry
    return plan


def _repair_shape_profile(plan: dict[str, Any], brief: str, findings: list[Finding]) -> None:
    """Per-field surgery for invalid app_shape values. Never
    overwrites a valid LLM emission — only fills the missing / bad."""
    from services.shape_profile import shape_primitive_values
    from services.shape_profile_detector import repair_single_field, detect_shape_profile

    raw = plan.get("app_shape")
    if not isinstance(raw, dict):
        # Whole profile missing — full detector rescue.
        profile, detector_findings = detect_shape_profile(brief)
        plan["app_shape"] = profile
        findings.extend(detector_findings)
        return

    # Per-field: check each slice + field; repair invalid values.
    schema = {
        "layout": ("shell", "hero", "primaryInteraction", "density"),
        "auth": ("surface", "gating"),
        "nav": ("menu", "back"),
        "workflows": ("executionMode",),
        "data": ("readShape", "denormalization"),
        "identity": ("usageMode",),
    }
    for slice_name, field_names in schema.items():
        section = raw.setdefault(slice_name, {})
        if not isinstance(section, dict):
            raw[slice_name] = section = {}
        for field_name in field_names:
            value = section.get(field_name)
            primitive = f"{slice_name}.{field_name}"
            try:
                allowed = shape_primitive_values(primitive)
            except KeyError:
                continue
            if value not in allowed:
                new_value, finding = repair_single_field(primitive, brief)
                section[field_name] = new_value
                findings.append(finding)


def _repair_runtime_context(plan: dict[str, Any], findings: list[Finding]) -> None:
    """Runtime context is multi-select over a closed set. Unknown
    values are dropped (never remapped — permission-related, we
    shouldn't guess). Missing field becomes empty list."""
    from services.shape_profile import runtime_capabilities

    raw = plan.get("runtime_context")
    if raw is None:
        plan["runtime_context"] = []
        return
    if not isinstance(raw, list):
        findings.append(Finding(
            rule="runtime_context.wrong_type_dropped",
            message=(
                f"plan.runtime_context was {type(raw).__name__}, expected "
                "list — dropped."
            ),
            severity="warning",
            axis="runtime_context",
        ))
        plan["runtime_context"] = []
        return
    valid = set(runtime_capabilities())
    kept: list[str] = []
    for item in raw:
        if isinstance(item, str) and item in valid and item not in kept:
            kept.append(item)
    if len(kept) != len(raw):
        findings.append(Finding(
            rule="runtime_context.unknown_values_dropped",
            message=(
                f"plan.runtime_context: dropped invalid entries; kept {kept}"
            ),
            severity="info",
            axis="runtime_context",
        ))
    plan["runtime_context"] = kept


def _repair_archetypes(plan: dict[str, Any], brief: str, findings: list[Finding]) -> None:
    """If archetypes is missing entirely, fall back to a single
    detector-authored instance. If individual instances reference
    unknown recipes, try to remap; otherwise fall through to
    capabilities."""
    from services.archetype_recipe_detector import (
        detect_archetype_instance,
        repair_unknown_recipe,
    )
    from services.shape_profile import known_recipes, safe_default_capabilities

    raw = plan.get("archetypes")
    if not raw or not isinstance(raw, list):
        instance, detector_findings = detect_archetype_instance(
            brief, module_name="main", routes=("/",)
        )
        plan["archetypes"] = [instance]
        findings.extend(detector_findings)
        return

    valid_recipes = set(known_recipes())
    for idx, inst in enumerate(raw):
        if not isinstance(inst, dict):
            continue
        recipe = inst.get("recipe")
        if recipe and recipe not in valid_recipes:
            remapped, finding = repair_unknown_recipe(recipe, brief)
            findings.append(finding)
            if remapped:
                inst["recipe"] = remapped
            else:
                # Fall through to safe-default capabilities so downstream
                # stages have SOMETHING to read.
                inst.pop("recipe", None)
                if not inst.get("capabilities"):
                    inst["capabilities"] = safe_default_capabilities()


def _ensure_coverage_verdict(plan: dict[str, Any], findings: list[Finding]) -> None:
    """If missing, default to in_scope (the pipeline is tolerant per
    M2-T7). Log an info finding — quality dashboard tracks the rate."""
    raw = plan.get("coverage_verdict")
    if isinstance(raw, dict) and raw.get("status"):
        return
    plan["coverage_verdict"] = {
        "status": "in_scope",
        "reason": "no explicit verdict emitted by planner; defaulted to in_scope",
    }
    findings.append(Finding(
        rule="coverage_verdict.defaulted",
        message="planner did not emit coverage_verdict; defaulted to in_scope",
        severity="info",
        axis="coverage_verdict",
    ))


# ══════════════════════════════════════════════════════════════════
# REVISE prompt builder (M1-T10)
# ══════════════════════════════════════════════════════════════════


def format_findings_for_revise(findings: list[Finding]) -> str | None:
    """Format shape-related findings as the "GAPS TO FIX" block the
    planner's existing REVISE MODE already understands. Returns None
    when there's nothing that warrants a REVISE (all info + defaulted
    entries)."""
    revisable = [
        f for f in findings
        if f.severity in ("error", "warning")
        and f.rule != "coverage_verdict.defaulted"
    ]
    if not revisable:
        return None

    lines = ["GAPS TO FIX (shape substrate — please reconcile in the next plan-json):", ""]
    for f in revisable:
        lines.append(f"  • [{f.axis or 'plan'}] {f.rule}")
        lines.append(f"      {f.message}")
    lines.append("")
    lines.append("Re-emit the plan-json with these fields corrected. Keep every other field unchanged.")
    return "\n".join(lines)
