"""SMITH-SOURCE-1: point Smith at the backend generator that produced an
artifact class, so he can propose a source fix instead of N in-place edits.

The problem this cures — a bug that affects N pages the same way (like
the "Status dropdown polluted with entity names" bug we just fixed via
HAR-1) is a GENERATOR bug, not a per-page bug. Smith today would try to
edit each of the N pages individually — even if he succeeds, the next
generation regenerates the same bug. Fixing at the source (the emitter
module) durably closes the class.

``find_source_generator(symptom)`` maps a symptom keyword or artifact
kind to the backend module(s) most likely responsible. Smith uses the
result to decide: propose a `handoff_to_pipeline("refine")` OR ask the
user to escalate to a source-code fix, rather than commit N in-place
edits that will regress on the next gen.

Deliberately heuristic — a real source-graph would require reverse-
mapping emitter code, which is orders of magnitude more work than a
curated dictionary. The dictionary covers the ~20 emitter modules
that produce ~95% of the artifacts a user complains about.
"""
from __future__ import annotations

import re


# ─── Source-generator map ────────────────────────────────────────────────
# Each entry is (compiled regex over the symptom text, list of likely
# backend modules that emit this class of artifact). First-match wins;
# multiple modules are returned when the responsibility is shared.
_SOURCE_MAP: list[tuple[re.Pattern[str], list[str], str]] = [
    # PLATFORM-HEALS class (cwx1stzz 2026-08-21) — cramped layout, fused
    # components, collapsed KPI grids, server-null-but-API-has-data,
    # impossible filter options. All repairable in place with ONE call.
    (re.compile(r"\b(cramp|no\s*space|no\s*gap|squeez|fused|stuck\s*together|"
                r"collaps\w*\s*(grid|column)|2\s*column)", re.I),
     ["backend/services/platform_heals.py::apply_platform_heals"],
     "Known platform-regression class. Run the heal_platform_regressions "
     "tool FIRST — it repairs spacing tokens, skin !important grid "
     "collapse, and the Tailwind safelist in one idempotent call."),
    (re.compile(r"(null|empty|0|zero).{0,40}\b(api|database|db)\b.{0,40}"
                r"(has|shows|returns)|breakdown.{0,20}(0|zero)", re.I),
     ["backend/templates/runtime/rules/engine.ts::canAccessField",
      "backend/services/platform_heals.py::sync_template_runtime_files"],
     "Rules-engine grant-union class: a role-scoped GRANT used to deny "
     "every other role server-side. heal_platform_regressions re-syncs "
     "the fixed engine into this app."),
    (re.compile(r"(filter|dropdown).{0,40}(doesn.?t\s*(match|exist)|no\s*result|"
                r"never\s*match|wrong\s*(option|value|status))", re.I),
     ["backend/services/platform_heals.py::align_dashboard_filter_enums"],
     "Invented filter enums: options must come from the plan's "
     "enum_values. heal_platform_regressions rewrites them."),
    # Status / enum dropdowns polluted or wrong
    (re.compile(r"\b(status|enum|dropdown)\b.*?(pollut|wrong|garbage|leak|extra)", re.I),
     ["backend/services/form_scaffold.py::ensure_enum_selects",
      "backend/services/semantic_field_types.py::harvest_workflow_statuses"],
     "Enum harvester over-scope. See HAR-1 for the pattern."),

    # Detail page shows empty values / labels-only
    (re.compile(r"\b(detail|show|view)\b.*?(empty|blank|missing|no.?data|not.?populat)", re.I),
     ["backend/templates/standalone-app/src/app/[...slug]/page.tsx",
      "backend/templates/app-foundation/src/lib/data-engine-bridge.ts",
      "backend/services/runtime_injector.py::_build_entity_alias_map"],
     "DV-BIND-1/2 class: catch-all can't map URL slug to schema, or entity "
     "alias missing route stem."),

    # Edit form doesn't prefill / has no dataSources
    (re.compile(r"\bedit\b.*?(prefill|populat|initial|default|empty)", re.I),
     ["backend/services/ensure_edit_routes.py::backfill_edit_defaults",
      "backend/services/ensure_edit_routes.py::build_edit_schema"],
     "DV-BIND-3 class: Form defaultValues prop missing → React Hook Form "
     "ignores per-Input defaultValue bindings."),

    # Edit / row button navigates to wrong entity or missing id
    (re.compile(r"\b(edit|button)\b.*?(wrong.*(entity|url|route|link)|404|missing.*id)", re.I),
     ["backend/services/ensure_edit_routes.py::_rewrite_edit_buttons",
      "backend/services/ensure_edit_routes.py::_detail_dataSource_name"],
     "DV-BIND-4 class: button entity-picker fell back to first-in-dict; or "
     "used {{item.id}} on detail page where record binds as {{<ds>.id}}."),

    # Workflow node emits wrong shape / values
    (re.compile(r"\bworkflow\b.*(wrong|missing|empty|null)", re.I),
     ["backend/services/workflow_translator.py",
      "backend/services/workflow_input_map_backfill.py",
      "backend/services/workflow_value_types.py"],
     "Workflow translator / input-map backfill / value-type coercion."),

    # Menu / shell doesn't include a page
    (re.compile(r"\b(menu|sidebar|nav|shell)\b.*(missing|not.?show|absent)", re.I),
     ["backend/services/shell_menu_sync.py",
      "backend/services/nav_flow_from_plan.py"],
     "Shell menu sync derives from nav-flow.json; the page may lack "
     "visibleTo scoping or shell:true."),

    # Login / signup pages broken
    (re.compile(r"\b(login|signup|register|auth)\b.*(broken|not.?work|missing|redirect)", re.I),
     ["backend/services/auth_pages.py",
      "backend/services/nav_flow_from_plan.py"],
     "Auth pages emitter / nav-flow auth-route flagging."),

    # Forms don't submit / dispatch
    (re.compile(r"\b(form|submit|save)\b.*(nothing|not.?work|no.?action|fail)", re.I),
     ["backend/services/workflow_launch_forms.py",
      "backend/services/action_contract_guard.py",
      "backend/templates/runtime/workflows/engine.ts"],
     "Form workflow dispatch: launch-form generator, action-contract "
     "reconciliation, runtime engine."),

    # Wrong plan / planner-shaped complaints
    (re.compile(r"\b(plan|planner)\b.*(too.?many|too.?few|wrong.*(pages|entities|workflows))", re.I),
     ["backend/agents/planner.py",
      "backend/services/plan_wire_pipeline.py"],
     "Planner one-shot + plan-wire primitives."),

    # FK / relations / dropdown of records
    (re.compile(r"\b(fk|foreign.?key|relation|dropdown.*record)\b", re.I),
     ["backend/services/repair_fk_dropdowns.py",
      "backend/services/schema_builder.py"],
     "FK dropdown resolver / schema builder relations."),

    # Post-generate guard failures
    (re.compile(r"\b(guard|validator|post.?generat)\b", re.I),
     ["backend/services/post_generate_fixes.py"],
     "Post-generate pipeline of ~20 guards; each is a separate module."),

    # Self-heal itself misbehaves
    (re.compile(r"\bself.?heal\b", re.I),
     ["backend/services/self_healing.py",
      "backend/routers/runtime_exceptions.py"],
     "Runtime-error healing loop + the exception ingestion route."),
]


def find_source_generator(symptom: str) -> dict:
    """Map a user's symptom description to the backend emitter module(s)
    most likely responsible for the class of bug.

    Returns::

        {
          "matched": True,
          "modules": ["backend/services/foo.py::bar", ...],
          "hint": "one-line description",
          "recommendation": "propose_source_fix" | "in_place_edit_ok"
        }

    When ``matched=False``, no known emitter pattern hit — Smith should
    prefer an in-place edit and let the user escalate if it regresses.

    Deliberately conservative: only recommends ``propose_source_fix``
    when the symptom clearly names a class of artifact (>1 page/
    workflow), not a one-off. A single "the label on this button is
    wrong" is an in-place edit; "every status dropdown across the app
    shows garbage" is a source fix.
    """
    if not isinstance(symptom, str) or not symptom.strip():
        return {"matched": False, "modules": [], "hint": "", "recommendation": "in_place_edit_ok"}

    for regex, modules, hint in _SOURCE_MAP:
        if regex.search(symptom):
            recommendation = _recommend(symptom)
            return {
                "matched": True,
                "modules": modules,
                "hint": hint,
                "recommendation": recommendation,
            }

    return {"matched": False, "modules": [], "hint": "no known emitter pattern for this symptom", "recommendation": "in_place_edit_ok"}


def _recommend(symptom: str) -> str:
    """Detect signals in the symptom text that suggest a systemic bug
    (affects many pages) vs a one-off. Returns:
      - ``"propose_source_fix"`` when the symptom implies breadth
      - ``"in_place_edit_ok"`` when scoped to a single artifact
    """
    breadth_signals = re.compile(
        r"\b(every|all|any|multiple|across|throughout|whole|entire|both|"
        r"everywhere|repeatedly|always|systematic|generic)\b", re.I,
    )
    if breadth_signals.search(symptom):
        return "propose_source_fix"
    # Numbers ≥ 2 as a hint (e.g. "3 forms" or "5 pages")
    if re.search(r"\b([2-9]|\d{2,})\s+(page|form|workflow|entit|screen)", symptom, re.I):
        return "propose_source_fix"
    return "in_place_edit_ok"
