"""Classify verify-runner evidence into a named FaultSignature — SV-2.

Pure module. Zero I/O, zero LLM. Given an `Interaction` (from
`interaction_extractor`) and the `Evidence` the Playwright runner
collected, return a `FaultClassification` that carries:

  - the canonical `FaultSignature` (an enum from spec §5.6)
  - `priority`  — BLOCKER | BROKEN | CONTENT | FLAKY
  - `layer`     — where the failure lived (http / dom / console / …)
  - `hypothesis` — one sentence describing the likely root cause
  - `suggested_tools` — ordered list of Smith tools most likely to fix

Signature detection is pattern-match, ordered specific → general so
overlapping evidence (e.g. an SSR 500 with a stack trace) resolves to the
most-informative signature. Anything the table doesn't match lands as
`UNCLASSIFIED` — Smith gets the full evidence to reason about.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from services.interaction_extractor import (
    ButtonInteraction,
    DetailInteraction,
    FormInteraction,
    Interaction,
    ListInteraction,
    RouteInteraction,
)


# ── Signature enum (str for cheap serialization + set-lookup) ────────────


class FaultSignature(str):
    """Canonical fault labels. Strings so they JSON-serialize cleanly."""

    # SSR / build faults on route load
    SSR_500_ENOENT_JSON = "SSR_500_ENOENT_JSON"
    SSR_500_UNKNOWN_TABLE = "SSR_500_UNKNOWN_TABLE"
    SSR_500_MODULE_NOT_FOUND = "SSR_500_MODULE_NOT_FOUND"
    SSR_500_GENERIC = "SSR_500_GENERIC"
    ROUTE_404_MISSING_SCHEMA = "ROUTE_404_MISSING_SCHEMA"
    ROUTE_401_UNEXPECTED = "ROUTE_401_UNEXPECTED"

    # Button interactions
    BUTTON_NO_ACTION_DECLARED = "BUTTON_NO_ACTION_DECLARED"
    BUTTON_WORKFLOW_MISSING = "BUTTON_WORKFLOW_MISSING"
    BUTTON_NAV_TARGET_MISSING = "BUTTON_NAV_TARGET_MISSING"
    BUTTON_COMPUTE_WRONG_VALUE = "BUTTON_COMPUTE_WRONG_VALUE"

    # Form interactions
    FORM_SUBMIT_400 = "FORM_SUBMIT_400"
    FORM_SUBMIT_500_FK = "FORM_SUBMIT_500_FK"
    FORM_SUBMIT_500_GENERIC = "FORM_SUBMIT_500_GENERIC"
    FORM_NO_SUBMIT_ACTION = "FORM_NO_SUBMIT_ACTION"

    # List / content
    LIST_EMPTY = "LIST_EMPTY"
    LIST_DATASOURCE_UNRESOLVED = "LIST_DATASOURCE_UNRESOLVED"
    DASHBOARD_BLANK = "DASHBOARD_BLANK"
    DETAIL_BINDING_UNRESOLVED = "DETAIL_BINDING_UNRESOLVED"

    # Runtime console
    CONSOLE_REACT_31 = "CONSOLE_REACT_31"
    CONSOLE_HYDRATION_MISMATCH = "CONSOLE_HYDRATION_MISMATCH"

    # Runner / infra
    TIMEOUT = "TIMEOUT"
    UNCLASSIFIED = "UNCLASSIFIED"

    # SV-STRICT-4: promise-vs-delivery — a persona stated a job in the
    # product brief but no reachable component fulfills it. Detected
    # deterministically at gen time by services.promise_gate.
    PROMISE_NOT_DELIVERED = "PROMISE_NOT_DELIVERED"


Priority = Literal["BLOCKER", "BROKEN", "CONTENT", "FLAKY"]
Layer = Literal["http", "dom", "console", "network", "timeout", "value"]


# ── Evidence + classification dataclasses ────────────────────────────────


@dataclass(frozen=True)
class NetworkEntry:
    method: str
    url: str
    status: int


@dataclass(frozen=True)
class LogEntry:
    level: str  # 'error' | 'warning' | 'info' | 'log'
    text: str


@dataclass
class Evidence:
    """Everything the runner observed for one interaction.

    All fields optional so the runner can populate whatever it captured;
    the classifier tolerates absence.
    """

    status: int | None = None                    # HTTP status on page load OR primary action
    body_excerpt: str | None = None              # first 2KB of response body (redacted)
    console: list[LogEntry] = field(default_factory=list)
    network_log: list[NetworkEntry] = field(default_factory=list)
    dom_snapshot: str | None = None              # outerHTML of interaction target
    stack_trace: str | None = None               # server-side stack (from body / next.js)
    screenshot_uri: str | None = None
    # Interaction-shape observations the classifier uses:
    url_after_click: str | None = None           # for navigate assertions
    computed_value_actual: Any = None            # for compute button assertions
    computed_value_expected: Any = None
    rows_returned: int | None = None             # for list assertions
    timed_out: bool = False                      # runner gave up
    rendered_widget_count: int | None = None     # for dashboard assertions


@dataclass(frozen=True)
class FaultClassification:
    signature: str
    priority: Priority
    layer: Layer
    hypothesis: str
    suggested_tools: tuple[str, ...]
    # SV-STRICT-2a: which W-slot of the component's contract this fault
    # falsifies (what/who/where/when/how/why). Intrinsic to the signature,
    # so downstream (narrator, log) can group without re-deriving.
    w_slot: str = "what"


# ── Signature → W-slot ───────────────────────────────────────────────────
#
# Which promise does this fault falsify?
#   what   — the component didn't render / didn't deliver its output
#   who    — access-control failure (right/wrong actor)
#   where  — the thing isn't at the promised route / target
#   when   — the trigger didn't fire (dead click, silent submit)
#   how    — the mechanism failed (workflow crashed, submit 500'd)
#   why    — the user job wasn't served (Slice 4 fills)
#
# Anything unclassified defaults to `what` — we know a promise was broken,
# we just don't yet know which slot to point to.

_SIG_TO_W_SLOT: dict[str, str] = {
    FaultSignature.SSR_500_ENOENT_JSON: "what",
    FaultSignature.SSR_500_UNKNOWN_TABLE: "what",
    FaultSignature.SSR_500_MODULE_NOT_FOUND: "what",
    FaultSignature.SSR_500_GENERIC: "what",
    FaultSignature.ROUTE_404_MISSING_SCHEMA: "where",
    FaultSignature.ROUTE_401_UNEXPECTED: "who",

    FaultSignature.BUTTON_NO_ACTION_DECLARED: "when",
    FaultSignature.BUTTON_WORKFLOW_MISSING: "how",
    FaultSignature.BUTTON_NAV_TARGET_MISSING: "where",
    FaultSignature.BUTTON_COMPUTE_WRONG_VALUE: "how",

    FaultSignature.FORM_SUBMIT_400: "how",
    FaultSignature.FORM_SUBMIT_500_FK: "how",
    FaultSignature.FORM_SUBMIT_500_GENERIC: "how",
    FaultSignature.FORM_NO_SUBMIT_ACTION: "when",

    FaultSignature.LIST_EMPTY: "what",
    FaultSignature.LIST_DATASOURCE_UNRESOLVED: "how",
    FaultSignature.DASHBOARD_BLANK: "what",
    FaultSignature.DETAIL_BINDING_UNRESOLVED: "how",

    FaultSignature.CONSOLE_REACT_31: "how",
    FaultSignature.CONSOLE_HYDRATION_MISMATCH: "how",

    FaultSignature.TIMEOUT: "when",
    FaultSignature.UNCLASSIFIED: "what",

    # SV-STRICT-4
    FaultSignature.PROMISE_NOT_DELIVERED: "why",
}


def w_slot_for_signature(signature: str) -> str:
    """Return the W-slot a signature falsifies.

    Unknown signatures fall back to `what` — every fault falsifies at
    least some promise; when we can't be more specific, this is the
    safe default.
    """
    return _SIG_TO_W_SLOT.get(signature, "what")


# ── Signature → metadata lookup ──────────────────────────────────────────
#
# One row per signature. When the classifier picks a signature, it also
# emits this metadata verbatim into the FaultClassification. Keep in sync
# with the spec's §5.6 signatures catalog.

_META: dict[str, tuple[Priority, Layer, str, tuple[str, ...]]] = {
    FaultSignature.SSR_500_ENOENT_JSON: (
        "BLOCKER", "http",
        "A Server Component reads a JSON contract via fs.readFile but the file "
        "wasn't shipped in the Vercel bundle. Ship it via next.config "
        "outputFileTracingIncludes OR vercel.json functions.includeFiles.",
        ("apply_post_generate_fixes", "next_config_guard"),
    ),
    FaultSignature.SSR_500_UNKNOWN_TABLE: (
        "BLOCKER", "http",
        "The generated app queries a Postgres table that doesn't exist. Likely "
        "a name-drift between schema (camelCase) and workflow/API (snake_case), "
        "or a migration that didn't run.",
        ("workflow_table_guard", "schema_references", "apply_post_generate_fixes"),
    ),
    FaultSignature.SSR_500_MODULE_NOT_FOUND: (
        "BLOCKER", "http",
        "A JS import can't be resolved at runtime. Usually a missing "
        "transpilePackages entry or a hallucinated import.",
        ("next_config_guard", "edit_page"),
    ),
    FaultSignature.SSR_500_GENERIC: (
        "BLOCKER", "http",
        "Server render threw an uncaught error. See stack trace for the "
        "throw site — needs Smith to read the file and diagnose.",
        ("edit_page",),
    ),
    FaultSignature.ROUTE_404_MISSING_SCHEMA: (
        "BLOCKER", "http",
        "The route is listed in nav-flow but its schema file (and/or Next "
        "page.tsx) is missing. Recreate via add_page or check ensure_create/"
        "edit_routes.",
        ("add_page", "ensure_create_edit_routes"),
    ),
    FaultSignature.ROUTE_401_UNEXPECTED: (
        "BLOCKER", "http",
        "Route returns 401 despite runner logging in. Auth wiring broken — "
        "session cookie not propagating, OR middleware misconfigured.",
        ("edit_page", "apply_post_generate_fixes"),
    ),

    FaultSignature.BUTTON_NO_ACTION_DECLARED: (
        "BROKEN", "dom",
        "Button has no onClick / navigate / workflow / submit prop. A button "
        "without an action is broken by definition.",
        ("edit_page", "wire_form_to_workflow"),
    ),
    FaultSignature.BUTTON_WORKFLOW_MISSING: (
        "BROKEN", "network",
        "Button declares a workflow target but no POST /api/workflows/*/start "
        "fired on click. The workflow name likely doesn't match any registered "
        "workflow, OR the dispatch handler isn't wired.",
        ("wire_form_to_workflow", "add_workflow", "check_data_source"),
    ),
    FaultSignature.BUTTON_NAV_TARGET_MISSING: (
        "BROKEN", "http",
        "Button navigated to a route that 404s. The target route is missing "
        "from nav-flow / doesn't have a schema.",
        ("navigate_target_guard", "add_page"),
    ),
    FaultSignature.BUTTON_COMPUTE_WRONG_VALUE: (
        "BROKEN", "value",
        "Compute button ran but the resulting field value doesn't match the "
        "formula. Formula bug OR wrong target field.",
        ("edit_page",),
    ),

    FaultSignature.FORM_SUBMIT_400: (
        "BROKEN", "http",
        "Form POST returned 400. Likely input-shape mismatch: form fields "
        "don't line up with workflow.trigger_inputs or entity columns.",
        ("wire_form_to_workflow", "check_data_source", "edit_page"),
    ),
    FaultSignature.FORM_SUBMIT_500_FK: (
        "BROKEN", "http",
        "Form POST failed with a foreign-key constraint. Either the seed data "
        "for the referenced entity is empty, or the FK field wasn't filled.",
        ("check_data_source", "apply_post_generate_fixes"),
    ),
    FaultSignature.FORM_SUBMIT_500_GENERIC: (
        "BROKEN", "http",
        "Form POST returned a 500 without a clear signature. Needs Smith to "
        "read the route file + form schema.",
        ("edit_page",),
    ),
    FaultSignature.FORM_NO_SUBMIT_ACTION: (
        "BROKEN", "dom",
        "Form has no submit target (workflow or dataSource). Won't do "
        "anything on submit.",
        ("wire_form_to_workflow", "form_target_guard"),
    ),

    FaultSignature.LIST_EMPTY: (
        "CONTENT", "http",
        "Table's API returned 0 rows. Seed data missing for this entity — "
        "SEED-1 should have guaranteed ≥1 row.",
        ("check_data_source", "apply_post_generate_fixes"),
    ),
    FaultSignature.LIST_DATASOURCE_UNRESOLVED: (
        "CONTENT", "http",
        "GET /api/data/<slug> returned 404 — the dataSource name in the "
        "schema doesn't match any registered resource. Likely rename drift.",
        ("check_data_source", "schema_references"),
    ),
    FaultSignature.DASHBOARD_BLANK: (
        "CONTENT", "dom",
        "Dashboard route rendered fewer than 3 widgets — planner likely "
        "under-authored the schema.",
        ("dashboard_completeness_guard", "edit_page"),
    ),
    FaultSignature.DETAIL_BINDING_UNRESOLVED: (
        "CONTENT", "dom",
        "Detail page shows raw {{binding}} text — a template expression that "
        "didn't resolve. Field name or binding-path bug.",
        ("edit_page", "check_data_source"),
    ),

    FaultSignature.CONSOLE_REACT_31: (
        "BROKEN", "console",
        "React error #31 (object rendered as child) — a binding produced an "
        "object where a string was expected.",
        ("edit_page",),
    ),
    FaultSignature.CONSOLE_HYDRATION_MISMATCH: (
        "BROKEN", "console",
        "Server-rendered HTML disagreed with client hydration. Usually a "
        "Date.now() / random used in SSR.",
        ("edit_page",),
    ),

    FaultSignature.TIMEOUT: (
        "FLAKY", "timeout",
        "Runner timed out. Either the app is slow, or the page never "
        "responded. Not necessarily an app bug.",
        (),  # no auto-fix; escalate to user
    ),
    FaultSignature.UNCLASSIFIED: (
        "BROKEN", "http",
        "Fault did not match any known signature. Full evidence passed to "
        "Smith for open-ended diagnosis.",
        ("edit_page",),
    ),

    # SV-STRICT-4 — deterministic promise gate. A persona stated a job in
    # the product brief but no reachable component fulfills it. Detected
    # at gen time by services.promise_gate — no runner needed.
    FaultSignature.PROMISE_NOT_DELIVERED: (
        "BROKEN", "value",
        "A persona job declared in the product brief has no reachable "
        "component that fulfills it. The plan promised something the app "
        "does not deliver — add a page/workflow that serves this job.",
        ("add_page", "add_workflow"),
    ),
}


# ── Regex signatures for stack trace / body detection ────────────────────

_RE_ENOENT_JSON = re.compile(r"ENOENT[^\n]*\.json\b", re.IGNORECASE)
_RE_UNKNOWN_TABLE = re.compile(
    r"(unknown table|relation \"[^\"]+\" does not exist|does not exist.*relation)",
    re.IGNORECASE,
)
_RE_MODULE_NOT_FOUND = re.compile(
    r"(Module not found|Cannot find module|Can't resolve)",
    re.IGNORECASE,
)
_RE_FK_VIOLATION = re.compile(
    r"(foreign key constraint|violates.*foreign key|referenced.*does not exist)",
    re.IGNORECASE,
)
_RE_REACT_31 = re.compile(r"(Minified React error #31|React error.*31\b)", re.IGNORECASE)
_RE_HYDRATION = re.compile(
    r"(hydration|hydrat.*mismatch|did not match|Text content does not match)",
    re.IGNORECASE,
)
_RE_UNRESOLVED_BINDING = re.compile(r"\{\{[A-Za-z_][A-Za-z0-9_.\[\]]*\}\}")


# ── Public classifier ────────────────────────────────────────────────────


def classify(interaction: Interaction, evidence: Evidence) -> FaultClassification:
    """Ordered-match classifier. First match wins.

    Ordering: infra (timeout) → HTTP-status-shape (500/404/401) →
    per-interaction-kind (button/form/list/detail) → console →
    UNCLASSIFIED fallback.
    """
    # 1. Runner-infra faults come first — nothing else matters if the
    #    runner didn't get to observe the app.
    if evidence.timed_out:
        return _make(FaultSignature.TIMEOUT)

    # 2. HTTP-status-shape faults (most specific: match on stack trace first)
    if evidence.status == 500:
        sig = _classify_500(evidence)
        # For a Form, a 500 on the POST is a submit fault, not an SSR fault
        if isinstance(interaction, FormInteraction) and _has_post_5xx(evidence):
            if sig == FaultSignature.SSR_500_UNKNOWN_TABLE:
                # unknown table on a form POST → FK/schema, not SSR
                return _make(FaultSignature.FORM_SUBMIT_500_GENERIC)
            if _stack_matches(evidence, _RE_FK_VIOLATION):
                return _make(FaultSignature.FORM_SUBMIT_500_FK)
            return _make(FaultSignature.FORM_SUBMIT_500_GENERIC)
        return _make(sig)

    if evidence.status == 404:
        if isinstance(interaction, RouteInteraction):
            return _make(FaultSignature.ROUTE_404_MISSING_SCHEMA)
        if isinstance(interaction, ListInteraction):
            return _make(FaultSignature.LIST_DATASOURCE_UNRESOLVED)
        if isinstance(interaction, ButtonInteraction) \
                and interaction.action.kind == "navigate":
            return _make(FaultSignature.BUTTON_NAV_TARGET_MISSING)

    if evidence.status == 401 and isinstance(interaction, RouteInteraction) \
            and not interaction.requires_auth:
        return _make(FaultSignature.ROUTE_401_UNEXPECTED)

    if evidence.status == 400 and isinstance(interaction, FormInteraction) \
            and _has_post_4xx(evidence):
        return _make(FaultSignature.FORM_SUBMIT_400)

    # 3. Per-interaction-kind static faults (no HTTP involvement)
    if isinstance(interaction, ButtonInteraction):
        if interaction.action.kind == "none":
            return _make(FaultSignature.BUTTON_NO_ACTION_DECLARED)
        if interaction.action.kind == "workflow" \
                and not _has_workflow_post(evidence):
            return _make(FaultSignature.BUTTON_WORKFLOW_MISSING)
        if interaction.action.kind == "compute" \
                and evidence.computed_value_actual is not None \
                and evidence.computed_value_actual != evidence.computed_value_expected:
            return _make(FaultSignature.BUTTON_COMPUTE_WRONG_VALUE)

    if isinstance(interaction, FormInteraction) \
            and interaction.submit.kind == "none":
        return _make(FaultSignature.FORM_NO_SUBMIT_ACTION)

    if isinstance(interaction, ListInteraction) \
            and evidence.rows_returned == 0:
        return _make(FaultSignature.LIST_EMPTY)

    if isinstance(interaction, DetailInteraction) \
            and evidence.dom_snapshot \
            and _RE_UNRESOLVED_BINDING.search(evidence.dom_snapshot):
        return _make(FaultSignature.DETAIL_BINDING_UNRESOLVED)

    # 4. Console-only faults (page loaded but broke in the browser)
    if _console_matches(evidence, _RE_REACT_31):
        return _make(FaultSignature.CONSOLE_REACT_31)
    if _console_matches(evidence, _RE_HYDRATION):
        return _make(FaultSignature.CONSOLE_HYDRATION_MISMATCH)

    # 5. Dashboard-blank — route interactions where we counted widgets
    if isinstance(interaction, RouteInteraction) \
            and evidence.rendered_widget_count is not None \
            and evidence.rendered_widget_count < 3 \
            and _is_dashboard_route(interaction.route):
        return _make(FaultSignature.DASHBOARD_BLANK)

    # 6. Fallback
    return _make(FaultSignature.UNCLASSIFIED)


# ── Helpers ──────────────────────────────────────────────────────────────


def _make(signature: str) -> FaultClassification:
    priority, layer, hypothesis, tools = _META[signature]
    return FaultClassification(
        signature=signature,
        priority=priority,
        layer=layer,
        hypothesis=hypothesis,
        suggested_tools=tools,
        w_slot=w_slot_for_signature(signature),
    )


def _classify_500(evidence: Evidence) -> str:
    """Route a 500 into a specific signature based on stack/body content."""
    text = (evidence.stack_trace or "") + "\n" + (evidence.body_excerpt or "")
    if _RE_ENOENT_JSON.search(text):
        return FaultSignature.SSR_500_ENOENT_JSON
    if _RE_UNKNOWN_TABLE.search(text):
        return FaultSignature.SSR_500_UNKNOWN_TABLE
    if _RE_MODULE_NOT_FOUND.search(text):
        return FaultSignature.SSR_500_MODULE_NOT_FOUND
    return FaultSignature.SSR_500_GENERIC


def _stack_matches(evidence: Evidence, pattern: re.Pattern) -> bool:
    text = (evidence.stack_trace or "") + "\n" + (evidence.body_excerpt or "")
    return bool(pattern.search(text))


def _console_matches(evidence: Evidence, pattern: re.Pattern) -> bool:
    for entry in evidence.console or []:
        if pattern.search(entry.text or ""):
            return True
    return False


def _has_workflow_post(evidence: Evidence) -> bool:
    for req in evidence.network_log or []:
        if req.method == "POST" and "/api/workflows/" in req.url:
            return True
    return False


def _has_post_4xx(evidence: Evidence) -> bool:
    return any(
        r.method == "POST" and 400 <= r.status < 500
        for r in evidence.network_log or []
    )


def _has_post_5xx(evidence: Evidence) -> bool:
    return any(
        r.method == "POST" and 500 <= r.status < 600
        for r in evidence.network_log or []
    )


def _is_dashboard_route(route: str) -> bool:
    """Heuristic: routes containing 'dashboard' or 'home' or '/' root."""
    r = (route or "").lower()
    return r in {"/", "/home", "/dashboard"} or "dashboard" in r
