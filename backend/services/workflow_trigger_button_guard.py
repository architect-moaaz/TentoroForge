"""Post-generate guard: neutralize buttons that dispatch an EVENT-ONLY workflow.

Issue #6. A generated page carries a manual-looking Button — e.g. "Run Full
Compliance Check" with `props.workflow: "regulatorycompliancecheckworkflow"` —
but that workflow's trigger is `api_event` / `db_change` / `schedule`. Those
workflows are *event-driven*: they fire automatically off a record change (or a
clock) and expect the changed record as their context. A page-level button has
no such record to hand over, so clicking it dispatches an EMPTY payload and the
workflow does nothing (or crashes on a NOT-NULL access). The user clicks and
nothing happens.

`button_audit` does NOT cover this — the workflow exists and the ref resolves;
it's simply the wrong *kind* of trigger for a bare button. So this guard:

  * Reads every `workflows/*.json` trigger type (manual vs event-driven).
  * Walks each page schema for component nodes carrying a `workflow` ref
    (`props.workflow` / `action.workflow` / `onClick.workflow` / a direct
    `workflow` key on a button node).
  * If the referenced workflow is NON-manual AND the button has NO record
    context, the button can't work → NEUTRALIZE it (prefer removing the node;
    fall back to stripping the workflow prop + disabling when it can't be
    removed cleanly).

Record context is treated as PRESENT (→ leave the button alone) when:
  * the page is a record-detail route (path contains a `[param]` segment), or
  * the button sits inside a per-row container (a `rowActions`/`itemActions`
    list, or the children of a Table/Repeat/List that renders records).

Deliberately CONSERVATIVE: manual-trigger workflow buttons are untouched, and
whenever record context is ambiguous the button is LEFT (a possibly-valid button
beats an over-eager deletion). Idempotent (a re-run finds nothing to remove) and
never raises.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

# A trigger type that fires the workflow automatically from a record/clock event
# rather than an explicit user click. A bare button cannot supply the context
# these expect, so a button wired to one of them is dead.
# Trigger types that fire WITHOUT a user — a button bound to one of these can
# never do anything, which is what this guard neutralises.
#
# `timer` was missing (register TB-2). It is a first-class trigger type in the
# runtime's own union (`types.ts`: manual | api_event | schedule | webhook |
# db_change | user_input | timer), so a timer-triggered workflow was treated as
# manual and its dead button was left on the page looking clickable.
_EVENT_TRIGGERS = {"db_change", "dbchange", "api_event", "apievent", "schedule",
                   "scheduled", "cron", "webhook", "event", "timer"}
_MANUAL_TRIGGERS = {"manual", "button", "user", ""}

# Node types that behave like a clickable control carrying a workflow dispatch.
_BUTTON_TYPES = {
    "button", "iconbutton", "actionbutton", "fab", "linkbutton", "menubutton",
    "splitbutton", "togglebutton", "menuitem", "dropdownitem",
}
# Containers whose child rows each supply their own record — a workflow button
# inside one of these DOES get a record context, so leave it be.
_ROW_CONTAINER_TYPES = {
    "table", "datatable", "datagrid", "repeat", "list", "datalist", "cardlist",
    "listview", "itemlist", "recordlist", "resourcetimeline",
}
# Object keys that hold per-row actions (a record context comes with each row).
_ROW_CTX_KEYS = {
    "rowactions", "rowaction", "itemactions", "cardactions", "rowtemplate",
    "itemtemplate", "columns", "cell", "cells",
}
# Where a button may carry its workflow ref.
_WF_CARRIERS = ("workflow",)


def _canon(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def build_trigger_index(output_dir: str) -> dict[str, str]:
    """canon(workflow id/name/filename-stem) -> trigger type (lowercased).

    Mirrors the runtime cache keys (id + name), plus the filename stem, so a
    button ref in any of those casings resolves. Best-effort; a bad file is
    skipped rather than fatal.
    """
    wf_dir = os.path.join(str(output_dir), "workflows")
    idx: dict[str, str] = {}
    if not os.path.isdir(wf_dir):
        return idx
    for fn in sorted(os.listdir(wf_dir)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(wf_dir, fn), encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:  # noqa: BLE001 — a bad file must not break the pipeline
            continue
        if not isinstance(d, dict):
            continue
        ttype = _extract_trigger_type(d)
        for key in (d.get("name"), d.get("id"), fn[:-5]):
            if key and isinstance(key, str):
                idx.setdefault(_canon(key), ttype)
    return idx


def _extract_trigger_type(wf: dict) -> str:
    """Pull the trigger type from a workflow doc, tolerating shape variants."""
    defn = wf.get("definition") if isinstance(wf.get("definition"), dict) else wf
    trig = defn.get("trigger") if isinstance(defn.get("trigger"), dict) else None
    if isinstance(trig, dict) and trig.get("type"):
        return str(trig["type"]).strip().lower()
    for key in ("triggerType", "trigger_type"):
        if defn.get(key):
            return str(defn[key]).strip().lower()
        if wf.get(key):
            return str(wf[key]).strip().lower()
    if isinstance(trig, str):
        return trig.strip().lower()
    return ""


def _is_event_only(trigger_type: str) -> bool:
    t = _canon(trigger_type)
    if not t or t in {_canon(x) for x in _MANUAL_TRIGGERS}:
        return False
    return t in {_canon(x) for x in _EVENT_TRIGGERS}


def _button_workflow(node: dict) -> str | None:
    """The workflow ref a button node dispatches, from any carrier, or None."""
    for key in _WF_CARRIERS:
        v = node.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    for holder in ("props", "action", "onClick"):
        sub = node.get(holder)
        if isinstance(sub, dict):
            v = sub.get("workflow")
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


def _norm_type(node: dict) -> str:
    return _canon(node.get("type"))


def _is_button_node(node: dict) -> bool:
    return _norm_type(node) in _BUTTON_TYPES


def _neutralize_targets(node: dict, trig_idx: dict[str, str], record_ctx: bool,
                        removed: list, disabled: list, file_name: str) -> None:
    """Recurse a schema node tree, removing/disabling dead event-only buttons.

    `record_ctx` is True when the current subtree already has a record to hand a
    workflow (a detail route, or inside a per-row container).
    """
    if isinstance(node, dict):
        for key, val in list(node.items()):
            child_ctx = record_ctx or (_canon(key) in _ROW_CTX_KEYS)
            if isinstance(val, list):
                # Children of a record-rendering container each carry a record.
                list_ctx = child_ctx or (_norm_type(node) in _ROW_CONTAINER_TYPES)
                _process_list(val, trig_idx, list_ctx, removed, disabled, file_name)
                for item in val:
                    _neutralize_targets(item, trig_idx, list_ctx, removed,
                                        disabled, file_name)
            elif isinstance(val, dict):
                # A button that is a named dict value (not a list item) can't be
                # cleanly removed — strip its workflow + disable it instead.
                if _is_button_node(val):
                    wf = _button_workflow(val)
                    if wf and not child_ctx and _is_event_only(
                        trig_idx.get(_canon(wf), "")
                    ):
                        _disable_button(val, wf)
                        disabled.append((file_name, wf))
                        logger.warning(
                            "workflow_trigger_button_guard: disabled event-only "
                            "button -> %r (%s) in %s",
                            wf, trig_idx.get(_canon(wf), ""), file_name,
                        )
                _neutralize_targets(val, trig_idx, child_ctx, removed,
                                    disabled, file_name)


def _process_list(lst: list, trig_idx: dict[str, str], record_ctx: bool,
                  removed: list, disabled: list, file_name: str) -> None:
    """Drop event-only-workflow buttons from a children list (in place)."""
    keep = []
    for item in lst:
        if isinstance(item, dict) and _is_button_node(item):
            wf = _button_workflow(item)
            if wf and not record_ctx and _is_event_only(
                trig_idx.get(_canon(wf), "")
            ):
                # Delete the button ONLY when the dead workflow is all it does.
                #
                # This branch used to drop the whole node unconditionally, so a
                # button that also navigated somewhere, opened a modal or
                # carried a link lost that unrelated functionality too — the
                # guard removed working UI to clean up a dead binding. Note the
                # sibling dict path already did the right thing (_disable_button
                # strips the binding and keeps the node); that asymmetry WAS the
                # defect.
                if _has_other_function(item):
                    _disable_button(item, wf)
                    disabled.append((file_name, wf))
                    logger.warning(
                        "workflow_trigger_button_guard: stripped event-only workflow "
                        "%r (%s) from a button in %s but KEPT the node — it carries "
                        "other functionality that must not be deleted.",
                        wf, trig_idx.get(_canon(wf), ""), file_name,
                    )
                    keep.append(item)
                    continue
                removed.append((file_name, wf))
                logger.warning(
                    "workflow_trigger_button_guard: removed event-only button "
                    "-> %r (%s) in %s",
                    wf, trig_idx.get(_canon(wf), ""), file_name,
                )
                continue  # drop the dead button — it did nothing else
        keep.append(item)
    lst[:] = keep


# Keys that mean the button still DOES something once its dead workflow
# binding is stripped. Deleting such a node throws away working behaviour.
_OTHER_FUNCTION_KEYS = {
    "href", "to", "link", "route", "navigate", "navigateto", "url",
    "onclick", "action", "actions", "modal", "opens", "target", "submit",
    "dialog", "drawer", "command", "download",
}


def _has_other_function(node: dict) -> bool:
    """True when the button carries behaviour beyond the dead workflow."""
    def _scan(d: dict) -> bool:
        for k, v in d.items():
            ck = _canon(k)
            if ck in _OTHER_FUNCTION_KEYS:
                # `action`/`onClick` holding ONLY the workflow is not "other".
                if isinstance(v, dict):
                    if any(_canon(k2) != "workflow" for k2 in v):
                        return True
                    continue
                if v not in (None, "", [], {}):
                    return True
        return False

    if _scan(node):
        return True
    props = node.get("props")
    return isinstance(props, dict) and _scan(props)


def _disable_button(node: dict, wf: str) -> None:
    """Strip the workflow dispatch and mark the button disabled (no-op)."""
    node.pop("workflow", None)
    for holder in ("props", "action", "onClick"):
        sub = node.get(holder)
        if isinstance(sub, dict):
            sub.pop("workflow", None)
    props = node.get("props")
    if not isinstance(props, dict):
        props = {}
        node["props"] = props
    props["disabled"] = True


def _page_has_record_context(rel_path: str) -> bool:
    """A route with a `[param]` segment renders a single record → has context."""
    return "[" in rel_path


def neutralize_event_only_buttons(output_dir: str) -> dict:
    """Neutralize page buttons wired to event-only (non-manual) workflows.

    Returns {"removed": [...], "disabled": [...], "files": int,
    "files_scanned": int}. Loud logging per neutralization. Idempotent; a
    re-run over already-cleaned schemas is a no-op.
    """
    sdir = os.path.join(output_dir, "src", "schemas")
    removed: list = []
    disabled: list = []
    files = 0
    files_scanned = 0
    if not os.path.isdir(sdir):
        return {"removed": removed, "disabled": disabled, "files": files,
                "files_scanned": files_scanned, "asserts_logged": 0}

    trig_idx = build_trigger_index(output_dir)
    if not trig_idx:
        return {"removed": removed, "disabled": disabled, "files": files,
                "files_scanned": files_scanned, "asserts_logged": 0}

    # Phase 6b (Record Authority) — composer-authored schemas run in
    # ASSERT-only mode; composer's button choices are authority.
    from services.artifact_authority import should_assert_only_any

    asserts_logged = 0
    for fp in sorted(glob.glob(os.path.join(sdir, "**", "*.json"), recursive=True)):
        files_scanned += 1
        rel = os.path.relpath(fp, sdir)
        try:
            with open(fp, encoding="utf-8") as fh:
                page = json.load(fh)
        except (OSError, ValueError) as e:
            logger.warning("workflow_trigger_button_guard: could not parse %s: %s", rel, e)
            continue
        if not isinstance(page, dict):
            continue

        if should_assert_only_any(page):
            asserts_logged += 1
            continue

        before_removed = len(removed)
        before_disabled = len(disabled)
        record_ctx = _page_has_record_context(rel)
        _neutralize_targets(page, trig_idx, record_ctx, removed, disabled, rel)

        if len(removed) > before_removed or len(disabled) > before_disabled:
            files += 1
            try:
                with open(fp, "w", encoding="utf-8") as fh:
                    json.dump(page, fh, indent=2)
            except OSError as e:  # noqa: BLE001
                logger.warning("workflow_trigger_button_guard: could not write %s: %s", rel, e)

    return {"removed": removed, "disabled": disabled, "files": files,
            "files_scanned": files_scanned, "asserts_logged": asserts_logged}
