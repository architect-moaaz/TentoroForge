# backend/services/app_design_catalog.py
"""Capability catalog — the single source of truth for what the generator can
render (page archetypes) and back (domain features). The planner is steered
toward this catalog; the guardrail validates choices against it.
"""
from __future__ import annotations

# Page archetypes. `components` MUST be drawn from already-registered schema
# nodes (no new UI). `template_key` matches a key in page_type_templates._TEMPLATES.
ARCHETYPES: dict[str, dict] = {
    # The 6 legacy types remain renderable (templates already exist).
    "list":      {"components": ["DataGrid","FilterBar","Heading","Row","Stack","Button"], "template_key": "list",      "renderable": True, "description": "Browse/filter many records", "fits": "any entity collection"},
    "detail":    {"components": ["Heading","KeyValueList","Card","Tabs","Button","Row","Stack"], "template_key": "detail", "renderable": True, "description": "One record's full view", "fits": "single entity"},
    "form":      {"components": ["Form","Card","Row","Stack","Heading","Button"], "template_key": "form",         "renderable": True, "description": "Create/edit a record", "fits": "new/edit"},
    "dashboard": {"components": ["MetricTile","Grid","Chart","Card","Stack","Heading"], "template_key": "dashboard", "renderable": True, "description": "KPIs + overview", "fits": "home/overview"},
    # New archetypes (templates added in Task 4).
    "kanban":    {"components": ["Kanban","FilterBar","Heading","Row","Stack"], "template_key": "kanban",        "renderable": True, "description": "Board of cards grouped by status", "fits": "tasks/tickets/pipeline stages"},
    "calendar":  {"components": ["Calendar","Heading","Row","Stack"], "template_key": "calendar",                "renderable": True, "description": "Month/week event grid (single-day events on a date)", "fits": "appointments/events on a date"},
    "resource-schedule": {"components": ["ResourceTimeline","MetricTile","FilterBar","Heading","Row","Stack"], "template_key": "calendar", "renderable": True, "description": "Resource-scheduler / Gantt grid: rows=resources, cols=days, bars=multi-day bookings", "fits": "hotel reservations by room / staff shifts / rentals by unit / provider schedules"},
    "inbox":     {"components": ["Split","DataGrid","InspectorPanel","Heading","Stack"], "template_key": "inbox", "renderable": True, "description": "List + reading pane", "fits": "tickets/messages/requests"},
    "report":    {"components": ["Chart","DateRangePicker","Grid","Stat","Table","Card","Heading","Row","Stack"], "template_key": "report", "renderable": True, "description": "Charts + summary analytics", "fits": "reports/analytics"},
    "wizard":    {"components": ["ApprovalStepper","Form","Row","Stack","Heading","Button"], "template_key": "wizard", "renderable": True, "description": "Multi-step guided flow", "fits": "onboarding/multi-step create"},
    "audit-log": {"components": ["Timeline","ActivityFeed","Card","Heading","Stack"], "template_key": "audit-log", "renderable": True, "description": "Chronological event history", "fits": "history/activity/audit"},
    "settings":  {"components": ["Tabs","Form","Card","Heading","Stack","Button"], "template_key": "settings",      "renderable": True, "description": "Grouped configuration", "fits": "settings/profile/account"},
    "timeline":  {"components": ["Timeline","Heading","Stack"], "template_key": "audit-log", "renderable": True, "description": "Vertical chronological view", "fits": "process/status history"},  # reuses audit-log template intentionally
    # Standalone tool / no persistence — inputs → formula → result.
    # Uses interaction.computed for reactive fields OR onClick:{kind:"compute"}
    # for imperative "= key" semantics; no entities, no CRUD, no routes.
    "computational": {"components": ["Card","Form","Input","Text","Heading","Stack","Row","Button"], "template_key": "computational", "renderable": True, "description": "Standalone input→formula→result tool", "fits": "calculators/converters/estimators/quiz-scorers (no data persistence)"},
}


# ── APP-LEVEL ARCHETYPES ────────────────────────────────────────────────────
# App-level archetypes describe the SHAPE of an entire generated app (entities,
# whether it needs an agent-graph, which default features it comes with), as
# opposed to PAGE-level archetypes above which describe one page's composition.
#
# The planner classifies the user's brief against `signals` (case-insensitive
# keyword match on the brief text) and, if a match wins, seeds the plan with
# the archetype's canonical entities + agent flag + default_features. Without
# this, the planner will hallucinate a generic CRUD for shapes it hasn't seen
# (e.g. a visual product-search app becomes an image-upload table).
#
# Each entry:
#   - label: human-readable name (for logs / UI)
#   - description: one-line explanation of what this app does
#   - signals: keyword phrases that trigger classification (all lowercase);
#              match wins when ANY signal appears in the brief AND no negative
#              signal appears (see `_NEGATIVE_SIGNALS` below).
#   - entities: canonical entity list the planner should include
#   - has_agent: true when this shape needs a runtime app-agent (agent-graph),
#                not just deterministic workflows
#   - default_features: platform features the archetype relies on
APP_ARCHETYPES: dict[str, dict] = {
    "visual-product-search": {
        "label": "Visual Product Search",
        "description": (
            "Users scan/upload a product image; app identifies it and shows "
            "prices from multiple retailers. Includes admin-controlled "
            "retailer source list."
        ),
        "signals": [
            "scan",
            "camera",
            "image search",
            "price comparison",
            "product identify",
            "reverse image",
            "product lookup",
        ],
        "entities": ["scan_events", "retail_sources", "users"],
        "has_agent": True,
        "default_features": [
            "camera_upload",
            "admin_source_control",
            "outbound_links",
        ],
    },
}


# Negative signals per archetype — brief phrases that should DISQUALIFY a match
# even if a positive signal is present. Prevents dumb classifier collisions.
# For visual-product-search: a "photo gallery" is not a scan/identify app; a
# "receipt scanner" is text-extraction, not product identification.
_NEGATIVE_SIGNALS: dict[str, list[str]] = {
    "visual-product-search": [
        "photo gallery",
        "image gallery",
        "photo album",
        # These substrings are chosen so they also match "scan a receipt",
        # "scan a document", etc — not just "receipt scanner".
        "receipt",
        "document scan",
        "document scanner",
        "id scan",
        "id scanner",
        # Barcode / QR are NOT negatives — barcode-based and QR-based product
        # ID are the same app shape as image-based product ID: scan → identify
        # → compare prices. Only exclude when the app is explicitly about
        # printing / labeling / inventory (a different domain).
        "barcode label",
        "barcode printer",
        "barcode inventory",
        "qr generator",
        "generate qr",
        # Co-occurrence negatives (tuples): every part must appear somewhere
        # in the brief. Catches "barcode scanner for inventory" where the
        # words aren't contiguous but the app is still inventory-domain.
        ("barcode", "inventory"),
        ("qr", "inventory"),
        # QR check-in / ticketing apps scan people-credentials, not products.
        ("qr", "event"),
        ("qr", "ticket"),
        ("qr", "check-in"),
        ("qr", "attendance"),
    ],
}

# Domain features → the EXISTING primitive that backs them. Features needing new
# runtime are catalogued but flagged renderable_in:"SP2" (guardrail drops them).
FEATURES: dict[str, dict] = {
    "status-pipeline": {"primitive": "workflow", "renderable_in": "SP1", "description": "status field + status-change workflow"},
    "approval":        {"primitive": "workflow", "renderable_in": "SP1", "description": "approval workflow + Approve/Reject"},
    "notify":          {"primitive": "workflow", "renderable_in": "SP1", "description": "send-notification action on change"},
    "scheduled":       {"primitive": "timer",    "renderable_in": "SP1", "description": "timer/delay node"},
    "decision":        {"primitive": "decision", "renderable_in": "SP1", "description": "decision table"},
    # SP2 — need new engine wiring; not rendered in SP1.
    "sla-escalation":  {"primitive": "timer+route", "renderable_in": "SP2", "description": "deadline breach → escalate"},
    "auto-reorder":    {"primitive": "rule+workflow", "renderable_in": "SP2", "description": "threshold → create order"},
}


def archetype_names() -> set[str]:
    return set(ARCHETYPES)


def feature_names() -> set[str]:
    return set(FEATURES)


def is_renderable_archetype(name: str | None) -> bool:
    spec = ARCHETYPES.get(name) if name else None
    return bool(spec and spec.get("renderable"))


def is_renderable_feature(name: str | None) -> bool:
    spec = FEATURES.get(name) if name else None
    return bool(spec and spec.get("renderable_in") == "SP1")


def app_archetype_names() -> set[str]:
    """The set of registered APP-level archetypes."""
    return set(APP_ARCHETYPES)


def app_archetype_spec(name: str | None) -> dict | None:
    """Return the archetype spec dict for `name`, or None if unknown."""
    if not name:
        return None
    return APP_ARCHETYPES.get(name)


def classify_app_archetype(description: str | None) -> str | None:
    """Classify a user brief against `APP_ARCHETYPES.signals`.

    Returns the archetype key when a positive signal appears in the brief AND
    no negative signal disqualifies the match. Returns None otherwise (planner
    proceeds with generic CRUD shape).

    Match is case-insensitive substring. This is intentionally a cheap
    keyword classifier — it runs BEFORE any LLM call. Precision comes from
    the negative-signal list (`_NEGATIVE_SIGNALS`): if the brief mentions
    something that looks like a positive but is a different app shape
    ("photo gallery", "receipt scanner"), no match is returned.
    """
    if not isinstance(description, str) or not description.strip():
        return None
    lower = description.lower()
    for name, spec in APP_ARCHETYPES.items():
        negatives = _NEGATIVE_SIGNALS.get(name, [])
        if any(
            all(part in lower for part in neg) if isinstance(neg, tuple) else neg in lower
            for neg in negatives
        ):
            continue
        signals = spec.get("signals") or []
        if any(sig in lower for sig in signals):
            return name
    return None


def catalog_for_prompt() -> str:
    """Compact catalog text injected into the planner prompt."""
    a = "\n".join(f"  - {n}: {s['description']} (fits {s['fits']})" for n, s in ARCHETYPES.items())
    f = "\n".join(f"  - {n}: {s['description']}" for n, s in FEATURES.items() if s["renderable_in"] == "SP1")
    return f"PAGE ARCHETYPES (choose the one that fits each page):\n{a}\n\nDOMAIN FEATURES:\n{f}"
