"""
Registry validation engine.

Validates cross-references in a Contract Registry — a shared JSON structure
that tracks what each code generation agent has produced. Catches dangling
references, type mismatches, and missing bindings before they reach codegen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable

logger = logging.getLogger(__name__)

NUMERIC_TYPES = frozenset({"serial", "integer", "float", "decimal", "numeric"})
NUMERIC_OPERATORS = frozenset({">", "<", ">=", "<="})


@dataclass
class RegistryError:
    section: str
    name: str
    error: str
    suggestion: str | None = None
    severity: str = "error"


# ---------------------------------------------------------------------------
# Fuzzy matching (inline Levenshtein, no external deps)
# ---------------------------------------------------------------------------

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


def fuzzy_match(name: str, candidates: Iterable[str], threshold: float = 0.6) -> str | None:
    """Return the closest candidate if similarity exceeds *threshold*, else None."""
    best: str | None = None
    best_sim = 0.0
    for candidate in candidates:
        max_len = max(len(name), len(candidate))
        if max_len == 0:
            continue
        sim = 1.0 - _levenshtein(name, candidate) / max_len
        if sim > best_sim:
            best_sim = sim
            best = candidate
    if best_sim >= threshold:
        return best
    return None


# ---------------------------------------------------------------------------
# Individual validation checks
# ---------------------------------------------------------------------------

def _validate_relations(registry: dict, errors: list[RegistryError]) -> None:
    entities = registry.get("entities", {})
    for rel in registry.get("relations", []):
        label = f"{rel.get('from_entity', '?')}->{rel.get('to_entity', '?')}"
        for side in ("from_entity", "to_entity"):
            ent = rel.get(side, "")
            if ent not in entities:
                suggestion = fuzzy_match(ent, entities)
                errors.append(RegistryError(
                    section="relations",
                    name=label,
                    error=f"Relation references non-existent entity '{ent}' ({side})",
                    suggestion=f"Did you mean '{suggestion}'?" if suggestion else None,
                ))


def _validate_api_routes(registry: dict, errors: list[RegistryError]) -> None:
    entities = registry.get("entities", {})
    for route, cfg in registry.get("api_routes", {}).items():
        ent = cfg.get("entity", "")
        if ent and ent not in entities:
            suggestion = fuzzy_match(ent, entities)
            errors.append(RegistryError(
                section="api_routes",
                name=route,
                error=f"API route references non-existent entity '{ent}'",
                suggestion=f"Did you mean '{suggestion}'?" if suggestion else None,
            ))


def _validate_components(registry: dict, errors: list[RegistryError]) -> None:
    entities = registry.get("entities", {})
    api_routes = registry.get("api_routes", {})

    for comp_name, comp in registry.get("components", {}).items():
        # Field refs
        for ref in comp.get("field_refs", []):
            parts = ref.split(".", 1)
            if len(parts) != 2:
                errors.append(RegistryError(
                    section="components",
                    name=comp_name,
                    error=f"Malformed field reference '{ref}' (expected 'Entity.field')",
                ))
                continue
            ent_name, field_name = parts
            if ent_name not in entities:
                suggestion = fuzzy_match(ent_name, entities)
                errors.append(RegistryError(
                    section="components",
                    name=comp_name,
                    error=f"Field ref '{ref}' references non-existent entity '{ent_name}'",
                    suggestion=f"Did you mean '{suggestion}'?" if suggestion else None,
                ))
            else:
                fields = entities[ent_name].get("fields", {})
                if field_name not in fields:
                    suggestion = fuzzy_match(field_name, fields)
                    errors.append(RegistryError(
                        section="components",
                        name=comp_name,
                        error=f"Field ref '{ref}' references non-existent field '{field_name}' on entity '{ent_name}'",
                        suggestion=f"Did you mean '{suggestion}'?" if suggestion else None,
                    ))

        # API calls
        for call in comp.get("api_calls", []):
            if call not in api_routes:
                suggestion = fuzzy_match(call, api_routes)
                errors.append(RegistryError(
                    section="components",
                    name=comp_name,
                    error=f"Component calls unregistered API route '{call}'",
                    suggestion=f"Did you mean '{suggestion}'?" if suggestion else None,
                ))


def _validate_pages(registry: dict, errors: list[RegistryError]) -> None:
    components = registry.get("components", {})
    api_routes = registry.get("api_routes", {})

    for page_path, page in registry.get("pages", {}).items():
        for comp_name in page.get("components", []):
            if comp_name not in components:
                suggestion = fuzzy_match(comp_name, components)
                errors.append(RegistryError(
                    section="pages",
                    name=page_path,
                    error=f"Page imports unregistered component '{comp_name}'",
                    suggestion=f"Did you mean '{suggestion}'?" if suggestion else None,
                ))

        for call in page.get("api_calls", []):
            if call not in api_routes:
                suggestion = fuzzy_match(call, api_routes)
                errors.append(RegistryError(
                    section="pages",
                    name=page_path,
                    error=f"Page calls unregistered API route '{call}'",
                    suggestion=f"Did you mean '{suggestion}'?" if suggestion else None,
                ))


def _validate_workflow_bindings(registry: dict, errors: list[RegistryError]) -> None:
    pages = registry.get("pages", {})
    for binding_name, binding in registry.get("workflow_bindings", {}).items():
        page = binding.get("page", "")
        if page not in pages:
            suggestion = fuzzy_match(page, pages)
            errors.append(RegistryError(
                section="workflow_bindings",
                name=binding_name,
                error=f"Workflow binding points to non-existent page '{page}'",
                suggestion=f"Did you mean '{suggestion}'?" if suggestion else None,
            ))


def _base_field_type(raw_type: str) -> str:
    """Normalise a type string like 'varchar(50)' to 'varchar'."""
    paren = raw_type.find("(")
    return raw_type[:paren].lower().strip() if paren != -1 else raw_type.lower().strip()


def _validate_rules(registry: dict, errors: list[RegistryError]) -> None:
    entities = registry.get("entities", {})

    for rule_name, rule in registry.get("rules", {}).items():
        ent_name = rule.get("entity", "")
        field_name = rule.get("field", "")

        # Entity existence
        if ent_name not in entities:
            suggestion = fuzzy_match(ent_name, entities)
            errors.append(RegistryError(
                section="rules",
                name=rule_name,
                error=f"Rule references non-existent entity '{ent_name}'",
                suggestion=f"Did you mean '{suggestion}'?" if suggestion else None,
            ))
            continue

        fields = entities[ent_name].get("fields", {})

        # Field existence
        if field_name not in fields:
            suggestion = fuzzy_match(field_name, fields)
            errors.append(RegistryError(
                section="rules",
                name=rule_name,
                error=f"Rule references non-existent field '{field_name}' on entity '{ent_name}'",
                suggestion=f"Did you mean '{suggestion}'?" if suggestion else None,
            ))
            continue

        field_def = fields[field_name]
        raw_type = field_def.get("type", "") if isinstance(field_def, dict) else str(field_def)
        base_type = _base_field_type(raw_type)
        operator = rule.get("operator", "")
        value = rule.get("value")

        # Type compatibility — numeric operators on non-numeric types
        if operator in NUMERIC_OPERATORS and base_type not in NUMERIC_TYPES:
            errors.append(RegistryError(
                section="rules",
                name=rule_name,
                error=(
                    f"Numeric operator '{operator}' used on non-numeric field "
                    f"'{ent_name}.{field_name}' (type: {raw_type})"
                ),
                severity="error",
            ))

        # Enum value validity
        enum_values = field_def.get("enum_values") if isinstance(field_def, dict) else None
        if enum_values is not None and value is not None:
            if value not in enum_values:
                suggestion = fuzzy_match(str(value), (str(v) for v in enum_values))
                errors.append(RegistryError(
                    section="rules",
                    name=rule_name,
                    error=f"Rule value '{value}' is not a valid enum value for '{ent_name}.{field_name}'",
                    suggestion=f"Did you mean '{suggestion}'?" if suggestion else None,
                    severity="error",
                ))


# ---------------------------------------------------------------------------
# Main validation entry point
# ---------------------------------------------------------------------------

def validate_registry(registry: dict) -> list[RegistryError]:
    """Run every cross-reference check against *registry* and return all errors."""
    errors: list[RegistryError] = []

    _validate_relations(registry, errors)
    _validate_api_routes(registry, errors)
    _validate_components(registry, errors)
    _validate_pages(registry, errors)
    _validate_workflow_bindings(registry, errors)
    _validate_rules(registry, errors)

    if errors:
        logger.warning("Registry validation found %d issue(s)", len(errors))
    else:
        logger.info("Registry validation passed with no issues")

    return errors


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def format_validation_report(errors: list[RegistryError]) -> str:
    """Format errors grouped by section for logging/display."""
    if not errors:
        return "Registry validation: 0 issues found."

    error_count = sum(1 for e in errors if e.severity == "error")
    warning_count = sum(1 for e in errors if e.severity == "warning")

    parts: list[str] = []
    parts.append(
        f"Registry validation: {len(errors)} issue(s) "
        f"({error_count} error(s), {warning_count} warning(s))"
    )
    parts.append("")

    grouped: dict[str, list[RegistryError]] = {}
    for err in errors:
        grouped.setdefault(err.section, []).append(err)

    for section, section_errors in grouped.items():
        parts.append(f"[{section}]")
        for err in section_errors:
            tag = "ERROR" if err.severity == "error" else "WARN"
            parts.append(f"  {tag}  {err.name}: {err.error}")
            if err.suggestion:
                parts.append(f"        -> {err.suggestion}")
        parts.append("")

    return "\n".join(parts)
