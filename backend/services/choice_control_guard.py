"""Post-generate guard: an either/or choice must be a control that holds a value.

Symptom (UAT F&B, /order). "Dine-in" and "Delivery" were two plain Buttons
side by side with no action: pressing one changed nothing a person could see
(no selected state, no field appearing) and held no value for the order to
send. The page review pressed it and reported "no navigation, no request, no
visible change". The build had no notion of a choice, so it could neither
write one nor tell one from a dead button.

This finds a group of SIBLING buttons that do nothing (no workflow, navigate,
clientAction, ...) and read as options of one choice (2-4 short labels), on a
page with a Form, and repairs the group into a ``choice`` field of that Form:

  * the buttons are removed, the Form gains a first field ``{kind: "choice",
    name, options}`` -- segmented buttons with a visible selected state, the
    first option selected on load, its value submitted with the form;
  * every other field of the Form that belongs to exactly one option (a table
    field with "Dine-in", an address field with "Delivery") gets
    ``interaction.visibleIf`` on the choice, so picking an option shows what
    it needs and hides what it does not.

The choice gets a MEANINGFUL name and label from its option family (``orderType``
"Dine-in or Delivery", ``billingPeriod`` "Billing period", ``gender`` "Gender" ...).

TRADE-OFF, stated: a field that exists for only one option (Dine-in's table number,
Delivery's address) is shown only for that option, so it cannot be required of
every order - the guard makes both NOT required server-side. The form can no
longer insist on a table number for a dine-in order; a rule that does can be added.

The choice is carried into the form's workflow only where it can be saved: an
optional input and a ``values`` mapping when the record's column is CONFIRMED in
the schema on disk; when the column is absent or cannot be read, only the form field
and the optional input are added and a named finding says it is collected but not
saved. When the page has no Form to carry the value, nothing is guessed: a warning
names page and buttons, and it reaches the guard verdict. Idempotent (once
converted there are no inert sibling buttons) and never raises.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
from typing import Any

from services.component_nodes import components
from services.guard_io import read_raw, write_like

logger = logging.getLogger(__name__)

# What makes a button "do something" (client_state_anatomy.DOES_SOMETHING).
_DOES = ("clientAction", "workflow", "navigate", "submit", "opensDialog", "onClick",
         "togglesSidebar", "clearsFilters", "href", "action")
_BUTTONS = {"button", "togglebutton", "actionbutton"}

#: POSITIVE EVIDENCE that sibling buttons are the options of ONE choice: every
#: label belongs to the same family of mutually exclusive answers. Buttons that
#: merely sit beside a form (Cancel / Save, Yes / No, Previous / Next, tabs) are
#: not choices and are never converted.
_FAMILIES = (
    ({"dine-in", "dine in", "dinein", "eat in", "delivery", "takeaway", "take away", "take-out", "takeout", "pickup",
      "pick up", "pick-up", "collection", "curbside"}, "orderType", None),
    ({"one-time", "one time", "onetime", "recurring", "monthly", "yearly", "annual", "annually", "weekly", "daily",
      "quarterly"}, "billingPeriod", "Billing period"),
    ({"male", "female", "other", "non-binary", "nonbinary", "prefer not to say"}, "gender", "Gender"),
    ({"personal", "business", "individual", "company", "organisation", "organization"}, "accountType", "Account type"),
    ({"in person", "in-person", "online", "remote", "virtual", "hybrid"}, "meetingMode", "Meeting mode"),
    ({"cash", "card", "bank transfer", "upi", "wallet"}, "paymentMethod", "Payment method"),
)
#: Words of ACTION: a button saying one of these does something, whatever sits next to it.
_ACTION_WORDS = frozenset("""cancel save submit ok okay yes no previous prev next back delete remove edit add close confirm
apply reset clear + - view details open done continue finish skip retry undo redo send create update search filter
export import print share download upload login logout sign""".split())


def _family(labels: list[str]) -> tuple | None:
    low = [re.sub(r"\s+", " ", l.strip().lower()) for l in labels]
    return next((f for f in _FAMILIES if all(l in f[0] for l in low)), None)


def _family_of(labels: list[str]) -> bool:
    return _family(labels) is not None


def _name_and_label(labels: list[str], taken: set) -> tuple[str, str]:
    """A meaningful field name and label from the option family."""
    fam = _family(labels)
    base = fam[1] if fam else "choice"
    label = fam[2] if fam and fam[2] else " or ".join(labels)
    name = base
    i = 2
    while name in taken:
        name = f"{base}{i}"
        i += 1
    return name, label


def _is_action_label(label: str) -> bool:
    words = re.split(r"[^a-z+\-]+", label.strip().lower())
    return any(w in _ACTION_WORDS for w in words if w)

# Words that tie a field to one option when the option's own words are absent.
_ALIASES = {
    "dine": {"table", "seat", "seating", "guests", "covers"},
    "delivery": {"address", "street", "city", "postcode", "zip", "apartment", "driver", "instructions"},
    "pickup": {"pickup", "collection"},
}


def _canon(s: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _words(s: Any) -> set[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(s or ""))
    return {w for w in re.split(r"[^a-z0-9]+", spaced.lower()) if len(w) > 2}


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "option"


def _props(n: dict) -> dict:
    return n.get("props") if isinstance(n.get("props"), dict) else {}


def _is_inert_button(n: Any) -> bool:
    if not isinstance(n, dict) or _canon(n.get("type")) not in _BUTTONS:
        return False
    p = _props(n)
    if not isinstance(p.get("label"), str) or not p["label"].strip():
        return False
    if len(p["label"].split()) > 3 or p.get("variant") in ("destructive", "danger"):
        return False
    for holder in (n, p):
        for k in _DOES:
            if holder.get(k):
                return False
    return True


def _walk(n: Any):
    """Component nodes only; a record with a `type` column is data."""
    return components(n)


def _choice_groups(root: Any) -> list[tuple[dict, list[dict]]]:
    """(parent, [option buttons]) for each run of 2-4 inert sibling buttons."""
    out = []
    for parent in _walk(root):
        kids = parent.get("children")
        if not isinstance(kids, list):
            continue
        run: list[dict] = []
        for k in kids + [None]:
            if _is_inert_button(k):
                run.append(k)
                continue
            labels = [_props(b)["label"].strip() for b in run]
            if 2 <= len(run) <= 4 and len({l.lower() for l in labels}) == len(run) \
                    and not any(_is_action_label(l) for l in labels) and _family_of(labels):
                out.append((parent, run))
            run = []
    return out


def _prune_empty(root: Any, emptied: list) -> None:
    """Take away the layout containers the conversion left with no children."""
    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        kids = node.get("children")
        if isinstance(kids, list):
            for k in list(kids):
                walk(k)
            node["children"] = [k for k in kids if not any(k is e for e in emptied) or k.get("children")]
    walk(root)


def _find_workflow(output_dir: str, ref: str) -> str | None:
    want = _canon(ref)
    for rel in (("workflows",), ("src", "lib", "workflows", "definitions")):
        for fp in sorted(glob.glob(os.path.join(output_dir, *rel, "*.json"))):
            try:
                d = json.loads(read_raw(fp))
            except (OSError, ValueError):
                continue
            if isinstance(d, dict) and want in {_canon(d.get("id")), _canon(d.get("name")), _canon(os.path.basename(fp)[:-5])}:
                return fp
    return None


def _mutation_nodes(node: Any):
    if isinstance(node, dict):
        if str(node.get("actionType") or "").lower() in ("db_insert", "db_update", "insert", "update") \
                and isinstance(node.get("values"), dict):
            yield node
        for v in node.values():
            yield from _mutation_nodes(v)
    elif isinstance(node, list):
        for v in node:
            yield from _mutation_nodes(v)


def _carry_into_workflow(output_dir: str, wf_ref: str, name: str, gated: list[str], rel: str, report: dict) -> None:
    """The choice reaches the workflow: an optional input, a saved column when
    the record has one (a named finding when it does not), and the fields the
    choice hides stop being required server-side."""
    fp = _find_workflow(output_dir, wf_ref)
    if fp is None:
        return
    raw = read_raw(fp)
    doc = json.loads(raw)
    before = json.dumps(doc, sort_keys=True)
    if isinstance(doc.get("inputs"), list) and not any(isinstance(i, dict) and i.get("name") == name for i in doc["inputs"]):
        doc["inputs"].append({"name": name, "kind": "field", "type": "string", "required": False})
    if isinstance(doc.get("requiredInputs"), list):
        doc["requiredInputs"] = [r for r in doc["requiredInputs"] if r != name and r not in gated]
    for i in doc.get("inputs") or []:
        if isinstance(i, dict) and i.get("name") in gated:
            i["required"] = False
    from services.binding_validator import _read_schema_tables
    tables = {str(t["arg"]).lower(): t["columns"] for t in _read_schema_tables(output_dir)}
    for node in _mutation_nodes(doc):
        if name in node["values"]:
            continue
        cols = tables.get(str(node.get("table") or "").lower())
        if cols is None or (name not in cols and _canon(name) not in {_canon(c) for c in cols}):
            why = (f"the choice {name!r} has no column on {node.get('table')}" if cols is not None
                   else f"the column for {name!r} on {node.get('table')} could not be confirmed (no schema on disk)")
            report["findings"].append({"page": rel, "buttons": [], "workflow": wf_ref, "choice": name,
                                       "detail": f"{why}, so it is collected but not saved - add the column or say where it goes"})
            logger.warning("choice_control_guard: %s: %s; it is not saved", rel, why)
            continue
        node["values"][name] = "{{" + name + "}}"
    if json.dumps(doc, sort_keys=True) != before:
        write_like(fp, raw, doc)


def _form_of(root: Any) -> dict | None:
    return next((n for n in _walk(root) if _canon(n.get("type")) == "form"
                 and isinstance(_props(n).get("fields"), list)), None)


def _option_for(field: dict, options: list[dict]) -> str | None:
    """The one option this field belongs to, or None (belongs to all / unsure)."""
    fw = _words(field.get("name")) | _words(field.get("label"))
    hits = []
    for o in options:
        ow = _words(o["label"]) | _words(o["value"])
        keys = {w for w in ow}
        for stem, aliases in _ALIASES.items():
            if any(w.startswith(stem) for w in ow):
                keys |= aliases | {stem}
        if fw & keys:
            hits.append(o["value"])
    return hits[0] if len(hits) == 1 else None


def ensure_choices_are_controls(output_dir: str) -> dict:
    """Turn inert either/or button groups into a Form ``choice`` field.

    Returns ``{"converted": [{page, name, options}], "findings": [{page, buttons}]}``.
    Never raises.
    """
    report: dict = {"converted": [], "findings": []}
    try:
        sdir = os.path.join(str(output_dir), "src", "schemas")
        if not os.path.isdir(sdir):
            return report
        for fp in sorted(glob.glob(os.path.join(sdir, "**", "*.json"), recursive=True)):
            if os.path.basename(fp) in ("shell.json", "nav-flow.json"):
                continue
            try:
                raw = read_raw(fp)
                page = json.loads(raw)
            except (OSError, ValueError) as exc:
                logger.warning("choice_control_guard: cannot read %s: %s", fp, exc)
                continue
            if not isinstance(page, dict):
                continue
            rel = os.path.relpath(fp, sdir).replace(os.sep, "/")
            root = page.get("root")
            groups = _choice_groups(root)
            if not groups:
                continue
            form = _form_of(root)
            dirty = False
            emptied: list = []
            for parent, buttons in groups:
                labels = [_props(b)["label"].strip() for b in buttons]
                if form is None:
                    report["findings"].append({"page": rel, "buttons": labels})
                    logger.warning(
                        "choice_control_guard: %s: %s do nothing when pressed and the page has no "
                        "form to hold a choice - make them a choice field of a Form (kind: \"choice\") "
                        "or give each an action", rel, " / ".join(repr(l) for l in labels))
                    continue
                fields = _props(form)["fields"]
                taken = {f.get("name") for f in fields if isinstance(f, dict)}
                name, choice_label = _name_and_label(labels, taken)
                options = [{"value": _slug(l), "label": l} for l in labels]
                for f in fields:
                    if isinstance(f, dict) and not (isinstance(f.get("interaction"), dict)
                                                    and f["interaction"].get("visibleIf")):
                        opt = _option_for(f, options)
                        if opt and f.get("kind") != "choice":
                            f.setdefault("interaction", {})["visibleIf"] = f"{name} == '{opt}'"
                gated = [f["name"] for f in fields if isinstance(f, dict) and isinstance(f.get("interaction"), dict)
                         and name in str(f["interaction"].get("visibleIf") or "") and f.get("name")]
                fields.insert(0, {"kind": "choice", "name": name, "label": choice_label, "options": options})
                parent["children"] = [c for c in parent["children"] if all(c is not b for b in buttons)]
                if not parent["children"]:
                    emptied.append(parent)
                wf_ref = _props(form).get("workflow")
                if isinstance(wf_ref, str) and wf_ref:
                    _carry_into_workflow(str(output_dir), wf_ref, name, gated, rel, report)
                dirty = True
                report["converted"].append({"page": rel, "name": name, "options": labels})
                logger.info("choice_control_guard: %s: %s became the %r choice of its form",
                            rel, " / ".join(labels), name)
            if dirty:
                _prune_empty(root, emptied)
                write_like(fp, raw, page)
    except Exception:  # noqa: BLE001 — never block generation
        logger.exception("choice_control_guard: internal error (degrading to no-op)")
    return report
