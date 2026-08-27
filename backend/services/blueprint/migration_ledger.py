"""Migration ledger — where each of the 151 post-generation passes goes.

The old pipeline's repair chain (``services/post_generate_fixes.py``, 151
sequential passes over 63 guard modules) is architecturally excluded by §120:
it mutates application behaviour without passing through the Blueprint. But
every one of those passes exists because a real application shipped broken. The
chain is the platform's accumulated knowledge in its least usable form.

This ledger is the translation. Each pass gets exactly one disposition:

``constraint``
    The defect becomes unrepresentable. A Blueprint field or type means the
    wrong state cannot be described, so nothing needs to detect it.
    *Example:* ``fk_type_guard`` fixed FK columns whose type didn't match the
    referenced PK. With ``Relationship`` declaring both ends, a mismatched type
    is not a thing you can write down.

``guardrail``
    §30 capability. The agent that used to produce the defect no longer has
    permission to touch that section at all.
    *Example:* ``sensitive_column_guard`` stripped PII columns the page agent
    had exposed. The page agent cannot write ``data.entities``.

``edge``
    §75 verification. The inconsistency is real, cross-cutting and detectable —
    so it is detected and flagged ``OUT_OF_SYNC``, and the owning agent gets a
    repair task. Detection survives; the silent repair does not.

``emitter``
    Not a repair at all. Legitimate deterministic code generation *from* the
    Blueprint — CSS from ``designSystem``, config files, seed data. These
    belong downstream of the Blueprint and keep working as-is.

``dead``
    Obsolete under the new architecture. Mostly bookkeeping for the chain
    itself, LLM-output repair the agent contract now rejects up front, and
    dedup passes that cannot fire once IDs are allocated by natural key.

Everything marked ``needs_review`` is a judgement I could not make from the
pass's docstring and call site alone. Those are the rows to argue about; the
rest are mechanical.

``tests/services/test_migration_ledger.py`` asserts every target named here is
real — an edge that exists in §75, a section an agent can actually write, a
field the Blueprint schema actually has. A ledger whose targets have drifted is
worse than no ledger.
"""
from __future__ import annotations

from dataclasses import dataclass

DISPOSITIONS = ("constraint", "guardrail", "edge", "emitter", "dead")


@dataclass(frozen=True)
class Entry:
    step: int
    module: str
    disposition: str
    target: str = ""
    note: str = ""
    needs_review: bool = False


def _e(step, module, disposition, target="", note="", review=False) -> Entry:
    return Entry(step, module, disposition, target, note, review)


LEDGER: tuple[Entry, ...] = (
    # -- chain bookkeeping: the chain is gone ------------------------------
    _e(1, "guard_result", "dead", note="log capture for the chain itself"),
    _e(2, "post_gen_phases", "dead", note="per-run completion counter for the chain"),
    _e(3, "post_gen_phases", "dead", note="ditto"),
    _e(151, "post_gen_phases", "dead", note="ditto"),

    # -- repairing LLM output: the agent contract refuses it instead -------
    _e(4, "schema_json_repair", "dead",
       note="§29 rejects malformed agent output; nothing to repair afterwards"),
    _e(41, "alias_unknown_components", "edge", "Design↔DesignSystem",
       note="unknown component types are a registry violation, now detected"),
    _e(38, "chart_type_alias", "edge", "Design↔DesignSystem",
       note="hallucinated chart types are the same registry violation"),

    # -- duplicates: impossible once IDs are allocated by natural key ------
    _e(5, "schema_dedup_guard", "dead",
       note="IdAllocator keys on natural identity; a second Candidate is the first"),
    _e(128, "route_dedup", "dead", note="page_key(route) makes duplicate routes one page"),
    _e(129, "route_dedup", "dead", note="ditto"),
    _e(130, "route_dedup", "dead", note="ditto"),

    # -- data model -------------------------------------------------------
    _e(6, "schema_import_guard", "emitter", note="codegen import wiring"),
    _e(15, "drizzle_column_guard", "emitter", note="Drizzle emission from data.entities"),
    _e(16, "drizzle_check_guard", "emitter", note="Drizzle emission from constraints"),
    _e(17, "fk_type_guard", "constraint", "data.relationships",
       note="Relationship declares both ends; a type mismatch is not writable"),
    _e(90, "fk_source_guard", "edge", "API↔Database",
       note="an FK pointing at a non-entity is a reference violation"),
    _e(55, "fk_label_columns", "constraint", "data.entities.labelField"),
    _e(83, "sensitive_column_guard", "constraint", "data.entities.fields.sensitive",
       note="also a guardrail: page_design cannot write data.entities"),
    _e(42, "semantic_field_types", "constraint", "data.entities.fields.type"),
    _e(18, "seed_synthesizer", "emitter", note="§61 seed generation from the data model"),

    # -- forms ------------------------------------------------------------
    _e(33, "form_scaffold", "constraint", "data.entities.fields",
       note="form inputs derive from entity fields; nothing to scaffold after"),
    _e(34, "form_scaffold", "edge", "API↔Database", note="FK dropdown to a real entity"),
    _e(35, "form_scaffold", "constraint", "data.entities.fields.required"),
    _e(36, "form_scaffold", "constraint", "data.entities.fields.enumValues"),
    _e(126, "form_ux_invariants", "constraint", "pages.states",
       note="NN/g form invariants; partly emitter — see review", review=True),
    _e(25, "file_first_forms", "emitter", note="upload UI emission"),
    _e(137, "file_preview_guard", "emitter"),

    # -- pages and routes -------------------------------------------------
    _e(13, "stub_page_backfill", "constraint", "pages.states",
       note="empty is a declared state, not a discovery"),
    _e(79, "unbound_placeholder_text", "constraint", "pages.states"),
    _e(94, "bare_container_guard", "constraint", "pages.states"),
    _e(93, "dashboard_completeness", "constraint", "pages.pattern"),
    _e(78, "dashboard_slot_fit", "constraint", "pages.pattern"),
    _e(67, "dashboard_anatomy", "constraint", "pages.pattern"),
    _e(68, "apply_dashboard_maquette", "constraint", "pages.pattern"),
    _e(69, "dashboard_authority", "constraint", "pages.pattern"),
    _e(71, "dashboard_page_composer", "constraint", "pages.pattern"),
    _e(72, "apply_collection_maquette", "constraint", "pages.pattern"),
    _e(73, "apply_record_maquette", "constraint", "pages.pattern"),
    _e(132, "page_anatomy", "constraint", "pages.pattern"),
    _e(131, "density_frames", "constraint", "designSystem.informationDensity"),
    _e(74, "section_layout", "constraint", "pages.pattern"),
    _e(20, "ensure_edit_routes", "constraint", "pages.route",
       note="CRUD routes derive from the entity + pattern"),
    _e(54, "ensure_edit_routes", "constraint", "pages.route"),
    _e(142, "ensure_edit_routes", "constraint", "pages.route",
       note="junk create pages cannot be created if routes are derived"),
    _e(95, "route_intent_apply", "constraint", "pages.purpose",
       note="route intent is the page's declared purpose"),
    _e(19, "detail_polish", "constraint", "pages.pattern"),
    _e(53, "context_panel_builder", "constraint", "pages.pattern"),
    _e(143, "record_subresource_tabs", "constraint", "pages.pattern"),
    _e(51, "edge_page_customizer", "emitter"),
    _e(50, "edge_page_customizer", "emitter"),
    _e(118, "archetype_page_fixes", "dead", note="single-app special-casing"),
    _e(119, "archetype_page_fixes", "dead", note="ditto"),
    _e(120, "archetype_page_fixes", "dead", note="ditto"),

    # -- navigation -------------------------------------------------------
    _e(88, "nav_route_reconcile_guard", "edge", "Navigation↔Page"),
    _e(96, "navigate_target_guard", "edge", "Navigation↔Page",
       note="the dead 'View details' button class"),
    _e(76, "nav_entity_dedup", "constraint", "navigation.tree"),
    _e(77, "shell_menu_sync", "emitter", note="shell menu derived from navigation"),
    _e(144, "shell_menu_sync", "emitter", note="re-entrant with 77; one derivation now"),
    _e(59, "nav_transitions", "emitter"),
    _e(133, "page_nav", "constraint", "navigation.tree", note="breadcrumbs from the tree"),
    _e(134, "page_nav", "emitter"),
    _e(37, "humanize_nav_flow_labels", "emitter",
       note="labels derived from terminology; the 'batchs' class of bug"),

    # -- read bindings / data sources -------------------------------------
    _e(9, "list_data_source_guard", "edge", "Page↔API"),
    _e(64, "list_data_source_guard", "edge", "Page↔API", note="re-entrant with 9"),
    _e(91, "read_binding_guard", "edge", "Page↔API"),
    _e(12, "widget_data_source_guard", "constraint", "widgets",
       note="Widget.dataSource is required; a hardcoded widget will not parse"),
    _e(81, "widget_data_contract", "edge", "Widget↔DataSource"),
    _e(80, "widget_data_contract", "edge", "Widget↔DataSource"),
    _e(92, "aggregate_metrics_guard", "constraint", "widgets",
       note="the aggregate variant requires an aggregation"),
    _e(62, "chart_data_source_guard", "constraint", "widgets",
       note="a series without groupBy will not parse"),
    _e(75, "kpi_format_honesty", "edge", "Widget↔DataSource",
       note="a count formatted as a percent; the 1,000% utilisation bug"),
    _e(87, "filter_field_guard", "edge", "Page↔API"),
    _e(82, "list_entity_coherence_guard", "edge", "Page↔API"),
    _e(63, "schema_references", "edge", "Page↔API"),
    _e(136, "binding_prop_normalizer", "constraint", "pages",
       note="binding shape is schema-enforced"),
    _e(141, "binding_smoke", "edge", "Widget↔DataSource"),

    # -- actions / CRUD ---------------------------------------------------
    _e(10, "crud_invariants", "constraint", "pages.actions"),
    _e(11, "action_invariants", "constraint", "pages.actions"),
    _e(84, "action_contract_guard", "edge", "Page↔Workflow"),
    _e(85, "action_contract_guard", "edge", "Page↔Workflow"),
    _e(86, "detail_action_guard", "edge", "Page↔Workflow"),
    _e(57, "table_row_nav_guard", "edge", "Navigation↔Page"),

    # -- workflows --------------------------------------------------------
    _e(7, "workflow_table_guard", "edge", "Workflow↔API"),
    _e(8, "workflow_mutation_guard", "guardrail", "workflows",
       note="only the workflow agent may write workflows"),
    _e(14, "self_heal", "dead", note="missing workflows are a DAG gap, not a repair"),
    _e(22, "workflow_launch_forms", "constraint", "workflows.launchedFrom"),
    _e(24, "orphan_wiring_pass", "edge", "Page↔Workflow"),
    _e(26, "submit_authority_guards", "edge", "Page↔Workflow"),
    _e(27, "submit_authority_guards", "edge", "Page↔Workflow"),
    _e(28, "workflow_trigger_button_guard", "edge", "Page↔Workflow"),
    _e(29, "workflow_input_map_backfill", "constraint", "workflows.steps"),
    _e(30, "workflow_input_map_backfill", "constraint", "workflows.steps"),
    _e(31, "workflow_values_clean_guard", "constraint", "workflows.steps"),
    _e(32, "workflow_form_field_pruner", "constraint", "workflows.steps"),
    _e(104, "workflow_graph_gate", "edge", "Workflow↔API"),
    _e(105, "workflow_variable_reconcile", "constraint", "workflows.steps"),
    _e(106, "workflow_validator", "edge", "Workflow↔API"),
    _e(107, "workflow_validator", "edge", "Workflow↔API"),
    _e(147, "workflow_trigger_backfill", "constraint", "workflows.trigger"),
    _e(23, "task_notification_defaults", "constraint", "workflows.steps"),

    # -- rules ------------------------------------------------------------
    _e(113, "rules_validator", "edge", "Workflow↔BusinessRule"),
    _e(114, "rules_validator", "edge", "Workflow↔BusinessRule"),
    _e(138, "rules_sanity", "edge", "Workflow↔BusinessRule"),

    # -- validators that ARE the matrix ------------------------------------
    _e(108, "contract_validator", "edge", "Page↔API"),
    _e(109, "contract_validator", "edge", "Page↔API"),
    _e(110, "proof_pass", "edge", "Blueprint↔Implementation"),
    _e(111, "proof_pass", "edge", "Blueprint↔Implementation"),
    _e(140, "page_contract_validator", "dead",
       note="page shape is validated by the Blueprint schema at write time"),
    _e(139, "page_contract_repair", "dead", note="required props are schema defaults"),
    _e(115, "proof_auto_heal", "dead",
       note="§120: auto-heal is the repair half, architecturally excluded"),
    _e(116, "proof_auto_heal", "dead", note="ditto"),
    _e(52, "residual_placeholder_guard", "edge", "Requirement↔Code"),
    _e(40, "requirement_fidelity_critic", "edge", "Requirement↔Code"),
    _e(149, "delivery_gate", "edge", "Blueprint↔Implementation"),
    _e(135, "transition_materializer", "edge", "Blueprint↔Implementation"),

    # -- design system → CSS/assets: legitimate emission --------------------
    _e(43, "motion_tokens_writer", "emitter"),
    _e(44, "motion_tokens_writer", "emitter"),
    _e(148, "motion_authority", "edge", "Design↔DesignSystem"),
    _e(49, "interactions_css_inject", "emitter"),
    _e(112, "rtl_scope_guard", "emitter"),
    _e(89, "surface_border_guard", "emitter"),
    _e(61, "surface_wrap_guard", "constraint", "pages.pattern"),
    _e(125, "surface_treatment_pass", "emitter"),
    _e(124, "aesthetic_profile_picker", "constraint", "designSystem"),
    _e(123, "design_brief_to_prompt", "constraint", "designSystem"),
    _e(45, "apply_signature_moves", "constraint", "designSystem"),
    _e(46, "apply_signature_moves", "constraint", "designSystem"),
    _e(47, "logo_generator", "emitter"),
    _e(48, "illustrated_empty_pass", "constraint", "pages.states"),
    _e(99, "token_completeness_guard", "constraint", "designSystem"),
    _e(97, "text_template_backstop", "emitter",
       note="mechanical strings derive from terminology; agents must not author them"),

    # -- platform / infrastructure ----------------------------------------
    _e(56, "next_config_guard", "emitter"),
    _e(58, "auth_gate_guard", "constraint", "security.authentication"),
    _e(100, "platform_heals", "dead", note="grab-bag of chain-era repairs", review=True),
    _e(102, "emit_verify_container", "emitter"),
    _e(117, "verify_trigger", "emitter", note="dispatches the §77 test run"),
    _e(146, "test_suite_emitter", "emitter", note="§77 generated tests"),
    _e(145, "plan_writeback", "dead",
       note="§115: the Blueprint is the plan; nothing to write back into"),
    _e(121, "blueprint_writer", "dead", note="superseded by BlueprintService"),
    _e(122, "page_critic_summary", "emitter"),
    _e(127, "substrate_brief_writer", "emitter"),
    _e(150, "scorecard", "emitter", note="keep — the fleet scoreboard depends on it"),
    _e(60, "figma_overlay_strip", "dead", note="artifact of the split Figma pipeline (§5)"),
    _e(101, "mobile_scaffold", "dead", note="§106 native mobile is a V1 non-goal"),
    _e(103, "mobile_branding", "dead", note="§106"),
    _e(21, "payment_feature", "constraint", "integrations", review=True),
    _e(98, "commerce_placement", "constraint", "product.capabilities", review=True),
    _e(39, "apply_hints_to_pages", "constraint", "pages", review=True),
    _e(65, "a2ui_authority", "emitter", note="§34 A2UI is the page-generation capability"),
    _e(66, "a2ui_authority", "emitter"),
    _e(70, "library_manifest", "constraint", "uiRegistry"),
)


def by_disposition() -> dict[str, list[Entry]]:
    out: dict[str, list[Entry]] = {d: [] for d in DISPOSITIONS}
    for e in LEDGER:
        out[e.disposition].append(e)
    return out


def summary() -> dict[str, int]:
    counts = {d: len(v) for d, v in by_disposition().items()}
    counts["total"] = len(LEDGER)
    counts["needs_review"] = sum(1 for e in LEDGER if e.needs_review)
    return counts


def new_edges_required() -> set[str]:
    """§75 edges this migration adds beyond the ten the PRD names."""
    from services.blueprint.verification import EDGES
    return {e.target for e in LEDGER if e.disposition == "edge"} - set(EDGES)
