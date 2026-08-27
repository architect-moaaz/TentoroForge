"""Spec C6 — Library manifest reader.

Exposes the full library component catalog with LLM-friendly metadata
so the planner (and any downstream page-schema author) can see EVERY
registered component with a purpose blurb — not just the 20 it defaults
to when authoring from the SQL schema alone.

Source: ``packages/registry/dist/starter.json`` (the drift-guarded
catalog). Purposes are keyed by component name in a small curated
lookup so the LLM has structured "when to use" / "when not to use"
guidance without needing a separate LLM call.

The manifest is deliberately data, not code — adding purposes for a
new component is a one-line dict edit, not a Python file per component.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Purpose catalog — LLM-facing blurbs.
# Not enumerating domains; enumerating COMPONENTS (the library IS a fixed set).
# Missing entries are fine — the manifest falls back to name-only.
# --------------------------------------------------------------------------- #

_PURPOSES: dict[str, dict[str, str]] = {
    # Data displays
    "Table": {
        "purpose": "tabular data with sortable columns",
        "when_to_use": "list of records with 3+ scalar columns, comparison across rows",
        "when_not_to_use": "cards with rich media / kanban-style status / long-form content",
    },
    "Kanban": {
        "purpose": "records grouped by workflow status in columns",
        "when_to_use": "entity has a status/stage enum + users move records through it",
        "when_not_to_use": "static list with no state transitions",
    },
    "Calendar": {
        "purpose": "date-anchored records rendered on a month/week grid",
        "when_to_use": "events, bookings, deadlines, anything with a date range",
        "when_not_to_use": "date-only sorting (a Table sorted by date is often better)",
    },
    "Heatmap": {
        "purpose": "density of a value across two dimensions (usually time × category)",
        "when_to_use": "occupancy by property, sales by day-of-week, utilization by zone",
        "when_not_to_use": "single-dimension counts (use Chart/Stat instead)",
    },
    "Chart": {
        "purpose": "quantitative series (line/bar/pie/area/donut/funnel)",
        "when_to_use": "trend over time, category comparison, part-of-whole",
        "when_not_to_use": "single-number summary (use Stat)",
    },
    "Stat": {
        "purpose": "a single KPI number with label + optional delta",
        "when_to_use": "dashboard tiles: count, sum, ratio, avg, min, max",
        "when_not_to_use": "multi-column data (use Table)",
    },
    "Gauge": {
        "purpose": "single value inside a bounded range (progress toward goal)",
        "when_to_use": "occupancy %, quota progress, disk usage, health score",
        "when_not_to_use": "unbounded metric (use Stat) or trend (use Chart)",
    },
    "Timeline": {
        "purpose": "chronological sequence of events",
        "when_to_use": "audit log, activity feed, order status history",
        "when_not_to_use": "concurrent items in a date range (use Calendar)",
    },
    "ResourceTimeline": {
        "purpose": "rooms/resources × days grid with positioned bars",
        "when_to_use": "hotel booking, conference room reservation, equipment scheduling",
        "when_not_to_use": "single-resource date-ranges (use Calendar)",
    },
    "DataGrid": {
        "purpose": "editable-cell table with inline validation",
        "when_to_use": "bulk edit workflow, spreadsheet-style data entry",
        "when_not_to_use": "read-only display (use Table)",
    },
    "Tree": {
        "purpose": "hierarchical nested items with expand/collapse",
        "when_to_use": "categories with subcategories, org charts, file trees",
        "when_not_to_use": "flat lists (use List / Table)",
    },
    "List": {
        "purpose": "vertical stack of items with title + optional meta",
        "when_to_use": "notifications, activity, simple record lists (1-2 columns of info)",
        "when_not_to_use": "3+ scalar columns (Table) or status-grouped (Kanban)",
    },
    "DescriptionList": {
        "purpose": "label-value pairs (definition list)",
        "when_to_use": "detail views, side panels, key facts about a record",
        "when_not_to_use": "multi-record data (use Table)",
    },
    "ActivityFeed": {
        "purpose": "human-readable stream of what changed + when + who",
        "when_to_use": "audit trail visible to end users, comments, project history",
        "when_not_to_use": "structured audit log for admins (use Table)",
    },
    "Kanban": {
        "purpose": "records grouped by workflow status in columns",
        "when_to_use": "entity has a status/stage enum + users move records through it",
        "when_not_to_use": "static list with no state transitions",
    },
    "Schematic": {
        "purpose": "SVG floor/route map with clickable regions",
        "when_to_use": "restaurant floor plan, warehouse zones, seat picker",
        "when_not_to_use": "abstract data (use Chart/Heatmap)",
    },
    # Inputs (planner rarely picks these directly — form_scaffold does)
    "Combobox": {
        "purpose": "typeahead-filterable single-select",
        "when_to_use": "FK dropdown with >20 options",
        "when_not_to_use": "small enum with ≤5 options (use SegmentedControl or Select)",
    },
    "SegmentedControl": {
        "purpose": "2-5 mutually exclusive choices as adjacent chips",
        "when_to_use": "priority (low/medium/high), status filter, mode toggle",
        "when_not_to_use": "many options (use Select)",
    },
    # Feedback / structure
    "EmptyState": {
        "purpose": "explanation + CTA when a list has no items",
        "when_to_use": "any list bound to a dataSource",
        "when_not_to_use": "detail views (data always exists there)",
    },
    "EmptyStateRich": {
        "purpose": "empty state with illustration + primary + secondary CTA",
        "when_to_use": "first-run experiences, prominent onboarding moments",
        "when_not_to_use": "inline empty lists inside dense pages",
    },
    "Alert": {
        "purpose": "in-page banner explaining a persistent condition",
        "when_to_use": "unpaid invoice reminder, verification required, deprecation notice",
        "when_not_to_use": "transient success/error confirmation (use toast)",
    },
    "Banner": {
        "purpose": "top-of-page announcement bar",
        "when_to_use": "maintenance window, product release, org-wide notice",
        "when_not_to_use": "record-scoped condition (use Alert)",
    },
    "ApprovalStepper": {
        "purpose": "linear approval chain with current-step highlight",
        "when_to_use": "multi-approver workflow status visualisation",
        "when_not_to_use": "parallel approvals (use a status Table)",
    },
    "Stepper": {
        "purpose": "generic multi-step progress indicator",
        "when_to_use": "onboarding wizard, checkout, multi-page form",
        "when_not_to_use": "approval chain (use ApprovalStepper)",
    },
    "ValidationChecklist": {
        "purpose": "list of pass/fail rules with real-time status",
        "when_to_use": "compliance check, upload validator, form pre-flight",
        "when_not_to_use": "generic todo (use List)",
    },
    "Carousel": {
        "purpose": "horizontal-scrolling gallery of same-shape items",
        "when_to_use": "product images, featured content, testimonials",
        "when_not_to_use": "primary navigation or dense data",
    },
    "Lightbox": {
        "purpose": "modal image viewer with keyboard nav",
        "when_to_use": "click-to-zoom photo grids",
        "when_not_to_use": "non-image content",
    },
}


# --------------------------------------------------------------------------- #
# Loader
# --------------------------------------------------------------------------- #

def _default_starter_path() -> Path:
    """Path to the shipped starter.json (drift-guarded, always in-repo)."""
    # backend/services/library_manifest.py → repo/backend → repo → repo/packages
    here = Path(__file__).resolve()
    return here.parents[2] / "packages" / "registry" / "dist" / "starter.json"


def load_component_catalog(path: Path | str | None = None) -> dict[str, dict]:
    """Return the raw ``{name: {props: {...}}}`` catalog from starter.json.

    Never raises: missing/corrupt file → empty dict. Callers that
    depend on the catalog to make decisions should treat "empty" as
    "no library available" and stay safe.
    """
    p = Path(path) if path else _default_starter_path()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except FileNotFoundError:
        log.warning("[library-manifest] starter.json missing at %s", p)
    except Exception as exc:  # noqa: BLE001
        log.warning("[library-manifest] parse failed for %s: %s", p, exc)
    return {}


def enrich_with_purposes(
    catalog: dict[str, dict],
    purposes: dict[str, dict[str, str]] | None = None,
) -> list[dict]:
    """Combine the raw catalog with the purposes lookup into a list of
    ``{name, props: [str], purpose, when_to_use, when_not_to_use}`` dicts.

    Components without an entry in the purposes dict get name-only
    metadata (empty purpose/when strings) so the LLM at least sees the
    component exists.
    """
    lookup = purposes if purposes is not None else _PURPOSES
    out: list[dict] = []
    for name, entry in sorted(catalog.items()):
        props = entry.get("props") if isinstance(entry, dict) else None
        prop_names = sorted(props.keys()) if isinstance(props, dict) else []
        pdata = lookup.get(name, {})
        out.append({
            "name": name,
            "props": prop_names,
            "purpose": pdata.get("purpose", ""),
            "when_to_use": pdata.get("when_to_use", ""),
            "when_not_to_use": pdata.get("when_not_to_use", ""),
        })
    return out


def render_catalog_for_prompt(
    entries: list[dict],
    max_chars: int = 8000,
    include_props: bool = False,
) -> str:
    """Render a compact human-readable catalog for LLM prompts.

    Line format: ``- ComponentName — purpose. USE: ... . NOT: ...``
    Truncates at ``max_chars`` (rare — 110 components × ~100 chars fits in <15KB).
    """
    lines: list[str] = []
    for e in entries:
        parts = [f"- {e['name']}"]
        if e["purpose"]:
            parts.append(f"— {e['purpose']}")
        if e["when_to_use"]:
            parts.append(f"USE: {e['when_to_use']}")
        if e["when_not_to_use"]:
            parts.append(f"NOT: {e['when_not_to_use']}")
        if include_props and e["props"]:
            parts.append(f"PROPS: {', '.join(e['props'])}")
        lines.append(" ".join(parts))
    text = "\n".join(lines)
    if len(text) > max_chars:
        # Prefer truncating uninformative entries first (those without purposes).
        with_purpose = [l for l, e in zip(lines, entries) if e["purpose"]]
        text = "\n".join(with_purpose)[:max_chars]
    return text


# --------------------------------------------------------------------------- #
# Diversity metric — observability for "planner reaches for 20 comps"
# --------------------------------------------------------------------------- #

def component_types_in_schema(node) -> set[str]:
    """Walk any page-schema tree and return every ``node.type`` string."""
    out: set[str] = set()
    def _walk(n):
        if isinstance(n, dict):
            t = n.get("type")
            if isinstance(t, str):
                out.add(t)
            for v in n.values():
                _walk(v)
        elif isinstance(n, list):
            for x in n:
                _walk(x)
    _walk(node)
    return out


def diversity_metric(
    schemas: list[dict],
    catalog: dict[str, dict],
) -> dict:
    """Return ``{used, total, ratio, unused_sample}`` for a set of page schemas.

    Higher ratio = broader use of the library. Watch for regressions:
    if a planner change drops ratio significantly, the prompt got weaker.
    """
    used: set[str] = set()
    for s in schemas:
        used |= component_types_in_schema(s)
    catalog_names = set(catalog.keys())
    used_in_catalog = used & catalog_names
    total = len(catalog_names)
    ratio = round(len(used_in_catalog) / total, 3) if total else 0.0
    unused = sorted(catalog_names - used_in_catalog)
    return {
        "used": sorted(used_in_catalog),
        "used_count": len(used_in_catalog),
        "total": total,
        "ratio": ratio,
        "unused_sample": unused[:20],
    }


__all__ = [
    "component_types_in_schema", "diversity_metric",
    "enrich_with_purposes", "load_component_catalog",
    "render_catalog_for_prompt",
    # CREATIVE-5a — compact per-component manifest
    "build_library_manifest", "load_library_manifest", "persist_library_manifest",
    # CREATIVE-5b — token-lean projection for the vocab composer
    "compact_manifest_for_composer",
]


# --------------------------------------------------------------------------- #
# CREATIVE-5a — compact per-component manifest
# --------------------------------------------------------------------------- #
#
# `enrich_with_purposes` above produces human-readable BLURBS for prompt
# injection.  This section produces a *machine-shaped* manifest for
# downstream composers: exact category, data shape, slot hints, top props.
# The two coexist because they serve different callers (prompt vs.
# programmatic pick-a-component).
#
# All derivation is table-driven — see `_CATEGORY_RULES` — so extending
# the taxonomy is a data edit, not a code edit.
# --------------------------------------------------------------------------- #

from datetime import datetime, timezone

_MANIFEST_VERSION = "1"

# Categories the manifest exposes (CREATIVE-5a taxonomy). Composers rely
# on this fixed vocabulary; if new members appear extend the rules table.
_VALID_CATEGORIES = {
    "input", "display", "layout", "overlay",
    "data", "chart", "media", "action", "nav",
}

# Rules table — order matters: the FIRST matching row wins.
# Each row is (component_name, category, data_shape, slot_hints).
# Same category can repeat freely — the mapping is per-name.
_CATEGORY_RULES: list[tuple[str, str, str, tuple[str, ...]]] = [
    # Inputs — scalar values, live in forms
    ("Input", "input", "scalar", ("form-field",)),
    ("Textarea", "input", "scalar", ("form-field",)),
    ("Select", "input", "scalar", ("form-field",)),
    ("MultiSelect", "input", "scalar", ("form-field",)),
    ("Combobox", "input", "scalar", ("form-field",)),
    ("NumberInput", "input", "scalar", ("form-field",)),
    ("DatePicker", "input", "scalar", ("form-field",)),
    ("DateRangePicker", "input", "scalar", ("form-field",)),
    ("TimePicker", "input", "scalar", ("form-field",)),
    ("Switch", "input", "scalar", ("form-field",)),
    ("Checkbox", "input", "scalar", ("form-field",)),
    ("RadioGroup", "input", "scalar", ("form-field",)),
    ("SegmentedControl", "input", "scalar", ("form-field",)),
    ("Slider", "input", "scalar", ("form-field",)),
    ("FileUpload", "input", "scalar", ("form-field",)),
    ("SearchInput", "input", "scalar", ("form-field",)),
    ("MoneyInput", "input", "scalar", ("form-field",)),
    ("ColorPicker", "input", "scalar", ("form-field",)),
    ("InputOTP", "input", "scalar", ("form-field",)),
    ("MaskedInput", "input", "scalar", ("form-field",)),
    ("Rating", "input", "scalar", ("form-field",)),
    ("KeyValueInput", "input", "scalar", ("form-field",)),
    ("Form", "input", "none", ("form-field",)),
    # Actions
    ("Button", "action", "none", ("action",)),
    ("IconButton", "action", "none", ("action",)),
    ("AddToCart", "action", "none", ("action",)),
    # Display — headings + inline atoms
    ("Heading", "display", "scalar", ("heading",)),
    ("Text", "display", "scalar", ("body",)),
    ("Badge", "display", "scalar", ("body",)),
    ("Tag", "display", "scalar", ("body",)),
    ("Avatar", "display", "scalar", ("body",)),
    ("Icon", "display", "scalar", ("body",)),
    ("Chip", "display", "scalar", ("body",)),
    ("Divider", "display", "none", ("body",)),
    ("Link", "display", "scalar", ("body",)),
    ("Breadcrumb", "display", "none", ("chrome",)),
    ("MoneyDisplay", "display", "scalar", ("body",)),
    ("SensitiveField", "display", "scalar", ("body",)),
    ("RichTextEditor", "display", "scalar", ("body",)),
    ("Banner", "display", "scalar", ("body",)),
    ("IllustratedEmpty", "display", "scalar", ("body",)),
    ("EmptyState", "display", "scalar", ("body",)),
    ("EmptyStateRich", "display", "scalar", ("body",)),
    ("Spinner", "display", "none", ("body",)),
    ("Skeleton", "display", "none", ("body",)),
    ("LoadingState", "display", "none", ("body",)),
    ("Alert", "display", "scalar", ("body",)),
    ("ValidationChecklist", "display", "scalar", ("body",)),
    ("CodeBlock", "display", "scalar", ("body",)),
    ("KeyValueList", "display", "scalar", ("body",)),
    ("FeatureCard", "display", "scalar", ("body",)),
    ("PersonCard", "display", "scalar", ("body",)),
    ("Hero", "display", "scalar", ("heading",)),
    ("NarrativeHeadline", "display", "scalar", ("heading",)),
    # Layout — surfaces + primitives
    ("Card", "layout", "none", ("surface",)),
    ("Section", "layout", "none", ("surface",)),
    ("Stack", "layout", "none", ("surface",)),
    ("Row", "layout", "none", ("surface",)),
    ("Cluster", "layout", "none", ("surface",)),
    ("Grid", "layout", "none", ("surface",)),
    ("Split", "layout", "none", ("surface",)),
    ("SplitView", "layout", "none", ("surface",)),
    ("Sidebar", "layout", "none", ("surface",)),
    ("Container", "layout", "none", ("surface",)),
    ("Spacer", "layout", "none", ("surface",)),
    ("AppShell", "layout", "none", ("chrome",)),
    ("InspectorPanel", "layout", "none", ("surface",)),
    ("Tabs", "layout", "none", ("surface",)),
    ("TabPanel", "layout", "none", ("surface",)),
    ("TabPanelWithDeepLink", "layout", "none", ("surface",)),
    ("Accordion", "layout", "none", ("surface",)),
    ("AccordionPanel", "layout", "none", ("surface",)),
    ("OverlayCard", "layout", "none", ("surface",)),
    # Overlays — modal/floating chrome
    ("Modal", "overlay", "none", ("modal",)),
    ("Dialog", "overlay", "none", ("modal",)),
    ("ConfirmDialog", "overlay", "none", ("modal",)),
    ("Drawer", "overlay", "none", ("modal",)),
    ("Sheet", "overlay", "none", ("modal",)),
    ("Popover", "overlay", "none", ("modal",)),
    ("Tooltip", "overlay", "none", ("modal",)),
    ("HoverCard", "overlay", "none", ("modal",)),
    ("Menubar", "overlay", "none", ("modal",)),
    ("DropdownMenu", "overlay", "none", ("modal",)),
    ("ContextMenu", "overlay", "none", ("modal",)),
    ("CommandPalette", "overlay", "none", ("modal",)),
    ("TourOverlay", "overlay", "none", ("modal",)),
    # Data — multi-record collections
    ("Table", "data", "tabular", ("data-row",)),
    ("TableSortable", "data", "tabular", ("data-row",)),
    ("DataGrid", "data", "tabular", ("data-row",)),
    ("EditableLineGrid", "data", "tabular", ("data-row",)),
    ("List", "data", "list", ("data-row",)),
    ("Kanban", "data", "list", ("data-row",)),
    ("Calendar", "data", "list", ("data-row",)),
    ("Timeline", "data", "list", ("data-row",)),
    ("ResourceTimeline", "data", "tabular", ("data-row",)),
    ("SearchResults", "data", "list", ("data-row",)),
    ("DescriptionList", "data", "list", ("data-row",)),
    ("Tree", "data", "list", ("data-row",)),
    ("Transfer", "data", "list", ("data-row",)),
    ("Cascader", "data", "list", ("data-row",)),
    ("Stepper", "data", "list", ("data-row",)),
    ("ApprovalStepper", "data", "list", ("data-row",)),
    ("ActivityFeed", "data", "list", ("data-row",)),
    ("FilterBar", "data", "none", ("chrome",)),
    ("FilterBuilder", "data", "none", ("chrome",)),
    ("Pagination", "data", "none", ("chrome",)),
    ("BulkActionBar", "data", "none", ("chrome",)),
    ("SavedViewsPicker", "data", "none", ("chrome",)),
    ("Wizard", "data", "list", ("data-row",)),
    # Charts / metrics
    ("Chart", "chart", "series", ("chart",)),
    ("LineChart", "chart", "series", ("chart",)),
    ("BarChart", "chart", "series", ("chart",)),
    ("AreaChart", "chart", "series", ("chart",)),
    ("PieChart", "chart", "series", ("chart",)),
    ("DonutChart", "chart", "series", ("chart",)),
    ("FunnelChart", "chart", "series", ("chart",)),
    ("RadarChart", "chart", "series", ("chart",)),
    ("Sparkline", "chart", "series", ("chart",)),
    ("Gauge", "chart", "scalar", ("chart",)),
    ("SplitArc", "chart", "scalar", ("chart",)),
    ("Heatmap", "chart", "series", ("chart",)),
    ("Schematic", "chart", "none", ("chart",)),
    ("Stat", "chart", "scalar", ("chart",)),
    ("MetricTile", "chart", "scalar", ("chart",)),
    ("Progress", "chart", "scalar", ("chart",)),
    # Media
    ("Image", "media", "scalar", ("media",)),
    ("Lightbox", "media", "scalar", ("media",)),
    ("Carousel", "media", "scalar", ("media",)),
    ("Video", "media", "scalar", ("media",)),
    ("CameraCapture", "media", "scalar", ("media",)),
    ("Scanner", "media", "scalar", ("media",)),
    ("QRCode", "media", "scalar", ("media",)),
    # Navigation / chrome
    ("NavLink", "nav", "none", ("chrome",)),
    ("SideNav", "nav", "none", ("chrome",)),
    ("MobileNav", "nav", "none", ("chrome",)),
    ("PersonaChrome", "nav", "none", ("chrome",)),
    ("CartBadge", "nav", "none", ("chrome",)),
    ("CartPanel", "nav", "none", ("chrome",)),
    ("CartPage", "nav", "none", ("chrome",)),
    ("GlobalSearch", "nav", "none", ("chrome",)),
    ("ThemeToggle", "nav", "none", ("chrome",)),
    ("KeyboardShortcuts", "nav", "none", ("chrome",)),
    ("SkipLink", "nav", "none", ("chrome",)),
    # Behavioural primitives — technically in starter but rarely picked
    # by composers on their own. Categorise so the fallback warning
    # stays clean; they render `body`-ish.
    ("FocusTrap", "display", "none", ("body",)),
    ("FocusRing", "display", "none", ("body",)),
    ("AutoFocus", "display", "none", ("body",)),
    ("PresenceIndicator", "display", "scalar", ("body",)),
    ("OptimisticProvider", "display", "none", ("body",)),
    ("UndoManager", "display", "none", ("body",)),
    ("FadeIn", "display", "none", ("body",)),
    ("Stagger", "display", "none", ("body",)),
    ("Repeat", "display", "none", ("body",)),
    ("Conditional", "display", "none", ("body",)),
    ("DataBoundary", "display", "none", ("body",)),
    ("Slot", "display", "none", ("body",)),
    ("CustomBlock", "display", "scalar", ("body",)),
    ("Toast", "display", "scalar", ("body",)),
]

_RULES_LOOKUP: dict[str, tuple[str, str, tuple[str, ...]]] = {
    name: (cat, shape, hints) for name, cat, shape, hints in _CATEGORY_RULES
}

# Props promoted to the top of `key_props` (highest-priority first).
# Any prop actually declared on the component keeps its slot; unknown
# names are ignored. Required props always outrank this list.
_PROP_PRIORITY: tuple[str, ...] = (
    "value", "defaultValue", "checked",
    "onChange", "onClick", "onSubmit", "onSelect",
    "data", "items", "rows", "columns", "dataSource", "options",
    # `optionsFrom` stays ahead of `bind`: with the list capped at 4, a Select
    # that loses `optionsFrom` loses the only way to populate an FK dropdown,
    # whereas losing `bind` costs a prefill. Components without an options
    # source (Input, Switch, NumberInput…) are unaffected and still lead
    # with `bind`.
    "optionsFrom",
    # `bind` is the RUNTIME prop carrying a data path on input components;
    # `binding` is the editor panel's name for the same idea and no component
    # accepts it. Both are ranked so ordering is stable whichever source a
    # component's props came from — only names that actually exist on the
    # component survive into key_props.
    "bind", "binding",
    "label", "title", "placeholder", "content", "text", "message",
    "name", "type",
)

_TYPE_NORMALIZE = {
    "string": "string",
    "number": "number",
    "boolean": "boolean",
    "any": "unknown",
    "array": "array",
    "object": "object",
    "enum": "string",
    "union": "unknown",
    "lazy": "object",
}


def _default_contracts_path() -> Path:
    here = Path(__file__).resolve()
    return here.parents[2] / "packages" / "registry" / "dist" / "component-contracts.json"


def _components_dir() -> Path:
    here = Path(__file__).resolve()
    return here.parents[2] / "packages" / "library" / "src" / "components"


def _load_json(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001
        log.warning("[library-manifest] parse failed for %s: %s", path, exc)
        return {}


def _normalize_type(raw_type: object) -> str:
    if not isinstance(raw_type, str):
        return "unknown"
    return _TYPE_NORMALIZE.get(raw_type, "unknown")


def _infer_type_from_name(name: str) -> str:
    """Fallback when contracts don't cover a prop (starter.json has empty ``{}``)."""
    if name.startswith("on") and len(name) > 2 and name[2].isupper():
        return "function"
    if name in {"disabled", "loading", "checked", "required", "readOnly",
                "multiple", "collapsible", "wrap", "compact", "showSymbol"}:
        return "boolean"
    if name in {"min", "max", "step", "rows", "columns"}:
        return "number"
    if name in {"data", "items", "rows", "options", "ctas", "actions",
                "shortcuts", "steps", "fields", "views", "tabs"}:
        return "array"
    if name in {"style", "backgroundImage", "media", "illustration"}:
        return "object"
    return "string"


def _extract_summary(name: str, cache: dict[str, str]) -> str:
    """Grep the component's first ``/** ... */`` block, cap at 80 chars.

    Fallback: ``"{name} — {category} component"`` when the caller can pass
    a category, otherwise just the empty string; caller composes.
    """
    if name in cache:
        return cache[name]
    comp_dir = _components_dir() / name
    candidates = [comp_dir / f"{name}.tsx"]
    # A handful of components live under a differently-named module
    # (e.g. Money/Money.tsx exports MoneyInput + MoneyDisplay). Also try
    # the parent-folder scan for that case.
    if not candidates[0].exists():
        parent_names = {
            "MoneyInput": "Money", "MoneyDisplay": "Money",
            "SensitiveField": "Money",
            "TableSortable": "Table",
        }
        alt = parent_names.get(name)
        if alt:
            candidates.append(_components_dir() / alt / f"{alt}.tsx")
    text = ""
    for p in candidates:
        if not p.exists():
            continue
        try:
            body = p.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        # Find the first /** ... */ block.
        start = body.find("/**")
        if start < 0:
            continue
        end = body.find("*/", start + 3)
        if end < 0:
            continue
        block = body[start + 3:end]
        # Strip leading * from each line, take the first non-empty line.
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("*"):
                line = line.lstrip("* ").strip()
            if not line:
                continue
            text = line
            break
        if text:
            break
    text = text[:70].rstrip(" .,;:—-")
    cache[name] = text
    return text


def _rank_prop(name: str, is_required: bool) -> tuple[int, int, str]:
    """Lower tuples sort first."""
    if is_required:
        return (0, 0, name)
    try:
        return (1, _PROP_PRIORITY.index(name), name)
    except ValueError:
        return (2, 0, name)


def _key_props_for(
    name: str,
    starter_entry: dict,
    contract_entry: dict | None,
    limit: int = 5,
) -> list[dict]:
    """Assemble the ranked, capped key_props list for one component."""
    starter_props = starter_entry.get("props") if isinstance(starter_entry, dict) else {}
    starter_names: set[str] = set(starter_props.keys()) if isinstance(starter_props, dict) else set()
    contract_props = contract_entry if isinstance(contract_entry, dict) else {}
    # The two sources speak different vocabularies and must NOT be unioned.
    #
    # `component-contracts.json` is generated from the components' Zod props —
    # it is what the runtime actually accepts, and anything outside it is
    # stripped by the registry's strict parse.
    #
    # `starter.json` is the visual EDITOR's property-panel catalog. Its entries
    # carry editor affordances (`control: "binding"`, `group: "data"`), so it
    # advertises names like `binding` on 38 input components where the runtime
    # prop is `bind`. Unioning them taught the page composer to emit
    # `props.binding`, which Zod silently dropped — every composed edit form
    # lost its prefill and rendered blank.
    #
    # So: when a contract exists it is the sole authority. Starter names are
    # used only for the 9 layout primitives (Stack/Row/Grid/Repeat/…) that
    # have no contract entry at all.
    all_names = set(contract_props.keys()) if contract_props else starter_names
    # A few props are noise — skip them.
    noise = {"style", "className", "args", "children", "dataJourney", "aria-label"}
    ranked: list[tuple[tuple[int, int, str], dict]] = []
    for pname in all_names:
        if pname in noise:
            continue
        raw_meta = contract_props.get(pname) if isinstance(contract_props, dict) else None
        meta = raw_meta if isinstance(raw_meta, dict) else None
        # Required only when the CONTRACT declares it — starter alone
        # can't tell us. Missing contract → assume optional (safer).
        is_required = meta is not None and "optional" not in meta
        rtype = _normalize_type(meta.get("type")) if meta else _infer_type_from_name(pname)
        entry: dict = {"name": pname}
        # Omit type when it's the default ("string" or "unknown") — the
        # manifest is a budget-conscious hint layer, not a full type
        # dictionary. Composers already default to string for scalar
        # inputs; annotate only when the shape actually differs.
        if rtype not in {"unknown", "string"}:
            entry["type"] = rtype
        if is_required:
            entry["required"] = True
        ranked.append((_rank_prop(pname, is_required), entry))
    ranked.sort(key=lambda t: t[0])
    return [e for _, e in ranked[:limit]]


def _categorize(name: str, unknown_sink: list[str]) -> tuple[str, str, list[str]]:
    hit = _RULES_LOOKUP.get(name)
    if hit is not None:
        cat, shape, hints = hit
        return cat, shape, list(hints)
    unknown_sink.append(name)
    return "display", "scalar", ["body"]


def build_library_manifest(
    starter_path: Path | str | None = None,
    contracts_path: Path | str | None = None,
) -> dict:
    """Compact per-component manifest for downstream composers.

    Returns ``{"version": "1", "generated_at": iso, "components": {...}}``
    with one entry per union of starter.json + rules-table + contracts.
    Never raises — missing sources produce empty ``components``.
    """
    starter_p = Path(starter_path) if starter_path else _default_starter_path()
    contracts_p = Path(contracts_path) if contracts_path else _default_contracts_path()
    starter = _load_json(starter_p)
    contracts = _load_json(contracts_p)

    # Union of names — starter is the ship-truth; the rules table adds
    # virtual chart variants (LineChart etc.) composers pick even when
    # only `Chart` is registered. Contracts-only names (e.g. Hero variants
    # never wired into starter) are DELIBERATELY skipped: they can't
    # actually render and would waste manifest budget.
    names = set(starter.keys()) | set(_RULES_LOOKUP.keys())

    unknown: list[str] = []
    summary_cache: dict[str, str] = {}
    components: dict[str, dict] = {}
    for name in sorted(names):
        category, shape, hints = _categorize(name, unknown)
        key_props = _key_props_for(
            name,
            starter.get(name, {}),
            contracts.get(name),
            limit=4,
        )
        summary = _extract_summary(name, summary_cache)
        if not summary:
            # Fallback stays terse — the category itself carries the
            # info a "{name} — {category} component" template would add.
            summary = f"{name} ({category})"
        components[name] = {
            "category": category,
            "data_shape": shape,
            "slot_hints": hints,
            "key_props": key_props,
            "summary": summary[:70],
        }

    if unknown:
        # Log once per build so we see the tail of unrecognized names and
        # can extend the rules table. Deliberately WARN, not error — the
        # fallback still yields a usable entry.
        log.warning(
            "[library-manifest] %d unrecognized components fell back to display/scalar/body: %s",
            len(unknown), ", ".join(unknown[:20]) + (" ..." if len(unknown) > 20 else ""),
        )

    return {
        "version": _MANIFEST_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "components": components,
    }


def persist_library_manifest(output_dir: Path | str) -> Path:
    """Build and write the manifest to ``<output_dir>/contracts/library-manifest.json``.

    Overwrites any existing file. Returns the path written.
    """
    out_dir = Path(output_dir) / "contracts"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "library-manifest.json"
    manifest = build_library_manifest()
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def compact_manifest_for_composer(manifest: dict | None = None,
                                    include_examples: bool = False) -> dict:
    """Return a token-lean projection of the manifest for a composer.

    Two shapes, gated by ``include_examples``:

    - ``False`` (default, for the vocab composer): drops ``key_props`` and
      returns only {category, data_shape, slot_hints, summary}. The vocab
      composer picks NAMES only, so prop shapes would be waste.

    - ``True`` (for the page composer): additionally attaches ``key_props``
      + ``example`` (a curated correct-shape props snippet) for the
      components in :data:`services.component_examples.COMPONENT_EXAMPLES`.
      The example lets the LLM copy the shape verbatim for tricky prop
      structures (Table columns, FilterBar chips, Cascader options,
      Chart series, Conditional pairs) — preventing a whole class of
      "composer emitted a broken widget" bugs.
    """
    src = manifest if isinstance(manifest, dict) else build_library_manifest()
    src_comps = src.get("components") if isinstance(src, dict) else None
    if not isinstance(src_comps, dict):
        return {"components": {}}
    examples: dict = {}
    if include_examples:
        try:
            from services.component_examples import COMPONENT_EXAMPLES
            examples = COMPONENT_EXAMPLES
        except Exception:  # noqa: BLE001 — examples are optional enrichment
            examples = {}
    out_comps: dict[str, dict] = {}
    for name, entry in src_comps.items():
        if not isinstance(entry, dict):
            continue
        out_comps[name] = {
            "category": entry.get("category", ""),
            "data_shape": entry.get("data_shape", ""),
            "slot_hints": list(entry.get("slot_hints") or []),
            "summary": entry.get("summary", ""),
        }
        if include_examples:
            kp = entry.get("key_props") or []
            if isinstance(kp, list) and kp:
                out_comps[name]["key_props"] = kp
            ex = examples.get(name)
            if isinstance(ex, dict):
                out_comps[name]["example"] = ex
    return {"components": out_comps}


def load_library_manifest(output_dir: Path | str | None = None) -> dict:
    """Load a persisted manifest; build fresh if none/missing.

    Never raises — any I/O failure returns an empty dict so callers can
    treat it as "no manifest available" without crashing the pipeline.
    """
    if output_dir is None:
        try:
            return build_library_manifest()
        except Exception as exc:  # noqa: BLE001
            log.warning("[library-manifest] build failed: %s", exc)
            return {}
    path = Path(output_dir) / "contracts" / "library-manifest.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except FileNotFoundError:
        try:
            return build_library_manifest()
        except Exception as exc:  # noqa: BLE001
            log.warning("[library-manifest] build fallback failed: %s", exc)
            return {}
    except Exception as exc:  # noqa: BLE001
        log.warning("[library-manifest] load failed for %s: %s", path, exc)
        return {}
