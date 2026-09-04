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
from typing import Any, Sequence

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
#
# `args` WAS ON THIS LIST AND IS NOT PLUMBING. It is the only channel a control
# has for telling a workflow what to act on: Button/Link/IconButton pass it to
# `fallbackDispatch(workflow, args)`, which posts `{input: args ?? {}}`. Filed
# next to `className` and `style` it was never authorable, so it was never
# authored, so every dispatch left `input` empty — a "Mark as watered" button
# reached a db_insert whose config reads `{"plantId": "{{plantId}}"}` and
# inserted a null plant_id. The workflow was right, the button was right, and
# the one prop connecting them had been classified as decoration.
_SKIP_PROPS = frozenset({
    "id", "component", "children", "style", "className",
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
#: Components that must declare at least one of a set — the prop is not fixed,
#: but having none of them is meaningless. Emitted as `anyOf`, so the schema
#: names the alternatives instead of only refusing what is not on the list.
#: Layout primitives have no component file, so `_extract_summary` finds no
#: doc comment and the manifest falls back to "Stack (layout)" — a description
#: that says nothing. Every page of every run then spent an attempt on
#: `unknown component "Column"`: A2UI could see `Row`, needed the vertical
#: counterpart, and wrote the obvious name for it. Nothing anywhere said Stack
#: was that counterpart.
#:
#: The builder is the only place these can be described, because there is no
#: file to put a doc comment in.
_STRUCTURAL_SUMMARIES: dict[str, str] = {
    "Stack": ("Vertical layout — children flow top to bottom. This is the "
              "column primitive; there is no 'Column' component. Use "
              "`direction: horizontal` to lay out in a row instead."),
    "Row": ("Horizontal layout — children flow left to right. The vertical "
            "counterpart is Stack. ONE row of fixed content, not one row per "
            "record: a Row copied per record cannot bind per-record data, "
            "because a layout node has no notion of a current item. To render "
            "many records, bind Table.rows or List.items and let the component "
            "iterate."),
    "Grid": ("Two-dimensional layout — children flow into `columns` tracks "
             "and wrap. For a single column use Stack, for a single row Row."),
    "Container": ("Page-width wrapper — centres its children and applies the "
                  "page gutter. Holds one layout, usually a Stack."),
    "Section": ("A titled region of a page — a heading and its content, as "
                "one block. Holds one layout, usually a Stack."),
}


_COMPOSE_ONE_OF: dict[str, tuple[str, ...]] = {
    # A button that does none of these is a label with a border.
    #
    # EVERY way the component can act, not the ones that came to mind. The
    # first version listed four and the catalog offers six, so a Button written
    # as {label: "Edit", opensDialog: "editDialog"} — correct, and exactly what
    # a page whose create form is a modal needs — was refused for declaring an
    # action that was not on the list. The constraint was right and the
    # enumeration was mine.
    "Button": ("workflow", "navigate", "submit", "onClick",
               "opensDialog", "togglesSidebar"),
    # A form that submits nowhere is a page-shaped dead end, and
    # `functional_completeness._ACTIONABLE` has always been ("Button", "Form")
    # — so a Form with no action was already refused. It was never told:
    # `anyOf` was on Button alone, so the composer had no way to know the
    # requirement existed until the page came back rejected. Twice on the last
    # full build, both on create pages.
    #
    # DERIVED, NOT ENUMERATED. `_action_props()` reads this table, so the check
    # and the catalog cannot disagree about what an action is — and `workflow`
    # is the only member of that union the Form contract actually offers.
    # `onSuccess` and `onError` are what happens after the action; `autoSave`
    # carries a workflow of its own for drafts and is not the submit. Listing
    # any of them would demand a prop that cannot satisfy the check.
    #
    # Adding this changes no behaviour in `_action_props()` — `workflow` is
    # already in the union from Button — so nothing newly fails. What changes
    # is that the requirement is now stated where the composer reads it.
    "Form": ("workflow",),
}


_COMPOSE_REQUIRED: dict[str, frozenset[str]] = {
    "List": frozenset({"items"}),
    # A chart with no data is the falsity the closing rule warns about, drawn
    # instead of written. Three shipped on one run carrying chartType, series,
    # xKey and showGrid and no `data` at all — describing a dataset's columns
    # without ever naming a dataset.
    #
    # Nothing reported it, because ChartNode coerces a missing `data` to `[]`
    # (packages/schema/src/nodes/charts.ts) so the chart renders empty rather
    # than invalid. That coercion is the render contract's business — an empty
    # chart while data loads is legitimate. What it cannot distinguish is "not
    # loaded yet" from "never bound", so the compose contract has to say the
    # prop must be there.
    "Chart": frozenset({"data"}),
    "Sparkline": frozenset({"data"}),
    "Heatmap": frozenset({"data"}),
    # Gauge reads a single number rather than a series.
    "Gauge": frozenset({"value"}),
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
    # WHAT THE WORKFLOW ACTS ON. The contract types `args` as a bare object,
    # which is true and says nothing — a composer reading `{"type": "object"}`
    # has no reason to write one, and a dispatch with no inputs is not visibly
    # wrong until a row lands with a null column.
    #
    # Bindings are legitimate here and are the usual case: `renderNode` runs
    # `interpolateDeep` over every prop before the click handler sees it
    # (renderer/src/runtime/dispatch.tsx), so a nested `{{plant.id}}` resolves
    # against the row the control sits in.
    if name == "args":
        return {
            "type": "object",
            "description": (
                "Inputs for the dispatched workflow, keyed by the parameter "
                "names the workflow uses. Values may be bindings, and usually "
                "are: {\"plantId\": \"{{plant.id}}\"}. A workflow that names a "
                "parameter receives nothing for it unless this supplies it."
            ),
        }
    # A binding prop by name AND by shape. `rows`, `columns` and `items` name
    # data on a Table or a List and something else entirely elsewhere:
    # `Textarea.rows` is how many lines to show and `Grid.columns` is how many
    # tracks to lay out, both integers. Describing those as "data for this
    # component" invited a binding where a number belongs.
    # Excluded by type, not selected by it. `Table.rows` is declared a string
    # because a Mustache binding IS a string, so an allow-list of array/object
    # dropped the very props this branch exists for. What must not be a
    # binding is a number: `Textarea.rows` is how many lines to show and
    # `Grid.columns` how many tracks to lay out.
    if name in _BINDING_PROPS and str(spec.get("type") or "").lower() not in (
        "number", "integer", "boolean",
    ):
        return {"description": f"{name} — data for this component."}
    raw = str(spec.get("type") or "").lower()
    # Enum members come from the contract, never from a list maintained here.
    # Two conventions reach this: component-contracts.json writes
    # {"type": "enum", "enum": [...]}, and JSON Schema — which is what the Zod
    # overlay supplies — writes {"enum": [...]} with no such type. Keying on
    # the type alone silently turned every overlaid enum into a free string.
    members = spec.get("enum")
    if isinstance(members, list) and members:
        # A literal member, or a binding that resolves to one. A status badge
        # whose colour follows the row is the ordinary case, and describing
        # `variant` as a bare enum refused it: A2UI bound
        # {'path': '/plant/statusVariant'}, its own validator rejected the
        # binding three times, and the page fell back to the authoring agent.
        #
        # Safe on our side: validate_props already treats a binding string as
        # deferred, because the renderer supplies the value later and there is
        # nothing to type-check until it does.
        return {"anyOf": [
            {"enum": list(members)},
            {"$ref": f"{_COMMON}#/$defs/DynamicString"},
        ]}
    if raw == "boolean":
        return {"type": "boolean"}
    if raw in ("number", "integer"):
        return {"type": "number"}
    if raw == "object":
        # AN OBJECT IS NOT A STRING. Every branch below handled a scalar or an
        # array and everything else fell through to DynamicString, so
        # `Table.emptyAction` — {label, navigate?, workflow?} in Zod — was
        # described to A2UI as text. A2UI wrote "New survey", exactly what the
        # catalog asked for, and our own validator rejected it: the page did
        # not ship and the application lost its list screen.
        #
        # The shape when the contract carries one, and a bare object when it
        # does not. "An object, keys unspecified" is a smaller claim than the
        # truth and a much smaller error than "a string".
        shape = spec.get("properties")
        if isinstance(shape, dict) and shape:
            out: dict[str, Any] = {"type": "object", "properties": shape}
            req = spec.get("required")
            if isinstance(req, list) and req:
                out["required"] = list(req)
            return out
        return {"type": "object"}
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
    # ONE OF THESE, NOT NONE OF THEM. A Button offers four ways to act —
    # workflow, navigate, onClick, submit — and, with all four optional, the
    # contract never said a button has to do anything. A composer reading that
    # invents the prop the schema seems to be missing: every failing page
    # carried `Button.action`, which is not ours and not A2UI's either.
    # `additionalProperties: false` rejected it without ever saying what to
    # write instead, so the retry guessed again and PAGE-003 died having
    # guessed three times.
    #
    # Stated as a constraint rather than repaired by an alias: the alias table
    # in a2ui_to_forge says of itself that it is a stopgap for a thin contract,
    # and this is the contract being thin.
    choices = _COMPOSE_ONE_OF.get(name)
    if choices:
        present = [c for c in choices if c in props]
        if present:
            body["anyOf"] = [{"required": [c]} for c in present]
    summary = (_STRUCTURAL_SUMMARIES.get(name)
               or (entry.get("summary") or "")).strip()
    if summary:
        body["description"] = summary[:300]

    return {
        "type": "object",
        "allOf": [
            {"$ref": f"{_COMMON}#/$defs/ComponentCommon"},
            {"$ref": "#/$defs/CatalogComponentCommon"},
            body,
        ],
        # THE COMPOSER'S VALIDATOR AND OURS AGREE NOW. This was absent, so it
        # defaulted to true: A2UI validated its own output against a catalog
        # that accepted any extra property, passed, returned — and Forge's
        # catalog, which sets `additionalProperties: false`, refused the page.
        # `density` on a Card cost a composition three minutes after A2UI had
        # already declared it valid, and A2UI's own three retries never fired
        # because its validator saw nothing wrong.
        #
        # `unevaluatedProperties`, not `additionalProperties`: this is an
        # `allOf`, and `additionalProperties` in one branch cannot see the
        # properties the two `$ref`s contribute, so it would reject `id` and
        # everything else inherited. `unevaluatedProperties` is evaluated
        # across the whole composition, which is what draft 2020-12 added it
        # for. A2UI builds Draft202012Validator, so it is understood.
        #
        # STRICTNESS WAS TRIED BEFORE AND MADE THINGS WORSE — see the note
        # above on `_COMPOSE_ONE_OF`: `additionalProperties: false` rejected
        # `Button.action` without saying what to write instead, so the retry
        # guessed again and a page died having guessed three times. What was
        # missing then was a positive statement of the requirement, and that
        # is what `anyOf` now supplies. Rejecting an invented prop is only
        # safe alongside a schema that says what the real one is.
        "unevaluatedProperties": False,
    }


def _constrain_workflows(node: Any, ids: list[str]) -> Any:
    """Every `workflow` property becomes the list of ids that actually exist.

    The composer was told, in prose, which workflows a screen launches and to
    "put the id in `workflow` on the Button or Form that runs it". It wrote
    `createDocument`, `save_draft`, `mark_read` — plausible names for real
    intentions, none of them an id — and five pages were refused for naming a
    workflow the application does not define.

    It was not disobeying a constraint. The catalog typed `workflow` as
    DynamicString, so ANY string was schema-valid, and prose lost to schema.
    An enum makes the invented name unrepresentable: A2UI validates its own
    output against this catalog before returning it, so a wrong id is caught
    and retried inside the composer rather than surfacing as a refused page
    three minutes later.

    Constrain, don't correct — the alternative is mapping `createDocument` onto
    the nearest real id after the fact, which is guessing at intent, silently,
    and right often enough that nobody removes it.

    THE APPLICATION'S IDS, NOT THE PAGE'S. The per-page set is narrower and is
    still what the domain context names, but the catalog is one document shared
    by every page in a run — the cached prefix. Enumerating per page would
    rebuild it 53 times and lose the cache to buy a narrowing that prose
    already does. What this removes is the invented id, which is the failure
    that was actually observed.
    """
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key == "properties" and isinstance(value, dict):
                out[key] = {
                    pk: ({"enum": ids,
                          "description": ("The id of the workflow this runs. "
                                          "One of the application's own "
                                          "workflows — not a name you choose.")}
                         if pk == "workflow" else _constrain_workflows(pv, ids))
                    for pk, pv in value.items()
                }
            else:
                out[key] = _constrain_workflows(value, ids)
        return out
    if isinstance(node, list):
        return [_constrain_workflows(x, ids) for x in node]
    return node


def build_a2ui_catalog(manifest: dict | None = None,
                       workflows: Sequence[str] = ()) -> dict:
    """Forge's component library as an A2UI v0.9 catalog.

    ``workflows`` are the application's workflow ids. Given them, every
    `workflow` prop is enumerated instead of typed as free text — see
    `_constrain_workflows`. Empty leaves the catalog exactly as it was, which
    is what every caller without an application to hand gets.
    """
    man = manifest or build_library_manifest()
    comps = man.get("components") or {}

    wanted = [n for group in COMPOSITION_SET.values() for n in group]
    missing = [n for n in wanted if n not in comps]
    present = [n for n in wanted if n in comps]

    contracts = load_contracts()
    components = {n: _component_schema(n, comps[n], contracts) for n in present}

    ids = sorted({str(w) for w in (workflows or []) if str(w).strip()})
    if ids:
        components = _constrain_workflows(components, ids)

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


def write_a2ui_catalog(dest: Path | str,
                       workflows: Sequence[str] = ()) -> Path:
    """Write the catalog to `dest` (a directory or an explicit .json path)."""
    cat = build_a2ui_catalog(workflows=workflows)
    p = Path(dest)
    if p.is_dir() or not p.suffix:
        p = p / "catalog.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cat, indent=2) + "\n", encoding="utf-8")
    return p
