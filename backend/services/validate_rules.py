"""
Validates project rules against the registry's entity/field definitions.

Checks that rules reference valid entities and fields, that operator types
are compatible with field types, that enum values are valid, and that
state machine transitions reference real states.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

NUMERIC_TYPES = {"serial", "integer", "float", "decimal", "numeric", "real", "bigint"}
STRING_TYPES = {"varchar", "text", "char"}
NUMERIC_OPERATORS = {"gt", "lt", "gte", "lte", "min", "max", "minValue", "maxValue", ">", "<", ">=", "<="}
STRING_OPERATORS = {"regex", "pattern", "minLength", "maxLength", "startsWith", "endsWith"}
ENUM_CONFIG_KEYS = {"value", "values", "allowedValues", "enum", "equals", "notEquals", "oneOf"}
AI_RULE_TYPES = {"content_moderation", "ai_validation", "ai_enrichment", "similarity_check"}


@dataclass
class RuleValidationError:
    rule_name: str
    error: str
    suggestion: str | None = None
    severity: str = "error"  # "error" | "warning"


def fuzzy_match(name: str, candidates: list[str], threshold: float = 0.6) -> str | None:
    """Return the best candidate above *threshold* using normalised edit-distance."""
    if not candidates:
        return None

    best: str | None = None
    best_score = 0.0

    for candidate in candidates:
        score = _similarity(name.lower(), candidate.lower())
        if score > best_score:
            best_score = score
            best = candidate

    return best if best_score >= threshold else None


def _similarity(a: str, b: str) -> float:
    """1 - (levenshtein / max_len), so 1.0 == identical."""
    if a == b:
        return 1.0
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 1.0
    return 1.0 - _levenshtein(a, b) / max_len


def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        return _levenshtein(b, a)
    if not b:
        return len(a)

    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


# ── public API ───────────────────────────────────────────────────────────


def validate_rules(entities: dict, rules: list[dict]) -> list[RuleValidationError]:
    """Validate every rule in *rules* against the entity registry."""
    errors: list[RuleValidationError] = []
    for rule in rules:
        errors.extend(validate_rule(entities, rule))
    return errors


def validate_rule(entities: dict, rule: dict) -> list[RuleValidationError]:
    """Validate a single rule dict and return any errors/warnings."""
    errors: list[RuleValidationError] = []
    rule_name: str = rule.get("name", "<unnamed>")
    model_name: str | None = rule.get("model_name")
    field_name: str | None = rule.get("field_name")
    rule_type: str | None = rule.get("rule_type")
    config: dict = rule.get("config") or {}

    entity_fields: dict | None = None

    # (a) entity existence
    if model_name:
        if model_name not in entities:
            suggestion = fuzzy_match(model_name, list(entities.keys()))
            msg = f"Entity '{model_name}' does not exist in the registry."
            errors.append(RuleValidationError(
                rule_name=rule_name,
                error=msg,
                suggestion=f"Did you mean '{suggestion}'?" if suggestion else None,
                severity="error",
            ))
            # Can't validate further without a valid entity.
            return errors
        entity_fields = entities[model_name].get("fields", {})

    # (b) field existence
    if field_name and entity_fields is not None:
        if field_name not in entity_fields:
            suggestion = fuzzy_match(field_name, list(entity_fields.keys()))
            msg = f"Field '{field_name}' does not exist on entity '{model_name}'."
            errors.append(RuleValidationError(
                rule_name=rule_name,
                error=msg,
                suggestion=f"Did you mean '{suggestion}'?" if suggestion else None,
                severity="error",
            ))
            # Can't do type-level checks without a valid field.
            return errors

    # For AI-based rule types, skip deeper config validation.
    if rule_type in AI_RULE_TYPES:
        return errors

    field_def: dict | None = None
    if field_name and entity_fields is not None:
        field_def = entity_fields.get(field_name, {})

    field_type: str | None = field_def.get("type") if field_def else None

    # (c) type compatibility for validation rules
    if rule_type == "validation" and field_type and config:
        config_keys = set(config.keys())

        has_numeric = bool(config_keys & NUMERIC_OPERATORS)
        has_string = bool(config_keys & STRING_OPERATORS)

        if has_numeric and field_type not in NUMERIC_TYPES:
            errors.append(RuleValidationError(
                rule_name=rule_name,
                error=(
                    f"Rule uses numeric operators ({config_keys & NUMERIC_OPERATORS}) "
                    f"but field '{field_name}' has type '{field_type}'."
                ),
                suggestion=f"Numeric operators require a numeric field type (one of {sorted(NUMERIC_TYPES)}).",
                severity="error",
            ))

        if has_string and field_type not in STRING_TYPES:
            errors.append(RuleValidationError(
                rule_name=rule_name,
                error=(
                    f"Rule uses string operators ({config_keys & STRING_OPERATORS}) "
                    f"but field '{field_name}' has type '{field_type}'."
                ),
                suggestion=f"String operators require a string field type (one of {sorted(STRING_TYPES)}).",
                severity="error",
            ))

    # (d) enum value checks
    if field_def and config:
        enum_values = field_def.get("enum_values")
        if enum_values is not None:
            _check_enum_values(rule_name, field_name, config, set(enum_values), errors)

    # (e) state machine rules
    if rule_type == "state_machine" and field_def and config:
        enum_values = field_def.get("enum_values")
        if enum_values is not None:
            allowed = set(enum_values)
            _check_state_machine(rule_name, field_name, config, allowed, errors)

    return errors


# ── internal helpers ─────────────────────────────────────────────────────


def _check_enum_values(
    rule_name: str,
    field_name: str | None,
    config: dict,
    allowed: set[str],
    errors: list[RuleValidationError],
) -> None:
    """Check that any values referenced in config are valid enum members."""
    for key in ENUM_CONFIG_KEYS:
        if key not in config:
            continue
        raw = config[key]
        values_to_check: list = []
        if isinstance(raw, list):
            values_to_check = raw
        elif isinstance(raw, str):
            values_to_check = [raw]
        else:
            continue

        for val in values_to_check:
            if isinstance(val, str) and val not in allowed:
                errors.append(RuleValidationError(
                    rule_name=rule_name,
                    error=(
                        f"Config key '{key}' references value '{val}' which is not "
                        f"a valid enum value for field '{field_name}'."
                    ),
                    suggestion=f"Allowed values: {sorted(allowed)}.",
                    severity="warning",
                ))


def _check_state_machine(
    rule_name: str,
    field_name: str | None,
    config: dict,
    allowed: set[str],
    errors: list[RuleValidationError],
) -> None:
    """Verify state machine states/transitions match the field's enum values."""
    # Check explicit states list
    states = config.get("states")
    if isinstance(states, list):
        for state in states:
            if isinstance(state, str) and state not in allowed:
                errors.append(RuleValidationError(
                    rule_name=rule_name,
                    error=(
                        f"State '{state}' in state_machine config is not a valid "
                        f"enum value for field '{field_name}'."
                    ),
                    suggestion=f"Allowed values: {sorted(allowed)}.",
                    severity="warning",
                ))

    # Check transitions (list of dicts with "from" / "to")
    transitions = config.get("transitions")
    if isinstance(transitions, list):
        for t in transitions:
            if not isinstance(t, dict):
                continue
            for direction in ("from", "to"):
                val = t.get(direction)
                if isinstance(val, str) and val not in allowed:
                    errors.append(RuleValidationError(
                        rule_name=rule_name,
                        error=(
                            f"Transition {direction} state '{val}' is not a valid "
                            f"enum value for field '{field_name}'."
                        ),
                        suggestion=f"Allowed values: {sorted(allowed)}.",
                        severity="warning",
                    ))


# ── formatting ───────────────────────────────────────────────────────────


def format_rule_errors(errors: list[RuleValidationError]) -> str:
    """Return a human-readable summary of validation errors."""
    if not errors:
        return "All rules are valid."

    lines: list[str] = [f"Found {len(errors)} rule validation issue(s):\n"]
    for i, err in enumerate(errors, 1):
        prefix = "ERROR" if err.severity == "error" else "WARNING"
        lines.append(f"  {i}. [{prefix}] {err.rule_name}: {err.error}")
        if err.suggestion:
            lines.append(f"     -> {err.suggestion}")
    return "\n".join(lines)
