"""Emit an A2UI v0.9 catalog from Forge's own component library.

Why this exists
---------------
A2UI's generation loop works because the catalog is a *closed set* validated
per-component, with a self-correct retry when the model steps outside it. Live
runs across five domains produced valid payloads on the first attempt every
time. That discipline is exactly what Forge's page authoring lacks — the Kanban
and Form breakage traced on q941voiw existed because the emitter, the schema
node and the React component were each free to disagree about the prop shape,
with nothing checking.

Pointing A2UI at the shipped `plc` catalog would author against ten components
Forge does not have. Generating the catalog *from* `library_manifest` instead
means the composer is constrained to components Forge can actually render, and
the contract has one source.

Scope
-----
This produces the composition surface only — the components a dashboard,
collection or record page is built from. Inputs, overlays and media are
deliberately excluded: they belong to form scaffolding and shell authoring,
which already have deterministic owners.

What this does NOT do
---------------------
The catalog says what can be *composed*. It says nothing about where data comes
from. A2UI payloads carry a literal `updateDataModel` — invented sample rows —
and importing those as-is would produce pages full of convincing fiction that
never touch Postgres. Translating a payload back into a Forge page schema is the
job of a separate binder that discards the sample data and substitutes real
`dataSources`. Keep that boundary.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.library_manifest import build_library_manifest

CATALOG_ID = "https://tentoroforge.local/a2ui/catalogs/forge/catalog.json"

_COMMON = "https://a2ui.org/specification/v0_9/common_types.json"

# The composition surface, grouped by the job each component does on a page.
# An explicit allowlist rather than a category filter: "every layout component"
# would drag in AppShell and Sidebar, which the shell owns, and hand the
# composer a way to re-author chrome it must not touch.
COMPOSITION_SET: dict[str, tuple[str, ...]] = {
    # The set was 27 components — 17% of a 157-component library — and the
    # shape of what was missing decided what the composer could never propose.
    # It had no input vocabulary at all, so it could not compose a create or
    # edit page; no Tabs, Stepper or Wizard, so it never reached for
    # progressive disclosure. That reads as conservative judgement and is
    # actually just absence.
    #
    # Deliberately still excluded, and why:
    #   * app frame — AppShell, SideNav, Sidebar, MobileNav, Breadcrumb.
    #     The shell has its own authority (build_shell_deterministic); a page
    #     composer reaching for chrome would fight it.
    #   * domain fixtures — the cart family, BarcodeScanner, CameraCapture,
    #     Scanner. These need archetype wiring the binder does not do.
    #   * behavioural wrappers — FocusTrap, AutoFocus, OptimisticProvider,
    #     UndoManager, Stagger, FadeIn. Not composition; they wrap it.
    #   * bespoke one-offs — the *Hero / *Rail / *Pulse family, authored for
    #     specific archetypes and meaningless outside them.
    "layout": ("Stack", "Row", "Grid", "Card", "Section", "Container", "Cluster",
               "Split", "SplitView", "Accordion", "AccordionPanel",
               "Tabs", "TabPanel", "Drawer", "Dialog"),
    "data": ("Table", "TableSortable", "DataGrid", "List", "DescriptionList",
             "KeyValueList", "Kanban", "Timeline", "ActivityFeed", "Tree",
             "Calendar", "CalendarWeek", "ResourceTimeline", "SearchResults"),
    "chart": ("MetricTile", "Chart", "Gauge", "Sparkline", "Stat", "Progress",
              "Heatmap", "Schematic", "SplitArc"),
    # Without these the composer cannot author a form, which is most of the
    # write surface of any business application.
    "form": ("Form", "Input", "Textarea", "Select", "MultiSelect", "Combobox",
             "Checkbox", "RadioGroup", "Switch", "NumberInput", "MoneyInput",
             "DatePicker", "DateRangePicker", "TimePicker", "FileUpload",
             "Slider", "Rating", "KeyValueInput", "MaskedInput", "InputOTP",
             "RichTextEditor", "ColorPicker", "SegmentedControl", "Cascader",
             "SearchInput", "FilterBar"),
    "display": ("Heading", "Text", "Badge", "Tag", "Divider", "Alert", "Avatar",
                "MoneyDisplay", "EmptyState", "EmptyStateRich", "IllustratedEmpty",
                "Banner", "Tooltip", "Popover", "HoverCard", "PersonCard",
                "FeatureCard", "Link", "CodeBlock", "QRCode", "Skeleton",
                "LoadingState", "Spinner", "ValidationChecklist"),
    "action": ("Button", "IconButton", "DropdownMenu", "Stepper", "Wizard",
               "BulkActionBar", "StickyPrimaryCta"),
}

# Components that hold other components. Everything else is a leaf, and saying
# so keeps the model from nesting a Table inside a Badge.
CONTAINERS = frozenset(
    {"Stack", "Row", "Grid", "Card", "Section", "Container", "Cluster", "Split"}
)

# Props whose value is a data binding rather than a literal. Typed as unknown so
# the model may emit either a literal or a path — the binder decides later which
# it was, and a stricter type here would just cause retry churn.
#: Props whose value is a data binding rather than a literal, described to the
#: composer as "data for this component" so it points rather than invents.
#:
#: `series` was here and is not one. A Chart's `data` is the measurement;
#: `series` says how to plot it — {name, dataKey, color} per line, where only
#: dataKey names a field. Described as data, A2UI sent a pointer, and the
#: binder had to notice and synthesise a descriptor: "A2UI's series is another
#: DATA pointer, not a Recharts series descriptor, so it resolves to nothing
#: and the prop vanishes — leaving the chart with rows but no encoding."
#: a2ui_to_forge already prefers a literal descriptor list (`already_shaped`)
#: and lists series in _CONFIG_DATA_PROPS as config rather than measurement.
#: So the binder wanted the descriptor all along; the catalog was asking for
#: the wrong thing.
#:
#: Out of this set it carries its item schema, and the composer is told what a
#: series entry must contain instead of discovering it from our validator.
_BINDING_PROPS = frozenset(
    {"data", "rows", "items", "bind", "dataSource", "columns", "entries"}
)


# ── Prop authority ────────────────────────────────────────────────────────
#
# `component-contracts.json` is generated from the components' real Zod props,
# so it is the only source that knows a prop's enum members and whether it is
# required. Reading it directly is what closes the gap that bit three separate
# times: a catalog that says "format is a string" produces a MetricTile with no
# format at all (schema-valid to A2UI, rejected by Forge, silently blank), and
# a catalog that omits Chart.series produces a chart with rows and no encoding.
#
# It was tempting to hand-maintain the enum lists instead. That was in fact the
# first attempt, and it was already wrong: the hand-written `format` list
# included "text", which the real contract does not accept. Hand-maintained
# copies of a generated contract drift by construction — that is the whole
# failure this catalog exists to prevent, so it must not be reintroduced here.
CONTRACTS_PATH = (
    Path(__file__).resolve().parents[2]
    / "packages" / "registry" / "dist" / "component-contracts.json"
)

# The five components with no contract entry are the schema-package primitives
# (layout + Text), which are declared in packages/schema/src/nodes rather than
# in the library, so the registry's extractor never sees them. Transcribed from
# those nodes; kept deliberately small, and every entry is a component the
# contract file genuinely cannot cover.
_PRIMITIVE_PROPS: dict[str, dict[str, dict]] = {
    "Stack": {
        "direction": {"type": "enum", "enum": ["vertical", "horizontal"], "optional": True},
        "gap": {"type": "string", "optional": True},
        "align": {"type": "enum", "enum": ["start", "center", "end", "stretch"], "optional": True},
        "justify": {"type": "enum",
                    "enum": ["start", "center", "end", "between", "around"], "optional": True},
        "wrap": {"type": "boolean", "optional": True},
    },
    "Row": {
        "gap": {"type": "string", "optional": True},
        "align": {"type": "enum", "enum": ["start", "center", "end", "stretch"], "optional": True},
        "justify": {"type": "enum",
                    "enum": ["start", "center", "end", "between", "around"], "optional": True},
        "wrap": {"type": "boolean", "optional": True},
    },
    "Grid": {
        "columns": {"type": "number"},
        "gap": {"type": "string", "optional": True},
        "equalRows": {"type": "boolean", "optional": True},
    },
    "Container": {
        "maxWidth": {"type": "enum",
                     "enum": ["sm", "md", "lg", "xl", "2xl", "full"], "optional": True},
    },
    "Text": {
        "content": {"type": "string", "optional": True},
        "as": {"type": "enum",
               "enum": ["span", "p", "h1", "h2", "h3", "h4", "h5", "h6",
                        "label", "strong", "em"], "optional": True},
    },
}

# Props the composer must never author: identity, layout plumbing, or things a
# later pass owns.
_SKIP_PROPS = frozenset({
    "id", "component", "children", "style", "className", "args",
    "dataJourney", "aria-label", "key",
})


def load_contracts(path: Path | str | None = None) -> dict:
    """The generated Zod-derived prop contracts. Missing file → {}."""
    p = Path(path) if path else CONTRACTS_PATH
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


#: Props a component renders happily without and cannot be *composed* without.
#: The render/compose split again: `List.items` is `z.array(Item).default([])`,
#: so an empty list renders as an empty list — correct at runtime, and useless
#: as a composition. A2UI, given a component that declared no place to put its
#: content, put children on it instead and the page was rejected.
#:
#: Kept here rather than in the generated contract because it is a judgement
#: about composition, not a fact about the component, and the generated file
#: describes the component. `Chart.series` needs no entry: the contract already
#: marks it required, for the same reason.
_COMPOSE_REQUIRED: dict[str, frozenset[str]] = {
    "List": frozenset({"items"}),
}


def _zod_facts(name: str) -> dict[str, dict]:
    """Types, enums and item shapes for `name`, as Zod declares them.

    Facts about a component, not judgements about a composition — which is the
    line this stops short of. Zod also says `Chart.series` is optional, and it
    is right to: charts.ts coerces a null series to [] so an unbound chart
    renders empty in the editor rather than "invalid props". That is a
    *renderer* tolerance. A composer that omits series has drawn a chart of
    nothing, so required-ness stays with the contract that governs composition.

    A prop optional at render time can be mandatory at compose time. Never the
    reverse — which is why this returns shape and says nothing about presence.
    """
    try:
        from services.blueprint.page_planner import load_catalog
        entry = (load_catalog().get(name) or {}).get("props") or {}
    except Exception:  # noqa: BLE001
        return {}
    return {
        prop: {k: v for k, v in spec.items()
               if k in ("type", "enum", "items", "format")}
        for prop, spec in (entry.get("properties") or {}).items()
        if isinstance(spec, dict)
    }


def _zod_shapes(name: str) -> dict[str, dict]:
    """Array item shapes from the Zod-derived catalog, keyed by prop.

    component-contracts.json stops at ``{"type": "array"}``. The Zod catalog
    carries the item schema — ``Chart.series`` items require ``name`` and
    ``dataKey`` — and A2UI composed a series with neither, because nothing it
    was shown said they existed. Same shape of gap that cost three page trees
    to a prose digest describing ``array<object>`` with no item schema.

    Read lazily and never fatally: a missing catalog degrades this to what the
    contract alone says, which is where it started.
    """
    try:
        from services.blueprint.page_planner import load_catalog
        props = ((load_catalog().get(name) or {}).get("props") or {})
        return {k: v for k, v in (props.get("properties") or {}).items()
                if isinstance(v, dict) and v.get("items")}
    except Exception:  # noqa: BLE001
        return {}


def props_for(name: str, contracts: dict) -> dict[str, dict]:
    """Every authorable prop for `name`, contract first, primitives second.

    Merged, not swapped. The contract is richer for the structural primitives
    — Stack's align/direction/gap, Container's maxWidth — which the Zod
    catalog omits because the renderer dispatches them directly rather than
    registering them. The Zod catalog is richer for everything nested. Taking
    either alone loses real constraints.
    """
    entry = contracts.get(name)
    if isinstance(entry, dict) and entry:
        out = {k: v for k, v in entry.items()
               if k not in _SKIP_PROPS and isinstance(v, dict)}
    else:
        out = dict(_PRIMITIVE_PROPS.get(name, {}))
    # Shape from Zod, presence from the contract: `optional` is never taken
    # from the overlay, so a renderer tolerance cannot loosen a compose-time
    # requirement.
    for prop, facts in _zod_facts(name).items():
        if prop in out:
            out[prop] = {**out[prop], **facts}
    return out


def _prop_schema(name: str, spec: dict) -> dict:
    """One property entry, straight off the contract.

    String-ish props use DynamicString so the model can bind them to the data
    model; the binder rewrites those into Forge's `{{source.field}}` form.
    """
    if name in _BINDING_PROPS:
        return {"description": f"{name} — data for this component."}
    raw = str(spec.get("type") or "").lower()
    # Enum members come from the contract, never from a list maintained here.
    # Two conventions reach this: component-contracts.json writes
    # {"type": "enum", "enum": [...]}, and JSON Schema — which is what the Zod
    # overlay supplies — writes {"enum": [...]} with no such type. Keying on
    # the type alone silently turned every overlaid enum into a free string.
    members = spec.get("enum")
    if isinstance(members, list) and members:
        return {"enum": list(members)}
    if raw == "boolean":
        return {"type": "boolean"}
    if raw in ("number", "integer"):
        return {"type": "number"}
    if raw == "array":
        # The item shape when the merge supplied one, so a required nested
        # field reaches the composer instead of being discovered by our
        # validator after the fact.
        items = spec.get("items")
        return {"type": "array", "items": items} if items else {"type": "array"}
    return {"$ref": f"{_COMMON}#/$defs/DynamicString"}


def _component_schema(name: str, entry: dict, contracts: dict) -> dict:
    props: dict[str, Any] = {"component": {"const": name}}
    required: list[str] = ["component"]
    for pname, spec in sorted(props_for(name, contracts).items()):
        props[pname] = _prop_schema(pname, spec)
        # Required-ness has to reach the catalog or the composer cannot know
        # it. Dropping it is why a generated MetricTile arrived without
        # `format` and rendered a blank value (schema-valid to A2UI, rejected
        # by Forge's node, silently empty on the page), and why a Chart arrived
        # without `series` and plotted nothing.
        if not spec.get("optional") or pname in _COMPOSE_REQUIRED.get(name, ()):
            required.append(pname)

    if name in CONTAINERS:
        props["children"] = {
            "description": (
                "Child component ids. Children are referenced by id, never "
                "inlined."
            ),
            "$ref": f"{_COMMON}#/$defs/ChildList",
        }

    body: dict[str, Any] = {
        "type": "object",
        "properties": props,
        "required": required,
    }
    summary = (entry.get("summary") or "").strip()
    if summary:
        body["description"] = summary[:300]

    return {
        "type": "object",
        "allOf": [
            {"$ref": f"{_COMMON}#/$defs/ComponentCommon"},
            {"$ref": "#/$defs/CatalogComponentCommon"},
            body,
        ],
    }


def build_a2ui_catalog(manifest: dict | None = None) -> dict:
    """Forge's component library as an A2UI v0.9 catalog."""
    man = manifest or build_library_manifest()
    comps = man.get("components") or {}

    wanted = [n for group in COMPOSITION_SET.values() for n in group]
    missing = [n for n in wanted if n not in comps]
    present = [n for n in wanted if n in comps]

    contracts = load_contracts()
    components = {n: _component_schema(n, comps[n], contracts) for n in present}

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": CATALOG_ID,
        "catalogId": CATALOG_ID,
        "title": "Tentoro Forge composition catalog",
        "description": (
            "The Forge component library, expressed as an A2UI catalog. Covers "
            "page composition only — inputs, overlays and shell chrome have "
            "deterministic owners elsewhere in the pipeline."
        ),
        "components": components,
        "functions": {},
        "$defs": {
            "CatalogComponentCommon": {
                "type": "object",
                "properties": {
                    "weight": {
                        "type": "number",
                        "description": (
                            "Relative flex-grow within a Row or Column. Only "
                            "valid on a direct child of a layout component."
                        ),
                    }
                },
            },
            "anyComponent": {
                "oneOf": [{"$ref": f"#/components/{n}"} for n in present]
            },
            "anyFunction": {"oneOf": [{"type": "null"}]},
            "_missing": missing,
        },
    }


def write_a2ui_catalog(dest: Path | str) -> Path:
    """Write the catalog to `dest` (a directory or an explicit .json path)."""
    cat = build_a2ui_catalog()
    p = Path(dest)
    if p.is_dir() or not p.suffix:
        p = p / "catalog.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cat, indent=2) + "\n", encoding="utf-8")
    return p
