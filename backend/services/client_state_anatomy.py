"""What a screen's own values must add up to.

`clientState` (Blueprint `PageLayout.clientState`) declares values that live on
the screen while someone works and are never written down. `clientAction` on a
control changes them. Together they are how a calculator, a converter or a
scratch tool is described — and how a server-backed form computes a total
before it submits one.

WHY A FLOOR AT ALL. Asked for "a simple arithmetic calculator that does not
store the values", the pipeline had no word for a value that is not a column,
so it invented an entity to hold the display, made every key a server workflow
against a row nothing ever created, and shipped a screen where no key did
anything. Every stage was individually correct. Nothing checked whether the
page, assembled, could work.

These findings are that check. They are internal-consistency questions — does
this target exist, does this control do anything — so they hold for any page,
not only for the tool-shaped ones. `_floor_findings` reports them, the composer
is re-run with them as feedback, and the run corrects itself rather than
shipping a screen that cannot work.
"""
from __future__ import annotations

from typing import Any

#: What a control may do. A button with none of these is inert: it renders,
#: it depresses, and the person pressing it learns nothing. `onClick` is here
#: because the schema renderer can carry a nav descriptor through it.
DOES_SOMETHING = (
    "clientAction", "workflow", "navigate", "submit", "opensDialog",
    "onClick", "togglesSidebar", "clearsFilters", "href",
)

#: Node types that are controls — the things a person presses. A Form's own
#: submit is checked through its button, so Form is not here.
CONTROL_TYPES = frozenset({"Button", "IconButton", "MenuItem", "Link"})

#: How a binding names a screen value. Kept in step with
#: :data:`services.a2ui_to_forge.CLIENT_STATE_ROOT`, which is the same word on
#: the other side of the same contract.
STATE_ROOT = "state"


def _finding(rule: str, route: str, slot: str, detail: str) -> dict:
    return {"rule": rule, "route": route, "slot": slot,
            "severity": "error", "action": "reported", "detail": detail}


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for child in node.get("children") or []:
            yield from _walk(child)
    elif isinstance(node, list):
        for child in node:
            yield from _walk(child)


def declared(schema: dict) -> set[str]:
    """The names this page says it keeps on screen."""
    out: set[str] = set()
    for value in schema.get("clientState") or []:
        if isinstance(value, dict) and value.get("name"):
            out.add(str(value["name"]))
    return out


def _actions(root: Any) -> list[tuple[dict, dict]]:
    """Every (node, clientAction) pair in the tree."""
    out: list[tuple[dict, dict]] = []
    for node in _walk(root):
        action = (node.get("props") or {}).get("clientAction")
        if isinstance(action, dict):
            out.append((node, action))
    return out


def _reads(root: Any, name: str) -> bool:
    """Does anything on this page show the value, or compute from it?

    Both count. A digit key reading `display` to append to it is a read, and so
    is the Text that shows the result — a value written by three keys and shown
    nowhere is the same dead end as a display bound to nothing.
    """
    needle = "{{" + STATE_ROOT + "." + name
    for node in _walk(root):
        for value in (node.get("props") or {}).values():
            if isinstance(value, str) and needle in value:
                return True
    for _node, action in _actions(root):
        if action.get("kind") == "compute" and name in str(action.get("formula") or ""):
            return True
    return False


def client_state_findings(route: str, schema: Any) -> list[dict]:
    """Everything the screen's own values promise and this page does not keep.

    Empty for every page that declares none and authors none, which is every
    server-backed page this platform has ever built.
    """
    if not isinstance(schema, dict):
        return []
    root = schema.get("root")
    names = declared(schema)
    actions = _actions(root)
    if not names and not actions:
        return []

    out: list[dict] = []

    # A CONTROL WRITING SOMEWHERE THAT DOES NOT EXIST. The mirror of a dangling
    # binding: `{{state.total}}` with no `total` declared is already refused,
    # and a key writing to an undeclared `total` is the same fault authored
    # from the other end — it fails silently, because writing a value nobody
    # declared changes nothing anyone can see.
    for node, action in actions:
        target = str(action.get("target") or "")
        if target and target not in names:
            out.append(_finding(
                "client_action_target_undeclared", route,
                str(node.get("id") or node.get("type") or "control"),
                f"a control writes to '{target}', which this page does not "
                f"declare in clientState — declare it, or write to one of: "
                + (", ".join(sorted(names)) or "(nothing is declared)")))

    # A VALUE NOBODY EVER SEES. Declared, perhaps written, and bound by no
    # control and no display: the page keeps a number in its head and shows a
    # blank. Reported per value so the composer knows which one to surface.
    for name in sorted(names):
        if not _reads(root, name):
            out.append(_finding(
                "client_state_never_read", route, name,
                f"'{name}' is declared but nothing on the page reads it — "
                f"bind it as {{{{{STATE_ROOT}.{name}}}}} somewhere a person "
                f"can see, or drop the declaration"))

    return out


def tool_findings(route: str, schema: Any) -> list[dict]:
    """The floor for a screen that is not about the application's records.

    A self-contained tool has no data sources by definition, so every floor
    keyed on records passes it silently — which is how a calculator whose keys
    did nothing cleared every check there was. What a tool owes its user is
    narrower and checkable: values of its own, and controls that change them.
    """
    if not isinstance(schema, dict):
        return []
    root = schema.get("root")
    controls = [n for n in _walk(root) if n.get("type") in CONTROL_TYPES]
    if not controls:
        # Judged elsewhere: a page with nothing to press is a reading dead end
        # whatever family it belongs to, and `page_kind_findings` says so.
        return []

    out: list[dict] = []
    # NOT "no clientState AND no dataSources". The screen that shipped had a
    # data source: the pipeline invented a `CalculatorSession` table, made the
    # display a column of it, and every key a workflow writing to a row nothing
    # created. Data sources are exactly what a self-contained tool does not
    # need, so accepting them in place of screen values excuses the defect
    # this floor exists to catch.
    #
    # `is_standalone` is narrow — no declared pattern AND no entity on the
    # contract — so this asks a screen with no records to show to keep
    # something of its own, which is the only thing it can be made of.
    if not schema.get("clientState"):
        out.append(_finding(
            "tool_has_no_values", route, "clientState",
            "this screen is a self-contained tool and declares no values of "
            "its own, so its controls have nothing to change. Declare what it "
            "keeps on screen in `clientState` — a calculator's display, a "
            "converter's input and result — and give each control a "
            "`clientAction` that sets or computes one of them. Do not reach "
            "for an entity, a table or a workflow: nothing here is stored"))

    inert = [n for n in controls
             if not any((n.get("props") or {}).get(p) for p in DOES_SOMETHING)]
    if inert and len(inert) == len(controls):
        out.append(_finding(
            "tool_controls_are_inert", route, "action",
            f"none of this screen's {len(controls)} controls do anything: no "
            "clientAction, no workflow, no navigation. A tool whose buttons "
            "are decoration is not a tool"))

    return out


__all__ = ["client_state_findings", "tool_findings", "declared",
           "DOES_SOMETHING", "CONTROL_TYPES", "STATE_ROOT"]
