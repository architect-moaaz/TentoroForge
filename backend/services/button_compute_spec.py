"""Validator for button ``onClick: {compute}`` actions — enables imperative
compute-on-click patterns (calculator '=' key, "Calculate EMI" button,
"Generate password", "Preview total").

Reuses the same formula-parsing + function/sibling checks as
:mod:`services.interaction_spec`, then tightens for the button context:
buttons live INSIDE forms, so the same siblings apply, but the target
field must exist as a form field too.

Shape validated:
    {
      "kind": "compute",
      "target": "<fieldName in the enclosing form>",
      "formula": "<expression over siblings + INTERACTION_FUNCTIONS>"
    }

Editor + Smith call ``validate_compute_action`` before writing the
button's onClick block, same fail-open/fail-closed contract as
:func:`services.interaction_spec.validate_interaction`.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any

from services.interaction_spec import (
    KNOWN_FUNCTIONS,
    extract_formula_refs,
    _closest,  # type: ignore[attr-defined]  — internal helper reuse
)


@dataclass
class ButtonComputeResult:
    ok: bool
    canonical: dict[str, Any] | None = None
    errors: list[str] = dc_field(default_factory=list)
    warnings: list[str] = dc_field(default_factory=list)


def validate_compute_action(
    action: Any,
    form_fields: list[dict[str, Any]],
) -> ButtonComputeResult:
    """Validate one ``{kind:"compute", target, formula}`` action against the
    fields of the button's enclosing form.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(action, dict):
        return ButtonComputeResult(
            ok=False,
            errors=[f"action must be an object, got {type(action).__name__}"],
        )
    kind = action.get("kind")
    if kind != "compute":
        return ButtonComputeResult(
            ok=False, errors=[f"kind must be 'compute', got {kind!r}"]
        )

    target = action.get("target")
    formula = action.get("formula")
    if not isinstance(target, str) or not target.strip():
        errors.append("target: required non-empty string (field name)")
    if not isinstance(formula, str) or not formula.strip():
        errors.append("formula: required non-empty string")
    if errors:
        return ButtonComputeResult(ok=False, errors=errors)

    target = target.strip()
    formula = formula.strip()

    field_names = {
        f.get("name") for f in (form_fields or []) if isinstance(f, dict) and isinstance(f.get("name"), str)
    }
    if target not in field_names:
        suggestion = _closest(target, field_names)
        hint = f" (did you mean '{suggestion}'?)" if suggestion else ""
        errors.append(f"target: unknown field '{target}' in the enclosing form{hint}")

    idents, funcs = extract_formula_refs(formula)
    for fn in funcs:
        if fn not in KNOWN_FUNCTIONS:
            suggestion = _closest(fn, KNOWN_FUNCTIONS)
            hint = f" (did you mean '{suggestion}'?)" if suggestion else ""
            errors.append(f"formula: unknown function '{fn}'{hint}")

    reads: set[str] = set()
    for ident in idents:
        if field_names and ident not in field_names:
            suggestion = _closest(ident, field_names)
            hint = f" (did you mean '{suggestion}'?)" if suggestion else ""
            errors.append(f"formula: unknown field '{ident}'{hint}")
            continue
        reads.add(ident)

    if errors:
        return ButtonComputeResult(ok=False, errors=errors, warnings=warnings)

    canonical: dict[str, Any] = {
        "kind": "compute",
        "target": target,
        "formula": formula,
    }
    if reads:
        canonical["reads"] = sorted(reads)
    return ButtonComputeResult(ok=True, canonical=canonical, warnings=warnings)
