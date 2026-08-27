"""Decision evaluator — evaluates decision tables and decision graphs.

Supports all 6 DMN hit policies:
  U (Unique)   — exactly one rule matches
  F (First)    — first matching rule wins
  A (Any)      — all matching must agree on output
  P (Priority) — all matching, output with highest priority
  C (Collect)  — collect all matching outputs
  R (Rule order) — all matching, in rule definition order

Cell matching:
  - Wildcard ("-" or empty) — matches anything
  - Exact value — string or number equality
  - Range — [1..100], (0..50], etc.
  - List — "A", "B", "C" (comma-separated) or [1, 2, 3]
  - Comparison — "> 100", "<= 50", "!= 0"
  - Negation — "not(X)", "not(1, 2, 3)"
  - String operations — via FEEL-lite expressions
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any

from runtime.feel_lite.tokenizer import tokenize
from runtime.feel_lite.parser import parse, ParseError
from runtime.feel_lite.evaluator import evaluate, match_value
from runtime.feel_lite.ast_nodes import (
    ASTNode,
    WildcardExpr,
    ComparisonExpr,
    Identifier,
)

logger = logging.getLogger(__name__)


def evaluate_decision_table(table_dict: dict, inputs: dict) -> dict:
    """Evaluate a decision table definition against a set of inputs.

    Args:
        table_dict: Decision table definition matching the TS DecisionTableDefinition type.
            Expected shape:
            {
                "id": str,
                "name": str,
                "hitPolicy": "U" | "F" | "A" | "P" | "C" | "R",
                "inputs": [{"id": str, "label": str, "expression": str, "type": str}],
                "outputs": [{"id": str, "label": str, "name": str, "type": str}],
                "rules": [{
                    "id": str,
                    "inputEntries": [str],     # cell expressions per input column
                    "outputEntries": [str|Any], # cell values per output column
                    "annotation": str?
                }]
            }
        inputs: dict of input variable name -> value

    Returns:
        {
            "hit_policy": str,
            "matched_rule_ids": list[str],
            "outputs": dict | list[dict],
            "result": Any,
        }
    """
    start_time = time.monotonic()

    hit_policy = table_dict.get("hitPolicy", "U").upper()
    input_cols = table_dict.get("inputs", [])
    output_cols = table_dict.get("outputs", [])
    rules = table_dict.get("rules", [])

    # Resolve input values from expressions
    input_values = []
    for col in input_cols:
        expr = col.get("expression", col.get("label", ""))
        value = _resolve_input_value(expr, inputs)
        input_values.append(value)

    # Evaluate each rule
    matched_rules: list[dict] = []

    for rule in rules:
        input_entries = rule.get("inputEntries", [])
        if _rule_matches(input_values, input_entries, inputs):
            output_dict = _extract_outputs(rule, output_cols, inputs)
            matched_rules.append({
                "id": rule.get("id", ""),
                "outputs": output_dict,
                "priority": rule.get("priority"),
                "annotation": rule.get("annotation"),
            })

    # Apply hit policy
    matched_rule_ids = [r["id"] for r in matched_rules]
    result = _apply_hit_policy(hit_policy, matched_rules, output_cols)

    duration_ms = int((time.monotonic() - start_time) * 1000)

    return {
        "hit_policy": hit_policy,
        "matched_rule_ids": matched_rule_ids,
        "outputs": result.get("outputs"),
        "result": result.get("result"),
        "duration_ms": duration_ms,
    }


def evaluate_decision_graph(graph_dict: dict, inputs: dict) -> dict:
    """Evaluate a decision graph with topological sort and context propagation.

    Args:
        graph_dict: Decision graph definition with nodes and edges.
            {
                "nodes": [{
                    "id": str,
                    "type": "decision" | "input" | "knowledge",
                    "decisionTable": dict?,  # DecisionTableDefinition
                    "expression": str?,       # FEEL expression for input/knowledge nodes
                }],
                "edges": [{"source": str, "target": str}]
            }
        inputs: Initial input context.

    Returns:
        {"outputs": dict, "node_results": dict[str, Any]}
    """
    nodes = graph_dict.get("nodes", [])
    edges = graph_dict.get("edges", [])

    # Build adjacency and in-degree maps
    node_map = {n["id"]: n for n in nodes}
    in_degree: dict[str, int] = defaultdict(int)
    dependents: dict[str, list[str]] = defaultdict(list)

    for n in nodes:
        in_degree.setdefault(n["id"], 0)

    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source and target:
            in_degree[target] = in_degree.get(target, 0) + 1
            dependents[source].append(target)

    # Topological sort (Kahn's algorithm)
    queue = [nid for nid, deg in in_degree.items() if deg == 0]
    execution_order: list[str] = []

    while queue:
        nid = queue.pop(0)
        execution_order.append(nid)
        for dep in dependents.get(nid, []):
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                queue.append(dep)

    # Execute nodes in topological order, propagating context
    context = dict(inputs)
    node_results: dict[str, Any] = {}

    for nid in execution_order:
        node = node_map.get(nid)
        if not node:
            continue

        node_type = node.get("type", "decision")

        if node_type == "input":
            # Input nodes just pass through values or evaluate an expression
            expr = node.get("expression")
            if expr:
                try:
                    from runtime.feel_lite.evaluator import evaluate_expression
                    val = evaluate_expression(expr, context)
                    node_results[nid] = val
                    context[nid] = val
                except Exception:
                    node_results[nid] = context.get(nid)
            else:
                node_results[nid] = context.get(nid)

        elif node_type == "decision":
            dt = node.get("decisionTable")
            if dt:
                result = evaluate_decision_table(dt, context)
                node_results[nid] = result
                # Merge outputs into context for downstream nodes
                outputs = result.get("outputs")
                if isinstance(outputs, dict):
                    context.update(outputs)
                    context[nid] = outputs
                elif isinstance(outputs, list) and outputs:
                    context[nid] = outputs
                else:
                    context[nid] = result.get("result")
            else:
                # Expression-based decision node
                expr = node.get("expression")
                if expr:
                    from runtime.feel_lite.evaluator import evaluate_expression
                    val = evaluate_expression(expr, context)
                    node_results[nid] = val
                    context[nid] = val

        elif node_type == "knowledge":
            # Knowledge / business knowledge model — evaluate expression
            expr = node.get("expression")
            if expr:
                from runtime.feel_lite.evaluator import evaluate_expression
                val = evaluate_expression(expr, context)
                node_results[nid] = val
                context[nid] = val

    return {
        "outputs": context,
        "node_results": node_results,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_input_value(expression: str, inputs: dict) -> Any:
    """Resolve an input column expression to a value from the inputs dict.

    The expression is typically a variable name (e.g., "age") or a dotted path
    (e.g., "customer.age"), or a FEEL expression.
    """
    expr = expression.strip()
    if not expr:
        return None

    # Direct variable lookup
    if expr in inputs:
        return inputs[expr]

    # Dotted path
    if "." in expr and not any(c in expr for c in "()+-*/<>=!"):
        parts = expr.split(".")
        val = inputs
        for part in parts:
            if isinstance(val, dict):
                val = val.get(part)
            else:
                return None
        return val

    # FEEL expression
    try:
        from runtime.feel_lite.evaluator import evaluate_expression
        return evaluate_expression(expr, inputs)
    except Exception:
        return inputs.get(expr)


def _rule_matches(
    input_values: list[Any],
    input_entries: list[str],
    ctx: dict,
) -> bool:
    """Check if a rule's input entries all match against the input values."""
    for i, entry_str in enumerate(input_entries):
        if i >= len(input_values):
            break

        value = input_values[i]
        entry = str(entry_str).strip() if entry_str is not None else ""

        if not _cell_matches(value, entry, ctx):
            return False

    return True


def _cell_matches(value: Any, cell_expr: str, ctx: dict) -> bool:
    """Check if a single cell expression matches a value.

    Supports: wildcard, exact, range, list, comparison, negation, FEEL expressions.
    """
    # Empty or wildcard
    if not cell_expr or cell_expr == "-":
        return True

    # Try parsing as FEEL expression
    try:
        tokens = tokenize(cell_expr)
        ast = parse(tokens)
        return match_value(value, ast, ctx)
    except (ParseError, Exception):
        pass

    # Fallback: simple string comparison
    return _fuzzy_equal(value, cell_expr)


def _extract_outputs(
    rule: dict,
    output_cols: list[dict],
    ctx: dict,
) -> dict:
    """Extract output values from a matched rule."""
    output_entries = rule.get("outputEntries", [])
    result: dict[str, Any] = {}

    for i, col in enumerate(output_cols):
        col_name = col.get("name", col.get("label", f"output_{i}"))
        if i < len(output_entries):
            raw = output_entries[i]
            result[col_name] = _coerce_output(raw, col.get("type"), ctx)
        else:
            result[col_name] = None

    return result


def _coerce_output(raw: Any, type_hint: str | None, ctx: dict) -> Any:
    """Coerce an output entry value to the appropriate type."""
    if raw is None:
        return None

    if isinstance(raw, (int, float, bool)):
        return raw

    s = str(raw).strip()
    if not s:
        return None

    # Try to evaluate as FEEL expression
    try:
        from runtime.feel_lite.evaluator import evaluate_expression
        return evaluate_expression(s, ctx)
    except Exception:
        pass

    # Type coercion based on hint
    if type_hint:
        t = type_hint.lower()
        if t in ("number", "integer", "int", "float", "double"):
            try:
                return float(s) if "." in s else int(s)
            except ValueError:
                pass
        if t in ("boolean", "bool"):
            return s.lower() in ("true", "1", "yes")

    # Try numeric
    try:
        return float(s) if "." in s else int(s)
    except ValueError:
        pass

    # Remove quotes if present
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]

    return s


def _apply_hit_policy(
    policy: str,
    matched_rules: list[dict],
    output_cols: list[dict],
) -> dict:
    """Apply hit policy to matched rules and return the final output."""

    if not matched_rules:
        return {"outputs": {}, "result": None}

    # U — Unique: exactly one rule should match
    if policy == "U":
        if len(matched_rules) > 1:
            logger.warning(
                "Hit policy U violated: %d rules matched, expected 1",
                len(matched_rules),
            )
        return {
            "outputs": matched_rules[0]["outputs"],
            "result": matched_rules[0]["outputs"],
        }

    # F — First: return first matching rule
    if policy == "F":
        return {
            "outputs": matched_rules[0]["outputs"],
            "result": matched_rules[0]["outputs"],
        }

    # A — Any: all matching must agree on output
    if policy == "A":
        first_output = matched_rules[0]["outputs"]
        for rule in matched_rules[1:]:
            if rule["outputs"] != first_output:
                logger.warning(
                    "Hit policy A violated: rules disagree on output. "
                    "Rule %s: %s vs Rule %s: %s",
                    matched_rules[0]["id"],
                    first_output,
                    rule["id"],
                    rule["outputs"],
                )
                break
        return {
            "outputs": first_output,
            "result": first_output,
        }

    # P — Priority: all matching, return output with highest priority
    if policy == "P":
        # Sort by priority (lower number = higher priority, or by output_cols order)
        sorted_rules = sorted(
            matched_rules,
            key=lambda r: r.get("priority") if r.get("priority") is not None else 999,
        )
        return {
            "outputs": sorted_rules[0]["outputs"],
            "result": sorted_rules[0]["outputs"],
        }

    # C — Collect: collect all matching outputs
    if policy == "C":
        all_outputs = [r["outputs"] for r in matched_rules]

        # Check for aggregation suffix (C+, C<, C>, C#)
        # For basic C, just return the list
        return {
            "outputs": all_outputs,
            "result": all_outputs,
        }

    # R — Rule order: all matching, in rule definition order
    if policy == "R":
        all_outputs = [r["outputs"] for r in matched_rules]
        return {
            "outputs": all_outputs,
            "result": all_outputs,
        }

    # Default fallback — treat as First
    logger.warning("Unknown hit policy '%s', falling back to First", policy)
    return {
        "outputs": matched_rules[0]["outputs"],
        "result": matched_rules[0]["outputs"],
    }


def _fuzzy_equal(a: Any, b: Any) -> bool:
    """Compare two values with type coercion."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    try:
        return float(a) == float(b)
    except (ValueError, TypeError):
        pass
    return str(a).lower().strip().strip("'\"") == str(b).lower().strip().strip("'\"")
