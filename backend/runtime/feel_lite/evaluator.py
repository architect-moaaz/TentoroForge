"""FEEL-lite AST evaluator with built-in functions.

Provides:
- evaluate(node, ctx) -> Any
- evaluate_expression(expr_str, ctx) -> Any  (convenience)
- match_value(value, pattern_node, ctx) -> bool  (for decision table cell matching)
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from typing import Any

from runtime.feel_lite.tokenizer import tokenize
from runtime.feel_lite.parser import parse, ParseError
from runtime.feel_lite.ast_nodes import (
    ASTNode,
    BetweenExpr,
    BinaryExpr,
    BooleanLiteral,
    ComparisonExpr,
    FunctionCall,
    Identifier,
    IfExpr,
    InExpr,
    ListExpr,
    LogicalExpr,
    MemberExpr,
    NotExpr,
    NullLiteral,
    NumberLiteral,
    RangeExpr,
    StringLiteral,
    UnaryExpr,
    WildcardExpr,
)

# ---------------------------------------------------------------------------
# Built-in functions
# ---------------------------------------------------------------------------

BUILTIN_FUNCTIONS: dict[str, Any] = {}


def _register(name: str):
    def decorator(fn):
        BUILTIN_FUNCTIONS[name] = fn
        return fn
    return decorator


@_register("sum")
def _fn_sum(args: list) -> float:
    if len(args) == 1 and isinstance(args[0], list):
        return sum(float(x) for x in args[0])
    return sum(float(x) for x in args)


@_register("count")
def _fn_count(args: list) -> int:
    if len(args) == 1 and isinstance(args[0], list):
        return len(args[0])
    return len(args)


@_register("min")
def _fn_min(args: list) -> Any:
    if len(args) == 1 and isinstance(args[0], list):
        return min(args[0])
    return min(args)


@_register("max")
def _fn_max(args: list) -> Any:
    if len(args) == 1 and isinstance(args[0], list):
        return max(args[0])
    return max(args)


@_register("avg")
def _fn_avg(args: list) -> float:
    items = args[0] if len(args) == 1 and isinstance(args[0], list) else args
    return sum(float(x) for x in items) / len(items) if items else 0


@_register("contains")
def _fn_contains(args: list) -> bool:
    if len(args) < 2:
        return False
    return str(args[1]) in str(args[0])


@_register("starts_with")
def _fn_starts_with(args: list) -> bool:
    if len(args) < 2:
        return False
    return str(args[0]).startswith(str(args[1]))


@_register("starts with")
def _fn_starts_with_space(args: list) -> bool:
    return _fn_starts_with(args)


@_register("ends_with")
def _fn_ends_with(args: list) -> bool:
    if len(args) < 2:
        return False
    return str(args[0]).endswith(str(args[1]))


@_register("ends with")
def _fn_ends_with_space(args: list) -> bool:
    return _fn_ends_with(args)


@_register("matches")
def _fn_matches(args: list) -> bool:
    if len(args) < 2:
        return False
    try:
        return bool(re.search(str(args[1]), str(args[0])))
    except re.error:
        return False


@_register("string")
def _fn_string(args: list) -> str:
    if not args:
        return ""
    return str(args[0])


@_register("number")
def _fn_number(args: list) -> float | None:
    if not args:
        return None
    try:
        return float(args[0])
    except (ValueError, TypeError):
        return None


@_register("date")
def _fn_date(args: list) -> date | None:
    if not args:
        return None
    try:
        if isinstance(args[0], (date, datetime)):
            return args[0] if isinstance(args[0], date) else args[0].date()
        return date.fromisoformat(str(args[0]))
    except (ValueError, TypeError):
        return None


@_register("now")
def _fn_now(args: list) -> datetime:
    return datetime.now()


@_register("duration")
def _fn_duration(args: list) -> timedelta | None:
    if not args:
        return None
    s = str(args[0])
    # Simple ISO 8601 duration parsing: P[n]D, PT[n]H[n]M[n]S
    try:
        days = 0
        hours = 0
        minutes = 0
        seconds = 0
        m = re.match(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", s)
        if m:
            days = int(m.group(1) or 0)
            hours = int(m.group(2) or 0)
            minutes = int(m.group(3) or 0)
            seconds = int(m.group(4) or 0)
        return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    except Exception:
        return None


@_register("abs")
def _fn_abs(args: list) -> float:
    if not args:
        return 0
    return abs(float(args[0]))


@_register("floor")
def _fn_floor(args: list) -> int:
    if not args:
        return 0
    return math.floor(float(args[0]))


@_register("ceiling")
def _fn_ceiling(args: list) -> int:
    if not args:
        return 0
    return math.ceil(float(args[0]))


@_register("round")
def _fn_round(args: list) -> float:
    if not args:
        return 0
    precision = int(args[1]) if len(args) > 1 else 0
    return round(float(args[0]), precision)


@_register("upper_case")
def _fn_upper_case(args: list) -> str:
    if not args:
        return ""
    return str(args[0]).upper()


@_register("lower_case")
def _fn_lower_case(args: list) -> str:
    if not args:
        return ""
    return str(args[0]).lower()


@_register("substring")
def _fn_substring(args: list) -> str:
    if len(args) < 2:
        return ""
    s = str(args[0])
    start = int(args[1])
    length = int(args[2]) if len(args) > 2 else None
    if length is not None:
        return s[start : start + length]
    return s[start:]


@_register("string_length")
def _fn_string_length(args: list) -> int:
    if not args:
        return 0
    return len(str(args[0]))


@_register("list_contains")
def _fn_list_contains(args: list) -> bool:
    if len(args) < 2:
        return False
    lst = args[0]
    if not isinstance(lst, list):
        return False
    return args[1] in lst


@_register("append")
def _fn_append(args: list) -> list:
    if not args:
        return []
    lst = list(args[0]) if isinstance(args[0], list) else [args[0]]
    for item in args[1:]:
        lst.append(item)
    return lst


@_register("flatten")
def _fn_flatten(args: list) -> list:
    if not args:
        return []
    result: list = []
    for item in (args[0] if isinstance(args[0], list) else args):
        if isinstance(item, list):
            result.extend(_fn_flatten([item]))
        else:
            result.append(item)
    return result


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

def evaluate(node: ASTNode, ctx: dict) -> Any:
    """Evaluate an AST node against a context dictionary."""

    if isinstance(node, NumberLiteral):
        return node.value

    if isinstance(node, StringLiteral):
        return node.value

    if isinstance(node, BooleanLiteral):
        return node.value

    if isinstance(node, NullLiteral):
        return None

    if isinstance(node, WildcardExpr):
        return True  # Wildcard always matches

    if isinstance(node, Identifier):
        # Support dotted names stored as a single identifier (e.g., "person.age")
        if "." in node.name:
            parts = node.name.split(".")
            val = ctx
            for part in parts:
                if isinstance(val, dict):
                    val = val.get(part)
                else:
                    return None
            return val
        return ctx.get(node.name)

    if isinstance(node, UnaryExpr):
        operand = evaluate(node.operand, ctx)
        if node.operator == "-":
            return -_to_number(operand)
        return _to_number(operand)

    if isinstance(node, BinaryExpr):
        left = evaluate(node.left, ctx)
        right = evaluate(node.right, ctx)
        return _eval_binary(node.operator, left, right)

    if isinstance(node, ComparisonExpr):
        left = evaluate(node.left, ctx)
        right = evaluate(node.right, ctx)
        return _eval_comparison(node.operator, left, right)

    if isinstance(node, LogicalExpr):
        left = evaluate(node.left, ctx)
        if node.operator == "or":
            if left:
                return True
            return bool(evaluate(node.right, ctx))
        elif node.operator == "and":
            if not left:
                return False
            return bool(evaluate(node.right, ctx))
        return False

    if isinstance(node, NotExpr):
        return not evaluate(node.operand, ctx)

    if isinstance(node, IfExpr):
        condition = evaluate(node.condition, ctx)
        if condition:
            return evaluate(node.then_branch, ctx)
        elif node.else_branch is not None:
            return evaluate(node.else_branch, ctx)
        return None

    if isinstance(node, InExpr):
        value = evaluate(node.value, ctx)
        return _eval_in(value, node.target, ctx)

    if isinstance(node, BetweenExpr):
        value = _to_number(evaluate(node.value, ctx))
        low = _to_number(evaluate(node.low, ctx))
        high = _to_number(evaluate(node.high, ctx))
        return low <= value <= high

    if isinstance(node, RangeExpr):
        # Evaluating a range as a standalone expression returns a dict descriptor
        return {
            "type": "range",
            "low": evaluate(node.low, ctx),
            "high": evaluate(node.high, ctx),
            "low_inclusive": node.low_inclusive,
            "high_inclusive": node.high_inclusive,
        }

    if isinstance(node, ListExpr):
        return [evaluate(el, ctx) for el in node.elements]

    if isinstance(node, FunctionCall):
        # Evaluate arguments
        args = [evaluate(arg, ctx) for arg in node.arguments]
        # Check built-in functions
        fn = BUILTIN_FUNCTIONS.get(node.name)
        if fn:
            return fn(args)
        # Check context for user-defined functions
        ctx_fn = ctx.get(node.name)
        if callable(ctx_fn):
            return ctx_fn(*args)
        raise ValueError(f"Unknown function: {node.name}")

    if isinstance(node, MemberExpr):
        obj = evaluate(node.object, ctx)
        if isinstance(obj, dict):
            return obj.get(node.property)
        if hasattr(obj, node.property):
            return getattr(obj, node.property)
        return None

    raise ValueError(f"Unknown AST node type: {type(node).__name__}")


def evaluate_expression(expr: str, ctx: dict) -> Any:
    """Convenience: tokenize, parse, and evaluate a FEEL-lite expression."""
    tokens = tokenize(expr)
    ast = parse(tokens)
    return evaluate(ast, ctx)


def match_value(value: Any, pattern_node: ASTNode, ctx: dict) -> bool:
    """Match a value against a pattern AST node (for decision table cell matching).

    Supports:
    - WildcardExpr: always matches
    - RangeExpr: check if value is in range
    - ListExpr: check if value matches any element
    - ComparisonExpr with '?' placeholder: substitute value for '?'
    - NotExpr: negation of match
    - StringLiteral / NumberLiteral / BooleanLiteral: exact match
    - Identifier: resolve from context, then compare
    """
    if isinstance(pattern_node, WildcardExpr):
        return True

    if isinstance(pattern_node, RangeExpr):
        low = _to_comparable(evaluate(pattern_node.low, ctx))
        high = _to_comparable(evaluate(pattern_node.high, ctx))
        v = _to_comparable(value)
        if v is None or low is None or high is None:
            return False
        in_low = low <= v if pattern_node.low_inclusive else low < v
        in_high = v <= high if pattern_node.high_inclusive else v < high
        return in_low and in_high

    if isinstance(pattern_node, ListExpr):
        return any(match_value(value, el, ctx) for el in pattern_node.elements)

    if isinstance(pattern_node, ComparisonExpr):
        # If left side is the '?' placeholder, substitute with value
        if isinstance(pattern_node.left, Identifier) and pattern_node.left.name == "?":
            right = evaluate(pattern_node.right, ctx)
            return _eval_comparison(pattern_node.operator, value, right)
        else:
            left = evaluate(pattern_node.left, ctx)
            right = evaluate(pattern_node.right, ctx)
            return _eval_comparison(pattern_node.operator, left, right)

    if isinstance(pattern_node, NotExpr):
        return not match_value(value, pattern_node.operand, ctx)

    if isinstance(pattern_node, InExpr):
        v = evaluate(pattern_node.value, ctx) if not isinstance(pattern_node.value, Identifier) or pattern_node.value.name != "?" else value
        return _eval_in(v, pattern_node.target, ctx)

    if isinstance(pattern_node, BetweenExpr):
        v = _to_number(value)
        low = _to_number(evaluate(pattern_node.low, ctx))
        high = _to_number(evaluate(pattern_node.high, ctx))
        return low <= v <= high

    # Literal values — exact match
    if isinstance(pattern_node, NumberLiteral):
        return _fuzzy_equal(value, pattern_node.value)

    if isinstance(pattern_node, StringLiteral):
        return str(value).lower() == pattern_node.value.lower()

    if isinstance(pattern_node, BooleanLiteral):
        return bool(value) == pattern_node.value

    if isinstance(pattern_node, NullLiteral):
        return value is None

    if isinstance(pattern_node, Identifier):
        # Could be a variable reference or a string comparison
        resolved = ctx.get(pattern_node.name, pattern_node.name)
        return _fuzzy_equal(value, resolved)

    # Fallback: evaluate the pattern and compare
    try:
        pattern_val = evaluate(pattern_node, ctx)
        return _fuzzy_equal(value, pattern_val)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_number(val: Any) -> float:
    """Coerce value to a number."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _to_comparable(val: Any) -> Any:
    """Coerce value for comparison purposes."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val)
        except ValueError:
            return val
    return val


def _fuzzy_equal(a: Any, b: Any) -> bool:
    """Compare two values with type coercion."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    # Try numeric comparison
    try:
        return float(a) == float(b)
    except (ValueError, TypeError):
        pass
    # String comparison (case-insensitive)
    return str(a).lower() == str(b).lower()


def _eval_binary(op: str, left: Any, right: Any) -> Any:
    """Evaluate a binary arithmetic operation."""
    if op == "+":
        # String concatenation if either side is a string
        if isinstance(left, str) or isinstance(right, str):
            return str(left if left is not None else "") + str(right if right is not None else "")
        return _to_number(left) + _to_number(right)
    if op == "-":
        return _to_number(left) - _to_number(right)
    if op == "*":
        return _to_number(left) * _to_number(right)
    if op == "/":
        r = _to_number(right)
        if r == 0:
            return None  # Division by zero
        return _to_number(left) / r
    if op == "%":
        r = _to_number(right)
        if r == 0:
            return None
        return _to_number(left) % r
    if op == "^":
        return _to_number(left) ** _to_number(right)
    return None


def _eval_comparison(op: str, left: Any, right: Any) -> bool:
    """Evaluate a comparison operation."""
    if op == "=":
        return _fuzzy_equal(left, right)
    if op == "!=":
        return not _fuzzy_equal(left, right)

    # Numeric comparisons
    try:
        l = float(left) if not isinstance(left, (date, datetime)) else left
        r = float(right) if not isinstance(right, (date, datetime)) else right
    except (ValueError, TypeError):
        # Fall back to string comparison
        l = str(left) if left is not None else ""
        r = str(right) if right is not None else ""

    if op == "<":
        return l < r
    if op == "<=":
        return l <= r
    if op == ">":
        return l > r
    if op == ">=":
        return l >= r
    return False


def _eval_in(value: Any, target: ASTNode, ctx: dict) -> bool:
    """Evaluate 'value in target' where target can be a list, range, or expression."""
    if isinstance(target, ListExpr):
        evaluated = [evaluate(el, ctx) for el in target.elements]
        return any(_fuzzy_equal(value, el) for el in evaluated)

    if isinstance(target, RangeExpr):
        return match_value(value, target, ctx)

    # Evaluate target and check membership
    target_val = evaluate(target, ctx)
    if isinstance(target_val, list):
        return any(_fuzzy_equal(value, el) for el in target_val)
    if isinstance(target_val, dict) and target_val.get("type") == "range":
        low = target_val["low"]
        high = target_val["high"]
        v = _to_comparable(value)
        l = _to_comparable(low)
        h = _to_comparable(high)
        if v is None or l is None or h is None:
            return False
        in_low = l <= v if target_val.get("low_inclusive", True) else l < v
        in_high = v <= h if target_val.get("high_inclusive", True) else v < h
        return in_low and in_high
    if isinstance(target_val, str):
        return str(value) in target_val
    return _fuzzy_equal(value, target_val)
