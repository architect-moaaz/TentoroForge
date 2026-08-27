"""Field-Interaction validator — the shared authority both the editor
UI and Smith call before writing an ``interaction`` block onto a form
field. See docs/superpowers/plans/2026-07-31-field-interaction-authoring.md
for the program overview.

Runtime contract (established in packages/renderer/src/runtime/formInteraction.ts):

    interaction: {
      computed?:    { formula: str, readOnly?: bool }
      optionsFrom?: { source: str, value: str, label: str, filter?: dict[str,str] }
      onChange?:    { fetch: {resource:str, by:str, from:str}, set: dict[str,str] }
      dependsOn?:   list[str]   # auto-derived from formula/filter/onChange if omitted
    }

This module returns a ValidationResult with:
  - ok        — True when the interaction is safe to write as-is (or with the canonical form)
  - canonical — the interaction with whitespace normalised + dependsOn auto-derived
  - errors    — actionable messages ("unknown field 'basicSalery' (did you mean basicSalary?)")
  - warnings  — non-blocking notes (type coercion, readOnly implicit)

Fails closed: any unrecognised interaction key or malformed shape rejects.
Fails open on unavailable registries (validation just downgrades checks to
warnings) so an interactively-authored change is never blocked by a missing
side channel.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field as dc_field
from typing import Any, Iterable


# ── Function library the runtime ships (mirror of INTERACTION_FUNCTIONS
# in packages/renderer/src/runtime/formInteraction.ts). Keep in sync when
# Slice 1 adds helpers. This is authoritative for the validator — if a
# formula calls something outside this set the validator rejects.
KNOWN_FUNCTIONS: frozenset[str] = frozenset({
    # Slice 1 (shipped baseline)
    "daysBetween", "hoursBetween", "sum", "min", "max",
    "round", "abs", "ceil", "floor", "ifElse",
    # Slice 1 additions (shipped alongside this module)
    "concat", "upper", "lower", "title", "slug", "initials",
    "contains", "startsWith", "endsWith",
    "avg", "count", "pow", "sqrt", "percent", "clamp",
    "now", "age", "today", "yearsBetween", "formatDate",
    "formatCurrency", "formatNumber", "formatPhone",
    "matches", "coalesce",
})


# Interaction kinds this validator understands. Anything else in the
# top-level of the interaction dict is an error — protects against typos
# ("dependson" vs "dependsOn") and forward-compat drift.
_VALID_INTERACTION_KEYS: frozenset[str] = frozenset({
    "computed", "optionsFrom", "onChange", "dependsOn",
    # Slice 4 primitives (validator recognises the keys pre-runtime ship
    # so the shape is stable; the runtime hooks land later)
    "visibleIf", "requiredIf", "enabledIf", "readOnlyIf",
})


# Tokens permitted in a formula OTHER than function names + sibling
# references: numeric literals, string literals, arithmetic operators,
# feel-lite comparison operators, boolean literals, and parens.
_FORMULA_LEXER = re.compile(
    r"""
      (?P<str>    "(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')     # string literal
    | (?P<num>    \d+(?:\.\d+)?)                            # numeric literal
    | (?P<ident>  [A-Za-z_][A-Za-z0-9_]*)                   # identifier (fn or var)
    | (?P<op>     ==|!=|<=|>=|&&|\|\||[+\-*/%<>()!,\.])     # operators / punctuation
    | (?P<ws>     \s+)                                      # whitespace
    """,
    re.VERBOSE,
)

# Reserved identifiers that are neither functions nor siblings (booleans, null).
_RESERVED_IDENTS: frozenset[str] = frozenset({"true", "false", "null", "undefined"})

# Predicate operators used in visibleIf/requiredIf/enabledIf/readOnlyIf.
_PREDICATE_OP_RE = re.compile(r"(==|!=|<=|>=|<|>)")


@dataclass
class ValidationResult:
    ok: bool
    canonical: dict[str, Any] | None = None
    errors: list[str] = dc_field(default_factory=list)
    warnings: list[str] = dc_field(default_factory=list)


# ── Public API ────────────────────────────────────────────────────────────


def validate_interaction(
    interaction: Any,
    field: dict[str, Any],
    siblings: list[dict[str, Any]],
    registry: dict[str, Any] | None = None,
) -> ValidationResult:
    """Validate a proposed ``interaction`` block for one field.

    Args:
        interaction: user-supplied dict (from Smith or editor).
        field:       the target field node (needs at minimum ``name``).
        siblings:    all peer fields on the same form (INCLUDING the target).
        registry:    resource-registry dict (optional — validator downgrades
                     resource checks to warnings when absent).
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(interaction, dict):
        return ValidationResult(
            ok=False,
            errors=[f"interaction must be a JSON object, got {type(interaction).__name__}"],
        )

    field_name = _safe_str(field.get("name"))
    if not field_name:
        errors.append("target field has no 'name'")

    sibling_names = _collect_names(siblings)
    resource_slugs = _collect_resource_slugs(registry)
    resource_columns = _collect_resource_columns(registry)

    # Reject unknown top-level keys (typos = user pain, fail early).
    unknown_keys = [k for k in interaction if k not in _VALID_INTERACTION_KEYS]
    for k in unknown_keys:
        suggestion = _closest(k, _VALID_INTERACTION_KEYS)
        hint = f" (did you mean '{suggestion}'?)" if suggestion else ""
        errors.append(f"unknown interaction key '{k}'{hint}")

    # Build the canonical output as we validate. Preserves only the fields
    # we understood, in a stable order.
    canonical: dict[str, Any] = {}
    derived_deps: set[str] = set()

    if "computed" in interaction:
        c_can, c_deps, c_err, c_warn = _validate_computed(
            interaction["computed"], sibling_names, field_name
        )
        errors.extend(c_err)
        warnings.extend(c_warn)
        if c_can is not None:
            canonical["computed"] = c_can
            derived_deps.update(c_deps)

    if "optionsFrom" in interaction:
        o_can, o_deps, o_err, o_warn = _validate_options_from(
            interaction["optionsFrom"], sibling_names, resource_slugs, resource_columns
        )
        errors.extend(o_err)
        warnings.extend(o_warn)
        if o_can is not None:
            canonical["optionsFrom"] = o_can
            derived_deps.update(o_deps)

    if "onChange" in interaction:
        ch_can, ch_err, ch_warn = _validate_on_change(
            interaction["onChange"], sibling_names, resource_slugs, resource_columns
        )
        errors.extend(ch_err)
        warnings.extend(ch_warn)
        if ch_can is not None:
            canonical["onChange"] = ch_can
            # onChange fires ON this field changing; no cross-field deps for it.

    for pred_key in ("visibleIf", "requiredIf", "enabledIf", "readOnlyIf"):
        if pred_key in interaction:
            p_can, p_deps, p_err, p_warn = _validate_predicate(
                interaction[pred_key], sibling_names, kind=pred_key
            )
            errors.extend(p_err)
            warnings.extend(p_warn)
            if p_can is not None:
                canonical[pred_key] = p_can
                derived_deps.update(p_deps)

    # dependsOn — user-supplied or auto-derived. When user supplies, validate
    # each name; when omitted, use derived. When both present, union.
    user_deps: list[str] = []
    if "dependsOn" in interaction:
        raw = interaction["dependsOn"]
        if not isinstance(raw, list):
            errors.append(f"dependsOn must be a list of field names, got {type(raw).__name__}")
        else:
            for d in raw:
                if not isinstance(d, str) or not d.strip():
                    errors.append(f"dependsOn entries must be non-empty strings; got {d!r}")
                    continue
                if d == field_name:
                    warnings.append(f"dependsOn refers to the field itself ('{d}') — dropped")
                    continue
                if sibling_names and d not in sibling_names:
                    suggestion = _closest(d, sibling_names)
                    hint = f" (did you mean '{suggestion}'?)" if suggestion else ""
                    errors.append(f"dependsOn: unknown field '{d}'{hint}")
                    continue
                user_deps.append(d)

    all_deps = sorted(set(user_deps) | derived_deps)
    if all_deps:
        canonical["dependsOn"] = all_deps

    ok = not errors
    return ValidationResult(
        ok=ok,
        canonical=canonical if ok else None,
        errors=errors,
        warnings=warnings,
    )


def extract_formula_refs(formula: str) -> tuple[set[str], set[str]]:
    """Return (identifiers, function_calls) present in a formula.

    Identifiers = bare names (siblings or reserved).
    Function calls = idents immediately followed by '('.

    Public because Smith uses it to preview which fields a formula
    depends on before persisting.
    """
    if not isinstance(formula, str):
        return set(), set()
    idents: set[str] = set()
    funcs: set[str] = set()
    tokens = list(_FORMULA_LEXER.finditer(formula))
    for i, m in enumerate(tokens):
        if m.lastgroup != "ident":
            continue
        name = m.group("ident")
        # Is this a function call? Peek at the next non-ws token.
        j = i + 1
        while j < len(tokens) and tokens[j].lastgroup == "ws":
            j += 1
        if j < len(tokens) and tokens[j].group("op") == "(":
            funcs.add(name)
        else:
            if name not in _RESERVED_IDENTS:
                idents.add(name)
    return idents, funcs


# ── Internal validators (one per interaction kind) ────────────────────────


def _validate_computed(
    node: Any,
    sibling_names: set[str],
    field_name: str,
) -> tuple[dict | None, set[str], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(node, dict):
        return None, set(), [f"computed: expected object, got {type(node).__name__}"], []
    if "formula" not in node:
        return None, set(), ["computed: missing 'formula'"], []
    formula = node["formula"]
    if not isinstance(formula, str) or not formula.strip():
        return None, set(), ["computed.formula: must be a non-empty string"], []

    formula = formula.strip()
    idents, funcs = extract_formula_refs(formula)

    # Function-name validation
    for fn in funcs:
        if fn not in KNOWN_FUNCTIONS:
            suggestion = _closest(fn, KNOWN_FUNCTIONS)
            hint = f" (did you mean '{suggestion}'?)" if suggestion else ""
            errors.append(
                f"computed.formula: unknown function '{fn}'{hint}. "
                f"Available: {', '.join(sorted(KNOWN_FUNCTIONS)[:8])}, …"
            )

    # Sibling-name validation (skip self-reference — that's a cycle)
    deps: set[str] = set()
    for ident in idents:
        if ident == field_name:
            errors.append(
                f"computed.formula: field '{field_name}' references itself — a computed field cannot depend on its own value"
            )
            continue
        if sibling_names and ident not in sibling_names:
            suggestion = _closest(ident, sibling_names)
            hint = f" (did you mean '{suggestion}'?)" if suggestion else ""
            errors.append(f"computed.formula: unknown field '{ident}'{hint}")
            continue
        deps.add(ident)

    if errors:
        return None, deps, errors, warnings

    canonical: dict[str, Any] = {"formula": formula}
    ro = node.get("readOnly")
    if ro is None:
        # Default computed to readOnly — a user typing over the derived
        # value defeats the whole point. Explicit False if you want it
        # editable (rare — usually you'd use a plain field with a suggest
        # button instead).
        canonical["readOnly"] = True
    else:
        if not isinstance(ro, bool):
            errors.append(f"computed.readOnly: expected bool, got {type(ro).__name__}")
            return None, deps, errors, warnings
        canonical["readOnly"] = ro

    return canonical, deps, [], warnings


def _validate_options_from(
    node: Any,
    sibling_names: set[str],
    resource_slugs: set[str] | None,
    resource_columns: dict[str, set[str]] | None,
) -> tuple[dict | None, set[str], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(node, dict):
        return None, set(), [f"optionsFrom: expected object, got {type(node).__name__}"], []

    source = node.get("source")
    if not isinstance(source, str) or not source.strip():
        errors.append("optionsFrom.source: required non-empty string (resource slug)")
        return None, set(), errors, warnings
    source = source.strip()

    value = node.get("value")
    label = node.get("label")
    if not isinstance(value, str) or not value.strip():
        errors.append("optionsFrom.value: required non-empty string (column name)")
    if not isinstance(label, str) or not label.strip():
        errors.append("optionsFrom.label: required non-empty string (column name)")

    # Resource existence (only when registry is available)
    if resource_slugs is not None:
        if source not in resource_slugs:
            suggestion = _closest(source, resource_slugs)
            hint = f" (did you mean '{suggestion}'?)" if suggestion else ""
            errors.append(f"optionsFrom.source: unknown resource '{source}'{hint}")

    # Column existence (only when we have column metadata)
    if resource_columns and source in resource_columns:
        cols = resource_columns[source]
        for key_name, key_val in (("value", value), ("label", label)):
            if isinstance(key_val, str) and key_val and key_val not in cols:
                suggestion = _closest(key_val, cols)
                hint = f" (did you mean '{suggestion}'?)" if suggestion else ""
                errors.append(
                    f"optionsFrom.{key_name}: '{key_val}' is not a column of '{source}'{hint}"
                )

    deps: set[str] = set()
    filt = node.get("filter")
    canonical_filter: dict[str, str] = {}
    if filt is not None:
        if not isinstance(filt, dict):
            errors.append(f"optionsFrom.filter: expected object, got {type(filt).__name__}")
        else:
            for fk, fv in filt.items():
                if not isinstance(fk, str) or not fk.strip():
                    errors.append(f"optionsFrom.filter: keys must be non-empty strings; got {fk!r}")
                    continue
                if not isinstance(fv, (str, int, float, bool)):
                    errors.append(
                        f"optionsFrom.filter['{fk}']: value must be a scalar or template, "
                        f"got {type(fv).__name__}"
                    )
                    continue
                if isinstance(fv, str):
                    for ref in _mustache_refs(fv):
                        if ref == "":
                            continue
                        if sibling_names and ref not in sibling_names:
                            suggestion = _closest(ref, sibling_names)
                            hint = f" (did you mean '{suggestion}'?)" if suggestion else ""
                            errors.append(
                                f"optionsFrom.filter['{fk}']: template refs unknown field '{ref}'{hint}"
                            )
                            continue
                        deps.add(ref)
                canonical_filter[fk] = fv

    if errors:
        return None, deps, errors, warnings

    canonical: dict[str, Any] = {"source": source, "value": value, "label": label}
    if canonical_filter:
        canonical["filter"] = canonical_filter
    return canonical, deps, [], warnings


def _validate_on_change(
    node: Any,
    sibling_names: set[str],
    resource_slugs: set[str] | None,
    resource_columns: dict[str, set[str]] | None,
) -> tuple[dict | None, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(node, dict):
        return None, [f"onChange: expected object, got {type(node).__name__}"], []

    fetch_spec = node.get("fetch")
    set_spec = node.get("set")
    if not isinstance(fetch_spec, dict):
        errors.append("onChange.fetch: required object with {resource, by, from}")
        return None, errors, warnings

    resource = fetch_spec.get("resource")
    by = fetch_spec.get("by")
    from_field = fetch_spec.get("from")
    if not isinstance(resource, str) or not resource.strip():
        errors.append("onChange.fetch.resource: required non-empty string")
    if not isinstance(by, str) or not by.strip():
        errors.append("onChange.fetch.by: required non-empty string (column on resource)")
    if not isinstance(from_field, str) or not from_field.strip():
        errors.append("onChange.fetch.from: required non-empty string (sibling field)")
    if errors:
        return None, errors, warnings

    resource = resource.strip()
    by = by.strip()
    from_field = from_field.strip()

    if resource_slugs is not None and resource not in resource_slugs:
        suggestion = _closest(resource, resource_slugs)
        hint = f" (did you mean '{suggestion}'?)" if suggestion else ""
        errors.append(f"onChange.fetch.resource: unknown resource '{resource}'{hint}")
    if resource_columns and resource in resource_columns:
        if by not in resource_columns[resource]:
            suggestion = _closest(by, resource_columns[resource])
            hint = f" (did you mean '{suggestion}'?)" if suggestion else ""
            errors.append(
                f"onChange.fetch.by: '{by}' is not a column of '{resource}'{hint}"
            )
    if sibling_names and from_field not in sibling_names:
        suggestion = _closest(from_field, sibling_names)
        hint = f" (did you mean '{suggestion}'?)" if suggestion else ""
        errors.append(f"onChange.fetch.from: unknown field '{from_field}'{hint}")

    if not isinstance(set_spec, dict) or not set_spec:
        errors.append("onChange.set: required non-empty object mapping target fields to templates")
        return None, errors, warnings

    canonical_set: dict[str, str] = {}
    for target, tmpl in set_spec.items():
        if not isinstance(target, str) or not target.strip():
            errors.append(f"onChange.set: keys must be non-empty strings; got {target!r}")
            continue
        if sibling_names and target not in sibling_names:
            suggestion = _closest(target, sibling_names)
            hint = f" (did you mean '{suggestion}'?)" if suggestion else ""
            errors.append(f"onChange.set: unknown target field '{target}'{hint}")
            continue
        if not isinstance(tmpl, str):
            errors.append(
                f"onChange.set['{target}']: value must be a template string, "
                f"got {type(tmpl).__name__}"
            )
            continue
        # Templates reference {{result.X}} — validate the shape, not X against
        # column list unless we have the resource's columns.
        for ref in _mustache_refs(tmpl):
            if not ref.startswith("result."):
                errors.append(
                    f"onChange.set['{target}']: template refs '{ref}' — onChange templates "
                    f"resolve against `result` (the fetched row); use {{{{result.{ref}}}}}"
                )
                continue
            col = ref.split(".", 1)[1]
            if resource_columns and resource in resource_columns:
                if col and col not in resource_columns[resource]:
                    suggestion = _closest(col, resource_columns[resource])
                    hint = f" (did you mean '{suggestion}'?)" if suggestion else ""
                    warnings.append(
                        f"onChange.set['{target}']: template refs '{ref}' — "
                        f"'{col}' isn't a known column of '{resource}'{hint}"
                    )
        canonical_set[target] = tmpl

    if errors:
        return None, errors, warnings

    canonical: dict[str, Any] = {
        "fetch": {"resource": resource, "by": by, "from": from_field},
        "set": canonical_set,
    }
    return canonical, [], warnings


def _validate_predicate(
    expr: Any,
    sibling_names: set[str],
    kind: str,
) -> tuple[str | None, set[str], list[str], list[str]]:
    """Validate a visibleIf/requiredIf/enabledIf/readOnlyIf predicate. The
    runtime hook lands in Slice 4; this validator ships the shape earlier
    so the same interaction_spec API covers everything.
    """
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(expr, str) or not expr.strip():
        errors.append(f"{kind}: must be a non-empty predicate string (e.g. \"country == 'US'\")")
        return None, set(), errors, warnings

    expr = expr.strip()

    # Must contain at least one comparison operator to be a predicate.
    if not _PREDICATE_OP_RE.search(expr):
        warnings.append(
            f"{kind}: expression '{expr}' has no comparison operator; "
            "will be evaluated for truthiness of the whole expression"
        )

    idents, funcs = extract_formula_refs(expr)
    for fn in funcs:
        if fn not in KNOWN_FUNCTIONS:
            suggestion = _closest(fn, KNOWN_FUNCTIONS)
            hint = f" (did you mean '{suggestion}'?)" if suggestion else ""
            errors.append(f"{kind}: unknown function '{fn}'{hint}")

    deps: set[str] = set()
    for ident in idents:
        if sibling_names and ident not in sibling_names:
            suggestion = _closest(ident, sibling_names)
            hint = f" (did you mean '{suggestion}'?)" if suggestion else ""
            errors.append(f"{kind}: unknown field '{ident}'{hint}")
            continue
        deps.add(ident)

    if errors:
        return None, deps, errors, warnings
    return expr, deps, [], warnings


# ── Helpers ───────────────────────────────────────────────────────────────


def _safe_str(x: Any) -> str:
    return x.strip() if isinstance(x, str) else ""


def _collect_names(fields: list[dict[str, Any]] | None) -> set[str]:
    if not fields:
        return set()
    out: set[str] = set()
    for f in fields:
        if isinstance(f, dict):
            name = f.get("name")
            if isinstance(name, str) and name.strip():
                out.add(name.strip())
    return out


def _collect_resource_slugs(registry: dict[str, Any] | None) -> set[str] | None:
    """Return the set of registered entity slugs, or None if registry not
    available (caller should skip resource checks rather than reject)."""
    if not isinstance(registry, dict):
        return None
    entities = registry.get("entities")
    if not isinstance(entities, dict):
        return None
    slugs: set[str] = set()
    for e in entities.values():
        if not isinstance(e, dict):
            continue
        for key in ("slug", "route", "name"):
            v = e.get(key)
            if isinstance(v, str) and v.strip():
                slugs.add(v.strip())
    return slugs or None


def _collect_resource_columns(registry: dict[str, Any] | None) -> dict[str, set[str]] | None:
    """Map slug → set of column names."""
    if not isinstance(registry, dict):
        return None
    entities = registry.get("entities")
    if not isinstance(entities, dict):
        return None
    out: dict[str, set[str]] = {}
    for e in entities.values():
        if not isinstance(e, dict):
            continue
        cols: set[str] = set()
        for c in e.get("columns") or []:
            if isinstance(c, dict):
                n = c.get("name")
                if isinstance(n, str) and n.strip():
                    cols.add(n.strip())
            elif isinstance(c, str) and c.strip():
                cols.add(c.strip())
        if not cols:
            continue
        for key in ("slug", "route", "name"):
            v = e.get(key)
            if isinstance(v, str) and v.strip():
                out[v.strip()] = cols
    return out or None


def _closest(needle: str, haystack: Iterable[str]) -> str | None:
    """Return the closest match from haystack, or None if nothing within 60%
    similarity. Used to power friendly typo-suggest hints."""
    if not needle or not haystack:
        return None
    matches = difflib.get_close_matches(needle, list(haystack), n=1, cutoff=0.6)
    return matches[0] if matches else None


_MUSTACHE_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


def _mustache_refs(template: str) -> list[str]:
    """Return every `{{ref}}` name in the template, in order."""
    if not isinstance(template, str):
        return []
    return [m.group(1) for m in _MUSTACHE_RE.finditer(template)]
