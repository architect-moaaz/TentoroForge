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

from typing import Any

from services.dashboard_anatomy import page_root

# ---------------------------------------------------------------- families
#
# The planner names kinds with more words than there are shapes. `list` and
# `collection` are the same job; `create`, `edit` and `form` are the same job.
# Normalising here keeps the rules from multiplying with the vocabulary.
_FAMILY = {
    "list": "collection", "collection": "collection", "index": "collection",
    "search": "collection", "kanban": "collection",
    "form": "form", "create": "form", "edit": "form", "new": "form",
    "detail": "record", "record": "record", "show": "record", "profile": "record",
}

# A surface that shows many records. Kanban and Calendar qualify — they are
# lists with an opinion about layout, not a different job.
_LIST_TYPES = frozenset({
    "Table", "TableSortable", "DataGrid", "List", "Kanban", "Calendar",
    "CalendarWeek", "Timeline", "ResourceTimeline", "Repeat", "CardGrid",
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


def _finding(rule: str, route: str, slot: str, detail: str) -> dict:
    return {"rule": rule, "route": route, "slot": slot,
            "severity": "error", "action": "reported", "detail": detail}


def page_kind_findings(kind: Any, route: str, doc: Any) -> list[dict]:
    """Everything this page kind promises and this page does not deliver.

    An empty list means the page does its job. A kind with no family — auth,
    static — always returns empty: silence here means "not my rule", never
    "checked and fine".
    """
    family = page_family(kind)
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
        if not (types & _ACTION_TYPES):
            out.append(_finding(
                "form_no_submit", route, "submit",
                "a form with no submit cannot deliver what it collected."))

    return out


__all__ = ["page_kind_findings", "page_family",
           "_LIST_TYPES", "_BODY_TYPES", "_FIELD_TYPES", "_ACTION_TYPES"]
