"""FaultReport renderer — SV-6.

Takes the raw RunReport from `forge-verify` (SV-3 shape) + runs the
classifier from SV-2 over each fault, then renders a structured markdown
prompt Smith can act on directly (spec §5.4/5.5).

The renderer is where 80% of the fix-loop's value lives — Smith needs
tool hints + hypotheses right at the top of the prompt so it doesn't
grep-hunt for context. The plan-app-map insight applied to defects.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from services.fault_classifier import Evidence, FaultClassification, LogEntry, NetworkEntry, classify
from services.interaction_extractor import (
    ButtonAction,
    ButtonInteraction,
    DetailInteraction,
    FieldSpec,
    FormInteraction,
    FormSubmit,
    Interaction,
    ListInteraction,
    RouteInteraction,
    WorkflowInput,
)


# ── Classified fault ────────────────────────────────────────────────────


@dataclass(frozen=True)
class Fault:
    """A classified fault the runner observed + the extractor set up."""

    id: str
    interaction: Interaction
    signature: str
    priority: str      # BLOCKER > BROKEN > CONTENT > FLAKY
    layer: str
    hypothesis: str
    suggested_tools: tuple[str, ...]
    evidence: Evidence
    # SV-STRICT-2a: which W-slot of the component's contract this fault falsifies
    w_slot: str = "what"
    # SV-STRICT-2b: which ComponentContract this fault attaches to (None
    # when the contract layer wasn't built or didn't cover the shape).
    contract_id: str | None = None


@dataclass
class FaultReport:
    run_id: str
    project_id: str
    round: int
    target: str
    base_url: str
    started_at: str
    finished_at: str
    interactions_run: int
    interactions_passed: int
    interactions_flaky: int
    faults: list[Fault] = field(default_factory=list)
    # SV-STRICT-2b: full ComponentContract set, if the caller supplied
    # ``output_dir`` to :func:`build_report_from_runner`. Empty otherwise —
    # existing callers keep the same shape.
    contracts: list[dict] = field(default_factory=list)


# ── Priority-sort helper ────────────────────────────────────────────────

_PRIORITY_ORDER = {"BLOCKER": 0, "BROKEN": 1, "CONTENT": 2, "FLAKY": 3}


def _priority_key(f: Fault) -> tuple[int, str]:
    return (_PRIORITY_ORDER.get(f.priority, 99), f.id)


# ── Building faults from the runner's raw JSON ──────────────────────────


def _hydrate_interaction(raw: dict) -> Interaction:
    """Rebuild an Interaction dataclass from a JSON dict.

    The runner passed the interaction through unchanged, so the shape
    matches interaction_extractor's dataclasses field-for-field.
    """
    kind = raw.get("kind")
    if kind == "route":
        return RouteInteraction(
            id=raw["id"], kind="route",
            route=raw["route"], requires_auth=bool(raw.get("requires_auth", False)),
            label=raw.get("label", ""),
        )
    if kind == "button":
        a = raw.get("action") or {}
        return ButtonInteraction(
            id=raw["id"], kind="button",
            route=raw.get("route", ""), selector=raw.get("selector", ""),
            label=raw.get("label", ""),
            action=ButtonAction(
                kind=a.get("kind", "none"),
                workflow_target=a.get("workflow_target"),
                navigate_target=a.get("navigate_target"),
                compute_target=a.get("compute_target"),
                compute_formula=a.get("compute_formula"),
            ),
        )
    if kind == "form":
        s = raw.get("submit") or {}
        fields_raw = raw.get("fields") or []
        inputs_raw = s.get("workflow_inputs") or []
        return FormInteraction(
            id=raw["id"], kind="form",
            route=raw.get("route", ""), selector=raw.get("selector", ""),
            fields=tuple(FieldSpec(
                name=f.get("name", ""),
                type=f.get("type", "text"),
                required=bool(f.get("required", False)),
                options=tuple(f.get("options") or ()),
                fk_entity=f.get("fk_entity"),
            ) for f in fields_raw),
            submit=FormSubmit(
                kind=s.get("kind", "none"),
                workflow_target=s.get("workflow_target"),
                workflow_inputs=tuple(WorkflowInput(
                    name=i.get("name", ""),
                    type=i.get("type", "text"),
                    required=bool(i.get("required", False)),
                    options=tuple(i.get("options") or ()),
                ) for i in inputs_raw),
                dataSource_target=s.get("dataSource_target"),
            ),
        )
    if kind == "list":
        return ListInteraction(
            id=raw["id"], kind="list",
            route=raw.get("route", ""), selector=raw.get("selector", ""),
            dataSource=raw.get("dataSource", ""),
            entity=raw.get("entity"),
            seed_min_rows=int(raw.get("seed_min_rows", 1)),
        )
    if kind == "detail":
        return DetailInteraction(
            id=raw["id"], kind="detail",
            route=raw.get("route", ""), entity=raw.get("entity"),
            param_name=raw.get("param_name", "id"),
        )
    raise ValueError(f"unknown interaction kind: {kind!r}")


def _hydrate_evidence(raw: dict) -> Evidence:
    ev = Evidence()
    if not raw:
        return ev
    ev.status = raw.get("status")
    ev.body_excerpt = raw.get("body_excerpt")
    ev.console = [
        LogEntry(level=str(c.get("level", "log")), text=str(c.get("text", "")))
        for c in (raw.get("console") or [])
    ]
    ev.network_log = [
        NetworkEntry(
            method=str(n.get("method", "GET")),
            url=str(n.get("url", "")),
            status=int(n.get("status", 0)),
        )
        for n in (raw.get("network_log") or [])
    ]
    ev.dom_snapshot = raw.get("dom_snapshot")
    ev.stack_trace = raw.get("stack_trace")
    ev.screenshot_uri = raw.get("screenshot_uri")
    ev.url_after_click = raw.get("url_after_click")
    ev.computed_value_actual = raw.get("computed_value_actual")
    ev.computed_value_expected = raw.get("computed_value_expected")
    ev.rows_returned = raw.get("rows_returned")
    ev.timed_out = bool(raw.get("timed_out", False))
    ev.rendered_widget_count = raw.get("rendered_widget_count")
    return ev


def build_report_from_runner(
    runner_report: dict,
    *,
    round_: int = 1,
    output_dir: str | None = None,
) -> FaultReport:
    """Convert forge-verify's raw RunReport into a classified FaultReport.

    When ``output_dir`` is supplied, the report also carries the
    :mod:`services.component_contract` set for the app and every fault
    is annotated with the ``contract_id`` it joins to (SV-STRICT-2b).
    Legacy callers omit the arg and get the pre-existing shape (empty
    ``contracts`` list, ``contract_id=None`` on every fault).
    """
    faults: list[Fault] = []
    for raw in runner_report.get("faults") or []:
        interaction = _hydrate_interaction(raw.get("interaction") or {})
        evidence = _hydrate_evidence(raw.get("evidence") or {})
        cls: FaultClassification = classify(interaction, evidence)
        faults.append(Fault(
            id=raw.get("interaction_id") or interaction.id,
            interaction=interaction,
            signature=cls.signature,
            priority=cls.priority,
            layer=cls.layer,
            hypothesis=cls.hypothesis,
            suggested_tools=cls.suggested_tools,
            evidence=evidence,
            w_slot=cls.w_slot,
        ))
    faults.sort(key=_priority_key)

    contracts_out: list[dict] = []
    if output_dir:
        try:
            from services.component_contract import (
                extract_component_contracts, to_dict as _contract_to_dict,
            )
            from services.contract_fault_join import join_faults_to_contracts

            contracts = extract_component_contracts(output_dir)
            joined = join_faults_to_contracts(faults, contracts)
            # Rewrite Fault entries with contract_id in-place (dataclass
            # is frozen — rebuild the list).
            faults = [
                Fault(
                    id=f.id, interaction=f.interaction, signature=f.signature,
                    priority=f.priority, layer=f.layer, hypothesis=f.hypothesis,
                    suggested_tools=f.suggested_tools, evidence=f.evidence,
                    w_slot=f.w_slot,
                    contract_id=joined.get(f.id),
                )
                for f in faults
            ]
            contracts_out = [_contract_to_dict(c) for c in contracts]
        except Exception:  # noqa: BLE001 — never break report on join failure
            contracts_out = []

    return FaultReport(
        run_id=runner_report.get("run_id", ""),
        project_id=runner_report.get("project_id", ""),
        round=round_,
        target=runner_report.get("target", "preview"),
        base_url=runner_report.get("base_url", ""),
        started_at=runner_report.get("started_at", ""),
        finished_at=runner_report.get("finished_at", ""),
        interactions_run=int(runner_report.get("interactions_run", 0)),
        interactions_passed=int(runner_report.get("interactions_passed", 0)),
        interactions_flaky=int(runner_report.get("interactions_flaky", 0)),
        faults=faults,
        contracts=contracts_out,
    )


# ── Markdown render for Smith ───────────────────────────────────────────


def _interaction_context(i: Interaction) -> str:
    if isinstance(i, RouteInteraction):
        auth = " (auth required)" if i.requires_auth else ""
        return f"Route: `{i.route}`{auth}"
    if isinstance(i, ButtonInteraction):
        a = i.action
        target = (a.workflow_target or a.navigate_target or a.compute_target or "—")
        return (
            f"Page: `{i.route}`\n- Button: **{i.label or '(unlabeled)'}**\n"
            f"- Action kind: `{a.kind}` → `{target}`"
        )
    if isinstance(i, FormInteraction):
        s = i.submit
        target = s.workflow_target or s.dataSource_target or "—"
        return (
            f"Page: `{i.route}`\n- Form → `{s.kind}`:`{target}`\n"
            f"- Fields: {', '.join(f.name for f in i.fields) or '(none extracted)'}"
        )
    if isinstance(i, ListInteraction):
        return (
            f"Page: `{i.route}`\n- Table dataSource: `{i.dataSource}` "
            f"(entity `{i.entity or '?'}`)"
        )
    if isinstance(i, DetailInteraction):
        return f"Route: `{i.route}` (entity `{i.entity or '?'}`, param `{i.param_name}`)"
    return f"Interaction: {i}"


def _evidence_slice(ev: Evidence) -> str:
    """Compact evidence summary — the classifier already extracted the
    signature; the human/Smith just needs enough to confirm + act."""
    parts: list[str] = []
    if ev.status is not None:
        parts.append(f"HTTP {ev.status}")
    if ev.timed_out:
        parts.append("TIMED OUT")
    if ev.rows_returned is not None:
        parts.append(f"rows_returned={ev.rows_returned}")
    if ev.url_after_click:
        parts.append(f"url→ {ev.url_after_click}")
    if ev.stack_trace:
        stack = ev.stack_trace.strip().replace("\n", " ")
        parts.append(f"stack: {stack[:240]}")
    if ev.body_excerpt and not ev.stack_trace:
        parts.append(f"body: {ev.body_excerpt[:200]}")
    if ev.console:
        errs = [c.text for c in ev.console if c.level == "error"][:2]
        if errs:
            parts.append(f"console errors: {' | '.join(e[:120] for e in errs)}")
    return " · ".join(parts) or "(no evidence)"


def render_for_smith(report: FaultReport) -> str:
    """Render the report as a markdown prompt Smith consumes.

    Structure matches spec §5.5 — priority-ranked, with hypothesis +
    suggested_tools per fault so Smith heads straight to the right seam.
    """
    lines: list[str] = []
    lines.append(
        f"# Self-Verify Report · run `{report.run_id}` · "
        f"round {report.round} · target `{report.target}`"
    )
    lines.append(
        f"- {report.interactions_run} interactions run, "
        f"{report.interactions_passed} passed, "
        f"{report.interactions_flaky} flaky, {len(report.faults)} faults"
    )
    lines.append("")
    if not report.faults:
        lines.append("**No faults found. The app looks green.**")
        return "\n".join(lines)

    lines.append(
        "The runner is authoritative — every fault below was confirmed "
        "by a real HTTP call / click. Do NOT re-verify by reading files. "
        "Prefer the suggested tool(s) per fault; escalate anything you "
        "can't classify by replying with the fault id in your summary."
    )
    lines.append("")

    for idx, f in enumerate(report.faults, start=1):
        lines.append(f"## D{idx} · `{f.signature}` · Priority: **{f.priority}**")
        lines.append(_interaction_context(f.interaction))
        lines.append(f"- Layer: `{f.layer}`")
        lines.append(f"- Evidence: {_evidence_slice(f.evidence)}")
        lines.append(f"- Hypothesis: {f.hypothesis}")
        if f.suggested_tools:
            tools = ", ".join(f"`{t}`" for t in f.suggested_tools)
            lines.append(f"- Suggested tools: {tools}")
        lines.append(f"- Fault id: `{f.id}`")
        lines.append("")

    lines.append(
        "Reply with a short Remediation summary: list which fault ids you "
        "fixed and which you couldn't. The runner will re-check the "
        "failing subset in a follow-up round."
    )
    return "\n".join(lines)
