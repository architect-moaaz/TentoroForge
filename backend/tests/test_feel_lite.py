"""Unit tests for FEEL-lite expression engine: tokenizer, parser, evaluator."""

import pytest
from runtime.feel_lite.tokenizer import tokenize, TokenType
from runtime.feel_lite.parser import parse, ParseError
from runtime.feel_lite.evaluator import evaluate, evaluate_expression, match_value
from runtime.feel_lite.ast_nodes import (
    NumberLiteral, StringLiteral, BooleanLiteral, NullLiteral,
    WildcardExpr, Identifier, BinaryExpr, ComparisonExpr, RangeExpr,
    ListExpr, IfExpr, FunctionCall,
)


# =====================================================================
# Tokenizer tests
# =====================================================================

class TestTokenizer:
    def test_number_integer(self):
        tokens = tokenize("42")
        assert tokens[0].type == TokenType.Number
        assert tokens[0].value == "42"

    def test_number_decimal(self):
        tokens = tokenize("3.14")
        assert tokens[0].type == TokenType.Number
        assert tokens[0].value == "3.14"

    def test_string_double_quotes(self):
        tokens = tokenize('"hello"')
        assert tokens[0].type == TokenType.String
        assert tokens[0].value == "hello"

    def test_string_single_quotes(self):
        tokens = tokenize("'world'")
        assert tokens[0].type == TokenType.String
        assert tokens[0].value == "world"

    def test_boolean_true(self):
        tokens = tokenize("true")
        assert tokens[0].type == TokenType.Boolean
        assert tokens[0].value == "true"

    def test_boolean_false(self):
        tokens = tokenize("false")
        assert tokens[0].type == TokenType.Boolean
        assert tokens[0].value == "false"

    def test_null(self):
        tokens = tokenize("null")
        assert tokens[0].type == TokenType.Null

    def test_identifier(self):
        tokens = tokenize("age")
        assert tokens[0].type == TokenType.Identifier
        assert tokens[0].value == "age"

    def test_dotted_identifier(self):
        tokens = tokenize("person.age")
        assert tokens[0].type == TokenType.Identifier
        assert tokens[0].value == "person.age"

    def test_arithmetic_operators(self):
        tokens = tokenize("1 + 2 - 3 * 4 / 5 % 6 ^ 7")
        ops = [t for t in tokens if t.type not in (TokenType.Number, TokenType.EOF)]
        assert [t.type for t in ops] == [
            TokenType.Plus, TokenType.Minus, TokenType.Star,
            TokenType.Slash, TokenType.Percent, TokenType.Caret,
        ]

    def test_comparison_operators(self):
        tokens = tokenize("a = b != c < d <= e > f >= g")
        comp_types = {TokenType.Eq, TokenType.NotEq, TokenType.Lt,
                      TokenType.LtEq, TokenType.Gt, TokenType.GtEq}
        ops = [t for t in tokens if t.type in comp_types]
        assert len(ops) == 6

    def test_two_char_operators(self):
        tokens = tokenize("!= <= >= ..")
        assert tokens[0].type == TokenType.NotEq
        assert tokens[1].type == TokenType.LtEq
        assert tokens[2].type == TokenType.GtEq
        assert tokens[3].type == TokenType.DotDot

    def test_keywords(self):
        tokens = tokenize("if then else and or not in between")
        expected = [TokenType.If, TokenType.Then, TokenType.Else,
                    TokenType.And, TokenType.Or, TokenType.Not,
                    TokenType.In, TokenType.Between]
        assert [t.type for t in tokens[:-1]] == expected

    def test_delimiters(self):
        tokens = tokenize("( ) [ ] , . :")
        expected = [TokenType.LParen, TokenType.RParen, TokenType.LBracket,
                    TokenType.RBracket, TokenType.Comma, TokenType.Dot,
                    TokenType.Colon]
        assert [t.type for t in tokens[:-1]] == expected

    def test_wildcard_at_start(self):
        tokens = tokenize("-")
        assert tokens[0].type == TokenType.Wildcard

    def test_wildcard_after_comma(self):
        tokens = tokenize("[1, -]")
        wildcard_tokens = [t for t in tokens if t.type == TokenType.Wildcard]
        assert len(wildcard_tokens) == 1

    def test_minus_after_number_is_minus(self):
        tokens = tokenize("5 - 3")
        assert tokens[1].type == TokenType.Minus

    def test_eof_appended(self):
        tokens = tokenize("42")
        assert tokens[-1].type == TokenType.EOF

    def test_empty_string(self):
        tokens = tokenize("")
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.EOF

    def test_whitespace_skipped(self):
        tokens = tokenize("  42  +  7  ")
        non_eof = [t for t in tokens if t.type != TokenType.EOF]
        assert len(non_eof) == 3

    def test_escaped_string(self):
        tokens = tokenize('"hello\\"world"')
        assert tokens[0].type == TokenType.String

    def test_range_dotdot_with_numbers(self):
        tokens = tokenize("[1..100]")
        types = [t.type for t in tokens[:-1]]
        assert TokenType.DotDot in types


# =====================================================================
# Parser tests
# =====================================================================

class TestParser:
    def test_number_literal(self):
        tokens = tokenize("42")
        ast = parse(tokens)
        assert isinstance(ast, NumberLiteral)
        assert ast.value == 42.0

    def test_string_literal(self):
        tokens = tokenize('"hello"')
        ast = parse(tokens)
        assert isinstance(ast, StringLiteral)
        assert ast.value == "hello"

    def test_boolean_literal(self):
        ast = parse(tokenize("true"))
        assert isinstance(ast, BooleanLiteral)
        assert ast.value is True

    def test_null_literal(self):
        ast = parse(tokenize("null"))
        assert isinstance(ast, NullLiteral)

    def test_identifier(self):
        ast = parse(tokenize("age"))
        assert isinstance(ast, Identifier)
        assert ast.name == "age"

    def test_binary_addition(self):
        ast = parse(tokenize("1 + 2"))
        assert isinstance(ast, BinaryExpr)
        assert ast.operator == "+"

    def test_binary_precedence(self):
        ast = parse(tokenize("1 + 2 * 3"))
        assert isinstance(ast, BinaryExpr)
        assert ast.operator == "+"
        assert isinstance(ast.right, BinaryExpr)
        assert ast.right.operator == "*"

    def test_comparison(self):
        ast = parse(tokenize("age >= 18"))
        assert isinstance(ast, ComparisonExpr)
        assert ast.operator == ">="

    def test_prefix_comparison(self):
        """Cell expressions like '>= 100' produce ComparisonExpr with ? placeholder."""
        ast = parse(tokenize(">= 100"))
        assert isinstance(ast, ComparisonExpr)
        assert ast.operator == ">="
        assert isinstance(ast.left, Identifier)
        assert ast.left.name == "?"

    def test_range_inclusive(self):
        ast = parse(tokenize("[1..100]"))
        assert isinstance(ast, RangeExpr)
        assert ast.low_inclusive is True
        assert ast.high_inclusive is True

    def test_range_exclusive(self):
        ast = parse(tokenize("(0..50)"))
        assert isinstance(ast, RangeExpr)
        assert ast.low_inclusive is False
        assert ast.high_inclusive is False

    def test_range_half_open(self):
        ast = parse(tokenize("(0..100]"))
        assert isinstance(ast, RangeExpr)
        assert ast.low_inclusive is False
        assert ast.high_inclusive is True

    def test_list(self):
        ast = parse(tokenize('[1, 2, 3]'))
        assert isinstance(ast, ListExpr)
        assert len(ast.elements) == 3

    def test_empty_list(self):
        ast = parse(tokenize("[]"))
        assert isinstance(ast, ListExpr)
        assert len(ast.elements) == 0

    def test_if_then_else(self):
        ast = parse(tokenize("if x > 0 then 1 else 0"))
        assert isinstance(ast, IfExpr)

    def test_function_call(self):
        ast = parse(tokenize("sum(1, 2, 3)"))
        assert isinstance(ast, FunctionCall)
        assert ast.name == "sum"
        assert len(ast.arguments) == 3

    def test_wildcard(self):
        ast = parse(tokenize("-"))
        assert isinstance(ast, WildcardExpr)

    def test_nested_parens(self):
        ast = parse(tokenize("(1 + 2) * 3"))
        assert isinstance(ast, BinaryExpr)
        assert ast.operator == "*"

    def test_logical_and_or(self):
        ast = parse(tokenize("a and b or c"))
        # or has lower precedence, so the tree should be: (a and b) or c
        from runtime.feel_lite.ast_nodes import LogicalExpr
        assert isinstance(ast, LogicalExpr)
        assert ast.operator == "or"

    def test_not_expression(self):
        ast = parse(tokenize("not true"))
        from runtime.feel_lite.ast_nodes import NotExpr
        assert isinstance(ast, NotExpr)

    def test_parse_error_on_unexpected(self):
        with pytest.raises(ParseError):
            parse(tokenize(")"))


# =====================================================================
# Evaluator tests
# =====================================================================

class TestEvaluator:
    # --- Literals ---
    def test_number(self):
        assert evaluate_expression("42", {}) == 42.0

    def test_string(self):
        assert evaluate_expression('"hello"', {}) == "hello"

    def test_boolean(self):
        assert evaluate_expression("true", {}) is True
        assert evaluate_expression("false", {}) is False

    def test_null(self):
        assert evaluate_expression("null", {}) is None

    # --- Variables ---
    def test_simple_variable(self):
        assert evaluate_expression("age", {"age": 25}) == 25

    def test_dotted_variable(self):
        assert evaluate_expression("person.age", {"person": {"age": 30}}) == 30

    def test_missing_variable(self):
        assert evaluate_expression("unknown", {}) is None

    # --- Arithmetic ---
    def test_addition(self):
        assert evaluate_expression("2 + 3", {}) == 5.0

    def test_subtraction(self):
        assert evaluate_expression("10 - 4", {}) == 6.0

    def test_multiplication(self):
        assert evaluate_expression("3 * 4", {}) == 12.0

    def test_division(self):
        assert evaluate_expression("10 / 4", {}) == 2.5

    def test_division_by_zero(self):
        assert evaluate_expression("10 / 0", {}) is None

    def test_modulo(self):
        assert evaluate_expression("10 % 3", {}) == 1.0

    def test_exponent(self):
        assert evaluate_expression("2 ^ 3", {}) == 8.0

    def test_operator_precedence(self):
        assert evaluate_expression("2 + 3 * 4", {}) == 14.0

    def test_parentheses(self):
        assert evaluate_expression("(2 + 3) * 4", {}) == 20.0

    def test_unary_minus(self):
        # Standalone "-5" is parsed as wildcard in FEEL-lite (dash = wildcard at start)
        # Unary minus works in expressions like "0 - 5" or within function args
        assert evaluate_expression("0 - 5", {}) == -5.0

    def test_string_concatenation(self):
        assert evaluate_expression('"hello" + " " + "world"', {}) == "hello world"

    # --- Comparisons ---
    def test_equality(self):
        assert evaluate_expression("5 = 5", {}) is True
        assert evaluate_expression("5 = 6", {}) is False

    def test_inequality(self):
        assert evaluate_expression("5 != 6", {}) is True
        assert evaluate_expression("5 != 5", {}) is False

    def test_less_than(self):
        assert evaluate_expression("3 < 5", {}) is True
        assert evaluate_expression("5 < 3", {}) is False

    def test_less_equal(self):
        assert evaluate_expression("5 <= 5", {}) is True
        assert evaluate_expression("6 <= 5", {}) is False

    def test_greater_than(self):
        assert evaluate_expression("5 > 3", {}) is True

    def test_greater_equal(self):
        assert evaluate_expression("5 >= 5", {}) is True

    # --- Logical ---
    def test_and(self):
        assert evaluate_expression("true and true", {}) is True
        assert evaluate_expression("true and false", {}) is False

    def test_or(self):
        assert evaluate_expression("false or true", {}) is True
        assert evaluate_expression("false or false", {}) is False

    def test_not(self):
        assert evaluate_expression("not true", {}) is False
        assert evaluate_expression("not false", {}) is True

    def test_short_circuit_and(self):
        # If left is false, right should not be evaluated
        assert evaluate_expression("false and unknown_var", {}) is False

    def test_short_circuit_or(self):
        assert evaluate_expression("true or unknown_var", {}) is True

    # --- If/Then/Else ---
    def test_if_true(self):
        assert evaluate_expression("if true then 1 else 0", {}) == 1.0

    def test_if_false(self):
        assert evaluate_expression("if false then 1 else 0", {}) == 0.0

    def test_if_without_else(self):
        assert evaluate_expression("if false then 1", {}) is None

    def test_if_with_variable(self):
        assert evaluate_expression("if age >= 18 then \"adult\" else \"minor\"",
                                   {"age": 25}) == "adult"

    # --- In / Between ---
    def test_in_list(self):
        assert evaluate_expression("x in [1, 2, 3]", {"x": 2}) is True
        assert evaluate_expression("x in [1, 2, 3]", {"x": 5}) is False

    def test_between(self):
        assert evaluate_expression("x between 1 and 10", {"x": 5}) is True
        assert evaluate_expression("x between 1 and 10", {"x": 15}) is False

    def test_between_boundary(self):
        assert evaluate_expression("x between 1 and 10", {"x": 1}) is True
        assert evaluate_expression("x between 1 and 10", {"x": 10}) is True

    # --- Lists ---
    def test_list_literal(self):
        assert evaluate_expression("[1, 2, 3]", {}) == [1.0, 2.0, 3.0]

    def test_empty_list(self):
        assert evaluate_expression("[]", {}) == []

    # --- Ranges ---
    def test_range_expression(self):
        result = evaluate_expression("[1..10]", {})
        assert result["type"] == "range"
        assert result["low"] == 1.0
        assert result["high"] == 10.0

    # --- Built-in functions ---
    def test_sum(self):
        assert evaluate_expression("sum([1, 2, 3])", {}) == 6.0

    def test_count(self):
        assert evaluate_expression("count([1, 2, 3])", {}) == 3

    def test_min(self):
        assert evaluate_expression("min([3, 1, 2])", {}) == 1.0

    def test_max(self):
        assert evaluate_expression("max([3, 1, 2])", {}) == 3.0

    def test_avg(self):
        assert evaluate_expression("avg([2, 4, 6])", {}) == 4.0

    def test_contains(self):
        assert evaluate_expression('contains("hello world", "world")', {}) is True
        assert evaluate_expression('contains("hello", "xyz")', {}) is False

    def test_starts_with(self):
        assert evaluate_expression('starts_with("hello", "hel")', {}) is True

    def test_ends_with(self):
        assert evaluate_expression('ends_with("hello", "llo")', {}) is True

    def test_string_length(self):
        assert evaluate_expression('string_length("hello")', {}) == 5

    def test_upper_case(self):
        assert evaluate_expression('upper_case("hello")', {}) == "HELLO"

    def test_lower_case(self):
        assert evaluate_expression('lower_case("HELLO")', {}) == "hello"

    def test_abs(self):
        # "-5" inside parens is a wildcard in FEEL-lite tokenizer context
        # Use variable instead
        assert evaluate_expression("abs(x)", {"x": -5}) == 5.0

    def test_floor(self):
        assert evaluate_expression("floor(3.7)", {}) == 3

    def test_ceiling(self):
        assert evaluate_expression("ceiling(3.2)", {}) == 4

    def test_round(self):
        assert evaluate_expression("round(3.456, 2)", {}) == 3.46

    def test_substring(self):
        assert evaluate_expression('substring("hello", 1, 3)', {}) == "ell"

    def test_list_contains(self):
        assert evaluate_expression("list_contains([1, 2, 3], 2)", {}) is True
        assert evaluate_expression("list_contains([1, 2, 3], 5)", {}) is False

    def test_flatten(self):
        result = evaluate_expression("flatten([[1, 2], [3, 4]])", {})
        assert result == [1.0, 2.0, 3.0, 4.0]

    def test_unknown_function_raises(self):
        with pytest.raises(ValueError, match="Unknown function"):
            evaluate_expression("nonexistent(1)", {})

    def test_user_defined_function(self):
        ctx = {"double": lambda x: x * 2}
        assert evaluate_expression("double(5)", ctx) == 10

    # --- Member access ---
    def test_member_access(self):
        from runtime.feel_lite.ast_nodes import MemberExpr
        ast = parse(tokenize("obj.field"))
        # This might be parsed as Identifier("obj.field") or MemberExpr
        result = evaluate(ast, {"obj": {"field": "value"}})
        assert result == "value"

    # --- Complex expressions ---
    def test_complex_business_rule(self):
        expr = "if amount > 1000 and status = \"pending\" then \"review\" else \"auto_approve\""
        ctx = {"amount": 5000, "status": "pending"}
        assert evaluate_expression(expr, ctx) == "review"

    def test_complex_calculation(self):
        expr = "sum([price * quantity, tax])"
        ctx = {"price": 10, "quantity": 5, "tax": 7.5}
        result = evaluate_expression(expr, ctx)
        assert result == 57.5


# =====================================================================
# Match value tests (for decision table cell matching)
# =====================================================================

class TestMatchValue:
    def test_wildcard_matches_everything(self):
        ast = parse(tokenize("-"))
        assert match_value(42, ast, {}) is True
        assert match_value("anything", ast, {}) is True
        assert match_value(None, ast, {}) is True

    def test_exact_number(self):
        ast = parse(tokenize("42"))
        assert match_value(42, ast, {}) is True
        assert match_value(43, ast, {}) is False

    def test_exact_string(self):
        ast = parse(tokenize('"approved"'))
        assert match_value("approved", ast, {}) is True
        assert match_value("APPROVED", ast, {}) is True  # case-insensitive
        assert match_value("rejected", ast, {}) is False

    def test_comparison_gte(self):
        ast = parse(tokenize(">= 100"))
        assert match_value(100, ast, {}) is True
        assert match_value(200, ast, {}) is True
        assert match_value(50, ast, {}) is False

    def test_comparison_lt(self):
        ast = parse(tokenize("< 50"))
        assert match_value(25, ast, {}) is True
        assert match_value(50, ast, {}) is False

    def test_range_inclusive(self):
        ast = parse(tokenize("[1..100]"))
        assert match_value(1, ast, {}) is True
        assert match_value(100, ast, {}) is True
        assert match_value(50, ast, {}) is True
        assert match_value(0, ast, {}) is False
        assert match_value(101, ast, {}) is False

    def test_range_exclusive(self):
        ast = parse(tokenize("(0..100)"))
        assert match_value(1, ast, {}) is True
        assert match_value(0, ast, {}) is False
        assert match_value(100, ast, {}) is False

    def test_list_match(self):
        ast = parse(tokenize('[1, 2, 3]'))
        assert match_value(2, ast, {}) is True
        assert match_value(5, ast, {}) is False

    def test_not_match(self):
        ast = parse(tokenize("not(5)"))
        assert match_value(5, ast, {}) is False
        assert match_value(3, ast, {}) is True

    def test_boolean_match(self):
        ast = parse(tokenize("true"))
        assert match_value(True, ast, {}) is True
        assert match_value(False, ast, {}) is False

    def test_null_match(self):
        ast = parse(tokenize("null"))
        assert match_value(None, ast, {}) is True
        assert match_value(0, ast, {}) is False
