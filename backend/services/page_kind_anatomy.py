"""Substance floors for the page kinds that are not dashboards.

Why this exists
---------------
``dashboard_anatomy`` gave the landing route a floor, and nothing else has one.
``page_anatomy`` looks like the missing piece but is not: it is *repair*-shaped
(``apply_page_anatomy`` mutates pages to fix them) rather than a pure predicate,
so there is nothing a caller can ask "is this collection page good enough".

That matters now for a reason beyond reporting. The A2UI composer is safe to
leave switched on because of one property: it writes nothing unless the page it
produced clears a floor. That property is only as wide as the floors, so
widening A2UI past the dashboard without widening the floors would quietly
trade the safety for the scope.

What the corpus says
--------------------
Measured across the 78 output apps carrying a plan (the plan is what declares a
page's kind — route shape does not, and guessing from it sweeps ``/login`` and
``/profile`` into "collections"):

    list    n=473    2% have no list surface     17% have no action at all
    form    n= 73    6% have no field or Form     5% have no submit
    detail  n= 36   11% have no detail body      33% have no action at all

These are much lower defect rates than the dashboard's (34% shipped chartless),
so as a repair tool this earns little. Its value is as a decline criterion: a
composer proposing a collection page with no table, or a detail page with no
way to act on the record, should not have that page written.

The rules, and why each is a floor rather than a preference
-----------------------------------------------------------
* a collection exists to show many records — with no list surface it is a title
* a collection with nothing to click is a reading dead end: no create, no
  row action, nothing. 17% of shipped list pages
* a detail page with no body renders a heading and whitespace
* a detail page with no action is a leaf a third of the time — the reader
  arrives and cannot edit, delete, advance or go back
* a form with no field cannot collect anything
* a form with no submit cannot deliver what it collected

Slots are matched by JOB, not by one blessed component name — the same choice
``dashboard_anatomy`` makes, for the same reason: pinning a rule to one type
teaches authors to satisfy the letter of it.

Shape
-----
Pure predicate, no I/O, mirroring ``dashboard_findings`` so both consumers
(the delivery gate, the A2UI decline check) read one rule rather than each
re-deriving what a page kind needs.
"""

from __future__ import annotations

import re

from typing import Any

from services.dashboard_anatomy import page_root

# ---------------------------------------------------------------- families
#
# The planner names kinds with more words than there are shapes. `list` and
# `collection` are the same job; `create`, `edit` and `form` are the same job.
# Normalising here keeps the rules from multiplying with the vocabulary.
#: Every page kind this pipeline can declare, reduced to the four shapes the
#: floors are written for.
#:
#: THE DECLARED PATTERNS WERE MISSING FROM IT, and the consequence was not that
#: they went unjudged — it is that they were judged as something else. Measured
#: across the Blueprint's eighteen-pattern enum:
#:
#:   * eleven fell through to `a2ui_authority._family_of`'s `dashboard`
#:     default, so `settings`, `configuration`, `calendar`, `search_results`,
#:     `data_explorer` and `document_workspace` were each required to carry
#:     KPIs, a chart and an activity feed. A security-settings page cannot
#:     satisfy that, so it was refused every time — six of the fourteen routes
#:     that 404ed on a real application.
#:   * five more — `entity_list`, `record_workspace`, `master_detail`,
#:     `wizard`, `approval_inbox`, which is most of what any application is
#:     made of — matched nothing here, so `page_kind_findings` returned "not my
#:     rule" and they were held to NO floor whatsoever.
#:
#: Wrong in both directions at once, from one table being incomplete. The
#: generic words below stay: callers outside the Blueprint pipeline pass
#: `list`, `detail`, `form` and always have.
_FAMILY = {
    # Generic kind words, from callers that predate the pattern enum.
    "list": "collection", "collection": "collection", "index": "collection",
    "search": "collection",
    "form": "form", "create": "form", "edit": "form", "new": "form",
    "detail": "record", "record": "record", "show": "record", "profile": "record",

    # The Blueprint's declared patterns. Every one of them, deliberately: a
    # pattern absent here is a page judged by a floor written for a different
    # kind of screen, and `test_every_declared_pattern_has_a_family` fails
    # rather than letting a new pattern default into one.
    #
    # dashboard — numbers, a breakdown worth charting, what just happened.
    "dashboard": "dashboard",
    "analytics": "dashboard",
    "command_center": "dashboard",
    # collection — many records, however they are laid out. A calendar and a
    # kanban are lists with an opinion about position, not a different job.
    "entity_list": "collection",
    "approval_inbox": "collection",
    "kanban": "collection",
    "calendar": "collection",
    "scheduler": "collection",
    "timeline": "collection",
    "search_results": "collection",
    "data_explorer": "collection",
    # record — one thing, in detail, with something to do to it.
    "master_detail": "record",
    "record_workspace": "record",
    "split_view": "record",
    "document_workspace": "record",
    # form — the reader is here to enter or change values.
    "wizard": "form",
    "configuration": "form",
    "settings": "form",
}

# A surface that shows many records. Kanban and Calendar qualify — they are
# lists with an opinion about layout, not a different job.
# `CardGrid` was here and is in neither the engine registry nor the A2UI
# catalog, so no page could ever satisfy this floor by carrying one. A floor
# that names a component nothing can produce is not a lenient floor, it is a
# misleading one — it reads as an offered alternative that is not on the menu.
# `Repeat` stays: `a2ui_to_forge` MINTS it, so it is absent from the A2UI
# catalog and present in the tree these floors actually judge.
_LIST_TYPES = frozenset({
    "Table", "TableSortable", "DataGrid", "List", "Kanban", "Calendar",
    "CalendarWeek", "Timeline", "ResourceTimeline", "Repeat",
    "SearchResults", "Tree",
})

# Anything that renders a single record's substance.
_BODY_TYPES = frozenset({
    "DescriptionList", "KeyValueList", "Table", "List", "Card", "Tabs",
    "TabPanel", "Timeline", "ActivityFeed", "Form",
})

# A control that collects a value. `Form` counts on its own: it carries its
# fields as a prop rather than as child nodes.
_FIELD_TYPES = frozenset({
    "Form", "Input", "Textarea", "Select", "MultiSelect", "Combobox",
    "Checkbox", "RadioGroup", "Switch", "NumberInput", "MoneyInput",
    "DatePicker", "DateRangePicker", "TimePicker", "FileUpload", "Slider",
    "Rating", "KeyValueInput", "MaskedInput", "InputOTP", "RichTextEditor",
    "ColorPicker", "SegmentedControl", "Cascader", "EditableLineGrid",
})

# A page that only redirects is a routing artifact, not a screen. The route
# reconciler (DEDUP-1) collapses duplicate routes into these, so `/staffs`
# legitimately contains one `Redirect` and nothing else. Judging it against a
# collection floor reports a missing table on a page that was never meant to
# have one — a false positive that would teach people to distrust the gate.
_ROUTING_ONLY = frozenset({"Redirect"})

_ACTION_TYPES = frozenset({
    "Button", "IconButton", "DropdownMenu", "AddToCart", "StickyPrimaryCta",
    "BulkActionBar", "Wizard", "Stepper",
})


#: A route the scaffold's own tree owns as a form. `[entity]/new/page.tsx` and
#: `[entity]/[id]/edit/page.tsx` ship with every generated app, so a route
#: ending this way IS a form — that is a fact about the router, not a reading
#: of the route string.
_FORM_ROUTE = re.compile(r"/(new|edit)/?$")


def route_family(route: Any) -> str | None:
    """The family a ROUTE settles, or None when the route has no opinion.

    THE PATTERN ENUM CANNOT NAME A CREATE FORM. Its eighteen values offer
    `wizard`, `configuration` and `settings` for the form family and nothing
    for the commonest screen in any CRUD app, so `page_contracts` labelled
    `/contacts/new`, `/contacts/[id]/edit` and `/sign-in` `record_workspace` —
    the least-bad value available to it.

    Everything downstream then behaved correctly on a false premise. The family
    became `record`, so the composer was handed the record job — "This screen
    shows ONE record in detail" — for a page whose entire purpose is to collect
    one. It composed a detail surface, never bound `FLOW-001 Create Contact`
    (which names PAGE-003 in its own `launchedFrom`), and the record floor
    refused it for having no action. Two runs, two different errors, one cause.

    The route is the stronger evidence and it was already being passed to
    `page_kind_findings` and ignored. A declared pattern is one agent's choice
    among values that could not express the answer; `/contacts/new` is a fact.
    """
    return "form" if _FORM_ROUTE.search(str(route or "").strip()) else None


def page_family(kind: Any) -> str | None:
    """The shape family a declared page kind belongs to, or None if this
    module has no opinion (auth, static, visual_scan and friends)."""
    return _FAMILY.get(str(kind or "").strip().lower())


def _types_present(root: dict) -> set[str]:
    out: set[str] = set()

    def walk(n: Any) -> None:
        if not isinstance(n, dict):
            return
        out.add(n.get("type"))
        for c in n.get("children") or []:
            walk(c)

    walk(root)
    return out


def _walk_nodes(node: Any) -> Any:
    """Every node in the tree, as dicts. `_types_present` throws the props away
    and some floors need them."""
    if isinstance(node, list):
        for item in node:
            yield from _walk_nodes(item)
        return
    if not isinstance(node, dict):
        return
    yield node
    for child in node.get("children") or []:
        yield from _walk_nodes(child)


def _submits(root: dict) -> bool:
    """Whether anything here can deliver what the form collected.

    A `Form` IS ITS OWN SUBMIT. It renders the button from `submitLabel` and
    posts to `workflow`, exactly as it carries its inputs in `fields` rather
    than as child nodes — which is why `_FIELD_TYPES` already counts it alone.
    `_ACTION_TYPES` lists only child-node controls, so a correct create page
    holding one Form and no separate Button was refused for having no submit:
    A2UI composed `{Container, Stack, Text, Link, Card, Form}` for
    /contacts/new and the floor called it undeliverable.

    Asking for a Button beside a Form asks for a second submit, and the
    composer was right not to add one.

    The action props come from the composer's own contract for the same reason
    `functional_completeness._action_props` reads them there: a hand-copied
    list is how `opensDialog` came to be refused on a modal create form.
    """
    try:
        from services.a2ui_catalog import _COMPOSE_ONE_OF
        actions = {p for choices in _COMPOSE_ONE_OF.values() for p in choices}
    except Exception:  # noqa: BLE001 — a floor must not fail on a lookup
        actions = {"workflow", "navigate", "submit", "onClick"}

    for node in _walk_nodes(root):
        kind = str(node.get("type"))
        if kind in _ACTION_TYPES:
            return True
        if kind == "Form" and (set(node.get("props") or {}) & actions):
            return True
    return False


def _finding(rule: str, route: str, slot: str, detail: str) -> dict:
    return {"rule": rule, "route": route, "slot": slot,
            "severity": "error", "action": "reported", "detail": detail}


def page_kind_findings(kind: Any, route: str, doc: Any) -> list[dict]:
    """Everything this page kind promises and this page does not deliver.

    An empty list means the page does its job. A kind with no family — auth,
    static — always returns empty: silence here means "not my rule", never
    "checked and fine".
    """
    # The route first: it settles create and edit screens that the pattern enum
    # has no value for. See `route_family`.
    family = route_family(route) or page_family(kind)
    if family is None:
        return []

    root = page_root(doc)
    if root is None:
        # Same stance as the dashboard floor: an unreadable page cannot be
        # judged, and a page that cannot be judged must not pass by default.
        # Scoring it flawless is how ten legacy-shaped dashboards read clean.
        return [_finding(f"{family}_unreadable", route, "page",
                         "page schema has no readable root node, so nothing "
                         "about it could be checked")]

    types = _types_present(root)

    # Routing artifacts carry no UI and promise none.
    if types & _ROUTING_ONLY:
        return []

    out: list[dict] = []

    if family == "collection":
        if not (types & _LIST_TYPES):
            out.append(_finding(
                "collection_no_list_surface", route, "list",
                "a collection page shows many records and this one carries no "
                "table, list, board or calendar — it is a title over nothing."))
        if not (types & _ACTION_TYPES):
            out.append(_finding(
                "collection_no_action", route, "action",
                "nothing on this collection can be clicked: no create, no row "
                "action, no filter control. A reader arrives and leaves."))

    elif family == "record":
        if not (types & _BODY_TYPES):
            out.append(_finding(
                "record_no_body", route, "body",
                "a record page shows one thing in detail and this one carries "
                "no description list, card or table — a heading over whitespace."))
        if not (types & _ACTION_TYPES):
            out.append(_finding(
                "record_no_action", route, "action",
                "the reader can see this record and do nothing with it — no "
                "edit, no delete, no advance, not even a way back."))

    elif family == "form":
        if not (types & _FIELD_TYPES):
            out.append(_finding(
                "form_no_fields", route, "fields",
                "a form with no field collects nothing."))
        if not _submits(root):
            out.append(_finding(
                "form_no_submit", route, "submit",
                "a form with no submit cannot deliver what it collected."))

    return out


__all__ = ["page_kind_findings", "page_family",
           "_LIST_TYPES", "_BODY_TYPES", "_FIELD_TYPES", "_ACTION_TYPES"]
