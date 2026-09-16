"""The move — the one step in a turn that changes the application.

Two moves: a RENAME (the label becomes another label) and a REMOVAL (the
label goes, with the control it names). Understanding encodes a removal as
a rename with an empty `new_value` — and this function used to answer that
with None, which `run_iteration` reported as "I looked for X and could not
find it". It had not looked. "Remove the delete button" on a list whose
Delete was a Table row action got that reply twice, once with the exact
text.

A REMOVAL IS A CONTRACT CHANGE, NOT A TREE EDIT. The page declares what it
offers (`actions: [.., "delete"]`) and the completeness rules demand a
control for every declared action — so a Delete cut from the tree alone
comes back on the next Verify & Fix, and the workflow it ran stays
"launched from" the page, which is the composer's cue to bind it again.
The removal therefore retracts the verb the control served from the page's
`actions` and takes the page off the workflow's `launchedFrom` when nothing
on the page runs it any more. What the user asked for — "this screen no
longer deletes" — is then what the Blueprint says.

`run_iteration` does not trust this function, and is right not to: it snapshots
git before calling, then asks git what actually changed and fails the turn
unless the diff mentions `element_label` and `target_file` is among the
modified files. So this returns a LABEL for what it intended, never a report of
what it did.

BLUEPRINT FIRST. A rename changes the `pageLayouts` artifact and re-projects;
it does not patch the generated file. §115 makes the Blueprint the source and
the implementation derived, and editing generated files directly is precisely
what makes the legacy pipeline's Blueprint a post-hoc record of whatever the
code happened to become. The verification still passes honestly — the
projection writes `target_file`, so the diff git sees is the real one.

Deterministic, and no model call. `understand_ask` already decided where, what
and what to write; a second model here would be a second opinion about a
question that has already been answered, and a place for the two to disagree.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

#: Props that hold text a person can see and therefore name. `label` is a
#: Button's, `content` a Text's or Heading's or Badge's, `title` a Section's.
#: A prop not in this set is not something anyone would call "the Add plant
#: button" — an `href` matching by accident would edit the wrong thing.
_TEXT_PROPS = ("label", "content", "title", "text", "heading", "placeholder")


def _route_matches(route: str, target: str) -> bool:
    """Whether a page's route is what `target_file` was pointing at.

    Understanding returns a route (`/plants`) or a schema path
    (`src/schemas/plants.json`), depending on what the Blueprint slice showed
    it. Both name the same page, and refusing one of them would turn a good
    understanding into a no-op.
    """
    route, target = (route or "").strip(), (target or "").strip()
    if not route or not target:
        return False
    if route == target:
        return True
    # `/plants/[id]` -> `plants/[id]`, which appears in `src/schemas/...`.
    return route.strip("/") and route.strip("/") in target


def _labelled(control: Any, label: str) -> bool:
    """A control inside a prop — a Table row action, a Card action, an
    empty-state action — is named by its `label` the way a Button is."""
    return isinstance(control, dict) and isinstance(control.get("label"), str) \
        and control["label"].strip() == label


def _named(node: Any, label: str) -> bool:
    """A node a person would call by `label`: one of its visible text props is it."""
    if not isinstance(node, dict):
        return False
    props = node.get("props")
    return isinstance(props, dict) and any(
        isinstance(props.get(key), str) and props[key].strip() == label for key in _TEXT_PROPS)


def _retitle(node: Any, label: str, new_value: str) -> int:
    """Set every visible text prop equal to `label` to `new_value`. Count them.

    Counted rather than stopped at the first, because a label can legitimately
    appear twice — a button in a header and the same button in an empty state —
    and renaming one of them is the bug a user would report next. Reaches the
    controls that live INSIDE a prop too (`rowActions[].label`): "rename the
    Delete row action" names something as real as a Button.
    """
    if isinstance(node, list):
        return sum(_retitle(n, label, new_value) for n in node)
    if not isinstance(node, dict):
        return 0

    hits = 0
    props = node.get("props")
    if isinstance(props, dict):
        for key in _TEXT_PROPS:
            if isinstance(props.get(key), str) and props[key].strip() == label:
                props[key] = new_value
                hits += 1
        for val in props.values():
            for control in (val if isinstance(val, list) else [val]):
                if _labelled(control, label) and control is not props:
                    control["label"] = new_value
                    hits += 1
    return hits + _retitle(node.get("children") or [], label, new_value)


def _remove(node: Any, label: str) -> list[dict]:
    """Cut every control named `label` out of the tree, in place. Returns the
    controls removed (a node's props, or the row-action / action entry itself)
    so the caller can see what each was bound to."""
    removed: list[dict] = []
    if isinstance(node, list):
        keep = []
        for n in node:
            if _named(n, label):
                removed.append(dict(n.get("props") or {}))
            else:
                removed.extend(_remove(n, label))
                keep.append(n)
        node[:] = keep
        return removed
    if not isinstance(node, dict):
        return removed
    props = node.get("props")
    if isinstance(props, dict):
        for key, val in list(props.items()):
            if isinstance(val, list) and val and all(isinstance(v, dict) for v in val):
                gone = [v for v in val if _labelled(v, label)]
                if gone:
                    removed.extend(gone)
                    kept = [v for v in val if not _labelled(v, label)]
                    if kept:
                        props[key] = kept
                    else:
                        del props[key]          # an empty list is not "no row actions" to every schema
            elif isinstance(val, dict) and _labelled(val, label) and ("workflow" in val or "navigate" in val):
                removed.append(val)
                del props[key]
    removed.extend(_remove(node.get("children") or [], label))
    return removed


#: The verbs a control serves, by what it runs — the page contract's own
#: vocabulary (`actions: ["delete", "edit_record", "create"]`, matched on
#: the first token, as `declare_capabilities` matches it).
_OP_VERBS: dict[str, tuple[str, ...]] = {
    "db_delete": ("delete", "remove"),
    "db_update": ("edit", "update", "save"),
    "db_insert": ("create", "add", "new", "submit", "register"),
}

_ROUTE_HOLE = re.compile(r"\[[^\]]+\]|\{\{[^}]+\}\}")


def _same_route(a: str, b: str) -> bool:
    """`/nurses/{{id}}` navigates to the page at `/nurses/[id]`."""
    norm = lambda r: _ROUTE_HOLE.sub("*", str(r or "").split("?")[0].strip()).rstrip("/") or "/"
    return norm(a) == norm(b)


def _served_verbs(doc: dict, control: dict) -> set[str]:
    """Which declared verbs `control` was the page's control FOR."""
    from services.blueprint.functional_completeness import page_family
    verbs: set[str] = set()
    wf_id = control.get("workflow")
    if isinstance(wf_id, str) and wf_id:
        for w in doc.get("workflows") or []:
            if str(w.get("id")) == wf_id:
                for st in w.get("steps") or []:
                    verbs.update(_OP_VERBS.get(str((st.get("config") or {}).get("actionType") or ""), ()))
    nav = control.get("navigate")
    if isinstance(nav, str) and nav:
        for p in doc.get("pages") or []:
            if p.get("status") == "DEPRECATED" or not _same_route(nav, str(p.get("route") or "")):
                continue
            fam = page_family(dict(p))
            if fam == "form":
                verbs.update(("edit", "update") if "[" in str(p.get("route") or "") else ("create", "add", "new"))
            elif fam == "record":
                verbs.update(("view", "open"))
    return verbs


def _still_runs(root: Any, wf_id: str) -> bool:
    def walk(n: Any) -> bool:
        if isinstance(n, list):
            return any(walk(c) for c in n)
        if not isinstance(n, dict):
            return False
        props = n.get("props")
        if isinstance(props, dict):
            if props.get("workflow") == wf_id:
                return True
            for val in props.values():
                for c in (val if isinstance(val, list) else [val]):
                    if isinstance(c, dict) and c.get("workflow") == wf_id:
                        return True
        return walk(n.get("children") or [])
    return walk(root)


def _retract(doc: dict, page: dict, layout: dict, removed: list[dict]) -> list[str]:
    """The contract after the controls are gone: the page stops declaring the
    verbs they served, and a workflow nothing on the page runs any more is
    no longer launched from it. Returns what was retracted, for the reply."""
    notes: list[str] = []
    verbs: set[str] = set()
    for c in removed:
        verbs |= _served_verbs(doc, c)
    before = [a for a in (page.get("actions") or []) if isinstance(a, str)]
    kept = [a for a in before if a.lower().split("_")[0] not in verbs]
    if kept != before:
        page["actions"] = kept
        notes.append("the page no longer declares " + ", ".join(a for a in before if a not in kept))
    pid = str(page.get("id") or "")
    for c in removed:
        wf_id = c.get("workflow")
        if not isinstance(wf_id, str) or _still_runs(layout.get("root"), wf_id):
            continue
        for w in doc.get("workflows") or []:
            if str(w.get("id")) == wf_id and pid in (w.get("launchedFrom") or []):
                w["launchedFrom"] = [x for x in w["launchedFrom"] if x != pid]
                notes.append(f"{w.get('name') or wf_id} is no longer launched from it")
    return notes


def move_dispatcher(
    understanding: dict[str, Any], output_dir: str
) -> Optional[Any]:
    """(understanding, output_dir) -> IterationMove, or None when nothing matched.

    None is a real answer and `run_iteration` treats it as one: it returns
    `no_op` and says the current state already matches. That is the honest
    result when a label cannot be found — better than editing the nearest thing
    and reporting success.
    """
    from services.blueprint.projection import apply_frontend_projection
    from services.blueprint.service import BlueprintService
    from services.smith_session import IterationMove

    label = str(understanding.get("element_label") or "").strip()
    new_value = str(understanding.get("new_value") or "").strip()
    target = str(understanding.get("target_file") or "").strip()

    # Nothing named is nothing to find. An empty `new_value` is a REMOVAL —
    # that is how understanding encodes one — not a request with nothing in it.
    if not label:
        return None
    removing = not new_value

    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return None

    pages = {p.get("id"): p for p in (svc.doc.get("pages") or [])
             if isinstance(p, dict)}
    changed: list[str] = []
    notes: list[str] = []

    for layout in svc.doc.get("pageLayouts") or []:
        if not isinstance(layout, dict) or layout.get("status") in ("SUPERSEDED", "DEPRECATED"):
            continue
        page = pages.get(layout.get("page")) or {}
        # An unmatched target scopes to nothing rather than to everything: a
        # rename that cannot find its page must not rewrite the whole app.
        if target and not _route_matches(str(page.get("route") or ""), target):
            continue
        if removing:
            removed = _remove(layout.get("root"), label)
            if not removed:
                continue
            notes.extend(_retract(svc.doc, page, layout, removed))
        elif not _retitle(layout.get("root"), label, new_value):
            continue
        svc.upsert("pageLayouts", layout, natural_key=str(layout["page"]))
        changed.append(str(layout["page"]))

    if not changed:
        return None

    svc.save()
    # The projection is what writes `target_file`, which is what git will show
    # and what `run_iteration` verifies against.
    result = apply_frontend_projection(svc, str(Path(output_dir) / "app"))
    touched = [str(f) for f in (result or {}).get("files", [])]

    if removing:
        name = f"remove {label!r} from {', '.join(changed)}"
        if notes:
            name += " (" + "; ".join(notes) + ")"
    else:
        name = f"rename {label!r} to {new_value!r} on {', '.join(changed)}"
    return IterationMove(move_name=name, touched_paths=touched)
