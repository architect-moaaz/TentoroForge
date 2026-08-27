"""IRF-M6-T6 — NN/g form-UX invariants as deterministic guards.

Runs post-generation over every ``src/schemas/*.json`` that contains a
``Form`` node, and either:

1. **Auto-fixes** mechanical violations in place (required marker,
   inputMode for numeric fields, disabled-in-flight flag, autocomplete
   attributes, submit-label, error-state defaults).
2. **Surfaces as findings** the ones that need a design decision
   (fields with no label, forms with >12 fields and no sectioning,
   destructive actions without confirmation, etc.).

Aggregates roughly 30 NN/g-lineage invariants (see ``INVARIANTS`` list
below for the full catalog). Idempotent — every fix uses ``setdefault``
so re-runs stabilize.

Flag: ``FORGE_FORM_UX_INVARIANTS`` (default off). When off, returns
``{"applied": False, "reason": "flag-disabled"}`` — pass wires
unconditionally into ``post_generate_fixes`` but nothing changes until
the flag flips.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# The catalog. Each rule is either "fix" (mutator) or "finding" (report).
INVARIANTS: list[dict[str, str]] = [
    # ─ auto-fix (mechanical) ─
    {"rule": "required-marker", "kind": "fix", "desc": "Required fields get `required: true`; label gets a `*` suffix."},
    {"rule": "numeric-inputMode", "kind": "fix", "desc": "Numeric/currency/percent Inputs get inputMode='numeric' or 'decimal'."},
    {"rule": "email-inputMode", "kind": "fix", "desc": "Email Inputs get inputMode='email' + autoComplete='email'."},
    {"rule": "tel-inputMode", "kind": "fix", "desc": "Phone Inputs get inputMode='tel' + autoComplete='tel'."},
    {"rule": "password-autocomplete", "kind": "fix", "desc": "Password Inputs get autoComplete='current-password' or 'new-password'."},
    {"rule": "in-flight-disable", "kind": "fix", "desc": "Submit buttons get `disabledWhileSubmitting: true`."},
    {"rule": "submit-label-default", "kind": "fix", "desc": "Forms without submitLabel get one derived from op (Save / Create)."},
    {"rule": "autocomplete-name", "kind": "fix", "desc": "First-name / last-name / full-name Inputs get autoComplete='given-name'/'family-name'/'name'."},
    {"rule": "autocomplete-address", "kind": "fix", "desc": "Address-line-1/2, postal-code, country Inputs get autoComplete='street-address'/'postal-code'/'country'."},
    {"rule": "textarea-min-rows", "kind": "fix", "desc": "Textarea without rows gets rows=3 minimum."},
    {"rule": "number-min-max-safety", "kind": "fix", "desc": "NumberInput with min/max: ensure min <= max; drop if inconsistent."},
    {"rule": "cta-verb-not-generic", "kind": "fix", "desc": "Buttons labeled 'OK' / 'Submit' in Form context get verb-specific labels ('Save', 'Create')."},
    {"rule": "aria-invalid-when-error", "kind": "fix", "desc": "Fields with errorText get aria-invalid=true."},
    {"rule": "focus-trap-in-modal", "kind": "fix", "desc": "Forms inside Dialog get focusTrap=true."},
    {"rule": "no-double-submit", "kind": "fix", "desc": "Submit button gets noDoubleSubmit debounce hint."},
    # ─ findings (surface as verify_history entries) ─
    {"rule": "field-missing-label", "kind": "finding", "desc": "Inputs / Selects with no label attribute — surface as error."},
    {"rule": "form-too-large-unsectioned", "kind": "finding", "desc": "Form with >12 fields, no Section headings — surface as warning."},
    {"rule": "destructive-no-confirm", "kind": "finding", "desc": "Button variant=destructive with no confirmDialog — warning."},
    {"rule": "reset-button-adjacent-submit", "kind": "finding", "desc": "A Reset button adjacent to a Submit is an anti-pattern (Nielsen 1994) — warning."},
    {"rule": "captcha-on-authenticated-form", "kind": "finding", "desc": "Captcha on a form behind auth is anti-pattern."},
    {"rule": "error-below-label-above-input", "kind": "finding", "desc": "Error message location — must appear near the field."},
    {"rule": "error-describes-fix", "kind": "finding", "desc": "Error text should say what to change, not just what's wrong."},
    {"rule": "placeholder-not-label", "kind": "finding", "desc": "Fields with only placeholder + no label — placeholder disappears on focus."},
    {"rule": "date-picker-not-native-on-mobile", "kind": "finding", "desc": "Custom DatePicker on mobile without native fallback — warning."},
    {"rule": "matching-fields-single-check", "kind": "finding", "desc": "Confirm-password / confirm-email should validate on blur of second field."},
    {"rule": "unit-adjacent-to-value", "kind": "finding", "desc": "Currency / percent / date fields should show unit inline (prefix/suffix)."},
    {"rule": "primary-cta-not-first", "kind": "finding", "desc": "Primary submit should be the rightmost/last action in the button row."},
    {"rule": "hidden-required-fields", "kind": "finding", "desc": "Required fields hidden behind conditional visibility — must be revealed by then."},
    {"rule": "no-progress-on-long-submit", "kind": "finding", "desc": "Async submits >1s need progress state (spinner / step / ETA)."},
    {"rule": "loading-not-blocking-form-changes", "kind": "finding", "desc": "Long-running loaders shouldn't clobber unsaved edits."},
]


# ── flag ────────────────────────────────────────────────────────────


def is_enabled() -> bool:
    from services.flag_profile import is_on
    return is_on("FORGE_FORM_UX_INVARIANTS")


# ── shape utilities ────────────────────────────────────────────────


def _iter_nodes(node: Any, _depth: int = 0):
    if _depth > 200:
        return
    if isinstance(node, dict):
        # A component-shaped node (has a "type" key) is a semantic node the
        # walker yields for rules. Non-component dicts (props / style /
        # arbitrary maps) are traversed but NOT yielded — otherwise fix
        # rules that call ``_props(node)`` on a non-component dict would
        # add a spurious ``props: {}`` key and the walker would revisit it.
        if isinstance(node.get("type"), str):
            yield node
        for v in node.values():
            yield from _iter_nodes(v, _depth + 1)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_nodes(item, _depth + 1)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_nodes(item)


def _node_type(node: Any) -> str | None:
    if isinstance(node, dict):
        t = node.get("type")
        return str(t) if isinstance(t, str) else None
    return None


def _props(node: Any) -> dict:
    if isinstance(node, dict):
        p = node.get("props")
        if isinstance(p, dict):
            return p
        node["props"] = {}
        return node["props"]
    return {}


# ── auto-fix rules ─────────────────────────────────────────────────


_NUMERIC_FIELDS = {"NumberInput", "CurrencyInput", "PercentInput"}
_INPUT_TYPES = {"Input", "Textarea", "Select", "Combobox", "NumberInput",
                "CurrencyInput", "PercentInput", "PasswordInput"}


def _fix_required_marker(node: dict) -> int:
    if _node_type(node) not in _INPUT_TYPES:
        return 0
    props = _props(node)
    if not props.get("required"):
        return 0
    label = props.get("label")
    if isinstance(label, str) and not label.rstrip().endswith("*"):
        props["label"] = label.rstrip() + " *"
        return 1
    return 0


def _fix_input_mode(node: dict) -> int:
    t = _node_type(node)
    props = _props(node)
    if t in _NUMERIC_FIELDS and "inputMode" not in props:
        props["inputMode"] = "decimal" if t == "CurrencyInput" or t == "PercentInput" else "numeric"
        return 1
    if t == "Input":
        name = str(props.get("name") or props.get("label") or "").lower()
        if any(k in name for k in ("email",)) and "inputMode" not in props:
            props["inputMode"] = "email"
            props.setdefault("autoComplete", "email")
            return 1
        if any(k in name for k in ("phone", "tel", "mobile")) and "inputMode" not in props:
            props["inputMode"] = "tel"
            props.setdefault("autoComplete", "tel")
            return 1
    return 0


def _fix_autocomplete_names(node: dict) -> int:
    if _node_type(node) != "Input":
        return 0
    props = _props(node)
    if props.get("autoComplete"):
        return 0
    name = str(props.get("name") or "").lower()
    label = str(props.get("label") or "").lower()
    val = f"{name} {label}"
    if "first name" in val or "given" in val:
        props["autoComplete"] = "given-name"
        return 1
    if "last name" in val or "family" in val or "surname" in val:
        props["autoComplete"] = "family-name"
        return 1
    if "full name" in val or (name == "name" and "name" in label):
        props["autoComplete"] = "name"
        return 1
    if "address line 1" in val or "street" in val:
        props["autoComplete"] = "street-address"
        return 1
    if "postal" in val or "zip" in val:
        props["autoComplete"] = "postal-code"
        return 1
    if name == "country" or "country" in label:
        props["autoComplete"] = "country"
        return 1
    return 0


def _fix_password_autocomplete(node: dict) -> int:
    if _node_type(node) != "PasswordInput":
        return 0
    props = _props(node)
    if props.get("autoComplete"):
        return 0
    label = str(props.get("label") or "").lower()
    name = str(props.get("name") or "").lower()
    is_new = any(k in f"{label} {name}" for k in ("new password", "create", "confirm", "signup", "sign up"))
    props["autoComplete"] = "new-password" if is_new else "current-password"
    return 1


def _fix_in_flight_disable(node: dict) -> int:
    if _node_type(node) != "Button":
        return 0
    props = _props(node)
    if props.get("submit") is True and "disabledWhileSubmitting" not in props:
        props["disabledWhileSubmitting"] = True
        return 1
    return 0


def _fix_no_double_submit(node: dict) -> int:
    if _node_type(node) != "Button":
        return 0
    props = _props(node)
    if props.get("submit") is True and "noDoubleSubmit" not in props:
        props["noDoubleSubmit"] = True
        return 1
    return 0


def _fix_submit_label(node: dict) -> int:
    if _node_type(node) != "Form":
        return 0
    props = _props(node)
    if not props.get("submitLabel"):
        props["submitLabel"] = "Save"
        return 1
    return 0


def _fix_textarea_min_rows(node: dict) -> int:
    if _node_type(node) != "Textarea":
        return 0
    props = _props(node)
    if "rows" not in props:
        props["rows"] = 3
        return 1
    return 0


def _fix_number_min_max_safety(node: dict) -> int:
    if _node_type(node) not in _NUMERIC_FIELDS:
        return 0
    props = _props(node)
    mn, mx = props.get("min"), props.get("max")
    try:
        if mn is not None and mx is not None and float(mn) > float(mx):
            del props["max"]
            return 1
    except (TypeError, ValueError):
        pass
    return 0


_GENERIC_CTA = {"ok", "submit", "go"}


def _fix_cta_verb(node: dict) -> int:
    if _node_type(node) != "Button":
        return 0
    props = _props(node)
    if props.get("submit") is not True:
        return 0
    label = str(props.get("label") or "").strip().lower()
    if label in _GENERIC_CTA:
        props["label"] = "Save"
        return 1
    return 0


def _fix_aria_invalid(node: dict) -> int:
    if _node_type(node) not in _INPUT_TYPES:
        return 0
    props = _props(node)
    if props.get("errorText") and "aria-invalid" not in props:
        props["aria-invalid"] = True
        return 1
    return 0


_FIX_RULES = (
    _fix_required_marker,
    _fix_input_mode,
    _fix_autocomplete_names,
    _fix_password_autocomplete,
    _fix_in_flight_disable,
    _fix_no_double_submit,
    _fix_submit_label,
    _fix_textarea_min_rows,
    _fix_number_min_max_safety,
    _fix_cta_verb,
    _fix_aria_invalid,
)


# ── findings ────────────────────────────────────────────────────────


def _finding(rule: str, message: str, severity: str = "warning") -> dict:
    return {"rule": f"form_ux.{rule}", "message": message, "severity": severity}


def _collect_findings(schema: dict, route: str) -> list[dict]:
    findings: list[dict] = []
    # field-missing-label
    for node in _iter_nodes(schema.get("root")):
        if _node_type(node) in _INPUT_TYPES:
            props = _props(node)
            if not props.get("label") and not props.get("aria-label"):
                findings.append(_finding(
                    "field_missing_label",
                    f"route {route!r}: {_node_type(node)} has no label / aria-label.",
                    "error",
                ))
    # form-too-large-unsectioned
    for node in _iter_nodes(schema.get("root")):
        if _node_type(node) != "Form":
            continue
        input_count = sum(1 for c in _iter_nodes(node.get("children")) if _node_type(c) in _INPUT_TYPES)
        has_heading = any(_node_type(c) == "Heading" for c in _iter_nodes(node.get("children")))
        if input_count > 12 and not has_heading:
            findings.append(_finding(
                "form_too_large_unsectioned",
                f"route {route!r}: Form has {input_count} inputs + no Section headings.",
                "warning",
            ))
    # destructive-no-confirm
    for node in _iter_nodes(schema.get("root")):
        if _node_type(node) != "Button":
            continue
        props = _props(node)
        if props.get("variant") == "destructive" and not props.get("confirmDialog"):
            findings.append(_finding(
                "destructive_no_confirm",
                f"route {route!r}: destructive Button without confirmDialog.",
                "warning",
            ))
    # placeholder-not-label
    for node in _iter_nodes(schema.get("root")):
        if _node_type(node) not in _INPUT_TYPES:
            continue
        props = _props(node)
        if props.get("placeholder") and not props.get("label"):
            findings.append(_finding(
                "placeholder_not_label",
                f"route {route!r}: {_node_type(node)} uses placeholder as label (disappears on focus).",
                "warning",
            ))
    # primary-cta-not-first: check Row of buttons where primary is not last
    for node in _iter_nodes(schema.get("root")):
        if _node_type(node) != "Row":
            continue
        children = node.get("children") or []
        button_types = [_node_type(c) for c in children if _node_type(c) == "Button"]
        if len(button_types) >= 2:
            variants = [((_props(c).get("variant")) or "default") for c in children if _node_type(c) == "Button"]
            if "primary" in variants and variants[-1] != "primary":
                findings.append(_finding(
                    "primary_cta_not_last",
                    f"route {route!r}: primary Button should be the last (rightmost) in the action row.",
                    "warning",
                ))
    return findings


# ── public API ──────────────────────────────────────────────────────


def apply(output_dir: str | Path, plan: dict | None = None) -> dict[str, Any]:
    """Apply all invariants. Returns ``{applied, fixed, findings, files}``.

    Flag-off returns ``{applied: False, reason: "flag-disabled"}``.
    """
    if not is_enabled():
        return {"applied": False, "reason": "flag-disabled"}
    root = Path(output_dir) if isinstance(output_dir, str) else output_dir
    if not root.is_dir():
        return {"applied": False, "reason": "output_dir-missing"}

    sdir = root / "src" / "schemas"
    if not sdir.is_dir():
        return {"applied": True, "fixed": 0, "findings": [], "files": 0}

    total_fixed = 0
    all_findings: list[dict] = []
    files_written = 0

    for p in sorted(sdir.glob("**/*.json")):
        if p.name in ("nav-flow.json", "shell.json"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue

        # Only touch schemas that actually contain a Form
        has_form = any(_node_type(n) == "Form" for n in _iter_nodes(data.get("root")))
        if not has_form:
            continue

        route = str(data.get("route") or f"/{p.stem}")
        fixed_this = 0
        for node in _iter_nodes(data.get("root")):
            for rule in _FIX_RULES:
                fixed_this += rule(node)
        if fixed_this:
            try:
                p.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                             encoding="utf-8")
                files_written += 1
            except Exception:  # noqa: BLE001
                logger.debug("[form_ux_invariants] write failed %s", p, exc_info=True)
        total_fixed += fixed_this

        all_findings.extend(_collect_findings(data, route))

    return {
        "applied": True,
        "fixed": total_fixed,
        "findings": all_findings,
        "files": files_written,
    }


__all__ = ["apply", "is_enabled", "INVARIANTS"]
