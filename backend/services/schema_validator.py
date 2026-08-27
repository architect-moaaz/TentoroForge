"""schema_validator — token-path validation.

The Zod schema (PageV2) validates STRUCTURE — it ensures the right keys
exist, types match, etc. It does NOT check whether `tokens.color.brand.500`
is a path that actually exists in the project's defaultTokens namespace.
This module fills that gap.

Usage:
    refs = collect_token_refs(schema_dict)
    tokens = {**defaultTokens, **tokens_custom}  # union
    valid, invalid = validate_token_refs(schema_dict, tokens)
    if invalid_ref_pct(valid, len(invalid)) > 50.0:
        raise SchemaValidationError("design context not reaching LLM")
"""
from __future__ import annotations

import re
from typing import Any

# Token-ref regex: tokens.<scope>.<...path>
_TOKEN_REF_RE = re.compile(r"^tokens\.[a-z]+(?:\.[a-zA-Z0-9_]+)+$")


def collect_token_refs(schema: Any, path: str = "$") -> list[tuple[str, str]]:
    """Walk the schema tree, return list of (json-path, ref) tuples for
    every string value that looks like a token ref.

    Used to inventory all token refs the LLM emitted, so we can validate
    each one against the project's actual token namespace.
    """
    refs: list[tuple[str, str]] = []

    def _walk(node: Any, p: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                _walk(v, f"{p}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                _walk(v, f"{p}[{i}]")
        elif isinstance(node, str) and _TOKEN_REF_RE.match(node):
            refs.append((p, node))

    _walk(schema, path)
    return refs


def path_exists_in(ref: str, tokens: dict) -> bool:
    """Resolve a token-ref against a tokens dict; return True if the path
    resolves to a leaf value (not a branch).

    `ref` should look like 'tokens.color.primary.500'. Returns False if:
      - ref doesn't start with 'tokens.'
      - any segment doesn't exist in the dict
      - the final resolution is itself a dict (i.e., a branch, not a leaf)
    """
    if not ref.startswith("tokens."):
        return False
    parts = ref.split(".")[1:]  # strip 'tokens'
    if not parts:
        return False

    cursor: Any = tokens
    for seg in parts:
        if not isinstance(cursor, dict):
            return False
        if seg not in cursor:
            return False
        cursor = cursor[seg]

    # The final cursor must be a leaf (string/number), not a branch (dict)
    return not isinstance(cursor, dict)


def validate_token_refs(schema: dict, tokens: dict) -> tuple[int, list[tuple[str, str]]]:
    """Walk the schema; for each token ref, check it exists in tokens dict.

    Returns:
        (valid_count, invalid_refs) where invalid_refs is a list of
        (json-path, ref) tuples for refs that didn't resolve.
    """
    valid = 0
    invalid: list[tuple[str, str]] = []
    for path, ref in collect_token_refs(schema):
        if path_exists_in(ref, tokens):
            valid += 1
        else:
            invalid.append((path, ref))
    return valid, invalid


def invalid_ref_pct(valid_count: int, invalid_count: int) -> float:
    """Compute % of refs that were invalid.

    Returns 0.0 when there are no refs at all (avoids divide-by-zero).
    """
    total = valid_count + invalid_count
    if total == 0:
        return 0.0
    return round((invalid_count / total) * 100.0, 2)


class SchemaValidationError(Exception):
    """Raised when a schema's token refs are systematically invalid (>50%)."""
    pass


def validate_cta_hierarchy(page: dict, cta: dict) -> list[str]:
    """Count Button variants in the page tree; return human-readable error
    strings for hierarchy violations. Empty list = no violations.

    Form pages skip the primary-min check because the <Form> component
    contains an implicit submit button that may not be a top-level Button
    node.
    """
    page_type = page.get("page_type", "")
    counts: dict[str, int] = {}

    def walk(node):
        if not isinstance(node, dict):
            return
        if node.get("type") == "Button":
            variant = (node.get("props") or {}).get("variant", "primary")
            counts[variant] = counts.get(variant, 0) + 1
        for child in (node.get("children") or []):
            walk(child)
        if node.get("else"):
            for child in node["else"]:
                walk(child)

    walk(page.get("root", {}))

    errors: list[str] = []

    primary_count = counts.get(cta["primary"]["variant"], 0)
    primary_max = cta["primary"]["max_per_page"]
    primary_min = cta["primary"]["min_per_page"]

    def contains_form(node):
        if not isinstance(node, dict):
            return False
        if node.get("type") == "Form":
            return True
        for c in (node.get("children") or []):
            if contains_form(c):
                return True
        return False

    page_supplies_form = page_type == "form" or contains_form(page.get("root", {}))

    if primary_max is not None and primary_count > primary_max:
        errors.append(
            f"page has {primary_count} primary CTAs (variant='{cta['primary']['variant']}'); "
            f"max is {primary_max}"
        )
    if not page_supplies_form and primary_count < primary_min:
        errors.append(
            f"page has {primary_count} primary CTAs; min is {primary_min} "
            f"(variant='{cta['primary']['variant']}')"
        )

    sec_count = counts.get(cta["secondary"]["variant"], 0)
    sec_max = cta["secondary"]["max_per_page"]
    if sec_max is not None and sec_count > sec_max:
        errors.append(
            f"page has {sec_count} secondary CTAs (variant='{cta['secondary']['variant']}'); "
            f"max is {sec_max}"
        )

    return errors


def validate_progressive_disclosure(page: dict) -> list[str]:
    """Flag pages with too-flat layouts.

    Rule: a Form with > 7 user-editable fields must be partitioned into
    an Accordion or Tabs (or TabPanelWithDeepLink) container. Counts
    fields not nested inside such a container.
    """
    FIELD_TYPES = {
        "Input", "Textarea", "Select", "Checkbox",
        "DatePicker", "DateRangePicker", "MultiSelect",
    }
    PARTITION_TYPES = {"Accordion", "Tabs", "TabPanelWithDeepLink"}

    errors: list[str] = []

    def find_forms(node):
        if not isinstance(node, dict):
            return
        if node.get("type") == "Form":
            yield node
        for c in (node.get("children") or []):
            yield from find_forms(c)

    def count_unpartitioned_fields(node) -> int:
        if not isinstance(node, dict):
            return 0
        node_type = node.get("type")
        # Fields inside an Accordion / Tabs / TabPanelWithDeepLink subtree are
        # considered partitioned and excluded from the flat-form count.
        if node_type in PARTITION_TYPES:
            return 0
        n = 1 if node_type in FIELD_TYPES else 0
        for c in (node.get("children") or []):
            n += count_unpartitioned_fields(c)
        return n

    for form in find_forms(page.get("root", {})):
        unpartitioned = count_unpartitioned_fields(form)
        if unpartitioned > 7:
            errors.append(
                f"Form has {unpartitioned} fields directly in a flat container; "
                f"wrap groups in Accordion or Tabs for progressive disclosure"
            )

    return errors
