"""Tests for workflow runtime: engine helpers, gateway resolution, variable resolution."""

import pytest
from runtime.gateway_controller import GatewayController
from runtime.variable_resolver import VariableResolver


# =====================================================================
# Gateway Controller — Exclusive Gateway
# =====================================================================

class TestExclusiveGateway:
    def setup_method(self):
        self.gc = GatewayController()

    def test_matches_first_condition(self):
        node = {"id": "gw1", "type": "exclusive_gateway"}
        edges = [
            {"source": "gw1", "target": "approve", "data": {"condition": "amount < 1000"}},
            {"source": "gw1", "target": "review", "data": {"condition": "amount >= 1000"}},
        ]
        result = self.gc.resolve_exclusive_gateway(node, edges, {"amount": 500})
        assert result == ["approve"]

    def test_falls_through_to_second(self):
        node = {"id": "gw1", "type": "exclusive_gateway"}
        edges = [
            {"source": "gw1", "target": "approve", "data": {"condition": "amount < 1000"}},
            {"source": "gw1", "target": "review", "data": {"condition": "amount >= 1000"}},
        ]
        result = self.gc.resolve_exclusive_gateway(node, edges, {"amount": 5000})
        assert result == ["review"]

    def test_default_edge_when_no_match(self):
        node = {"id": "gw1", "type": "exclusive_gateway"}
        edges = [
            {"source": "gw1", "target": "special", "data": {"condition": "priority == 'critical'"}},
            {"source": "gw1", "target": "normal", "data": {}},
        ]
        result = self.gc.resolve_exclusive_gateway(node, edges, {"priority": "low"})
        assert result == ["normal"]

    def test_empty_when_no_match_no_default(self):
        node = {"id": "gw1", "type": "exclusive_gateway"}
        edges = [
            {"source": "gw1", "target": "a", "data": {"condition": "x == 1"}},
            {"source": "gw1", "target": "b", "data": {"condition": "x == 2"}},
        ]
        result = self.gc.resolve_exclusive_gateway(node, edges, {"x": 999})
        assert result == []

    def test_ignores_edges_from_other_nodes(self):
        node = {"id": "gw1", "type": "exclusive_gateway"}
        edges = [
            {"source": "other", "target": "x", "data": {"condition": "true"}},
            {"source": "gw1", "target": "approve", "data": {"condition": "amount > 0"}},
        ]
        result = self.gc.resolve_exclusive_gateway(node, edges, {"amount": 100})
        assert result == ["approve"]


# =====================================================================
# Gateway Controller — Parallel Gateway
# =====================================================================

class TestParallelGateway:
    def setup_method(self):
        self.gc = GatewayController()

    def test_activates_all_paths(self):
        node = {"id": "fork1", "type": "parallel_gateway"}
        edges = [
            {"source": "fork1", "target": "path_a"},
            {"source": "fork1", "target": "path_b"},
            {"source": "fork1", "target": "path_c"},
        ]
        result = self.gc.resolve_parallel_gateway(node, edges, {})
        assert set(result) == {"path_a", "path_b", "path_c"}

    def test_empty_edges(self):
        node = {"id": "fork1", "type": "parallel_gateway"}
        result = self.gc.resolve_parallel_gateway(node, [], {})
        assert result == []

    def test_ignores_incoming_edges(self):
        node = {"id": "fork1", "type": "parallel_gateway"}
        edges = [
            {"source": "prev", "target": "fork1"},
            {"source": "fork1", "target": "path_a"},
            {"source": "fork1", "target": "path_b"},
        ]
        result = self.gc.resolve_parallel_gateway(node, edges, {})
        assert set(result) == {"path_a", "path_b"}


# =====================================================================
# Gateway Controller — Join Condition
# =====================================================================

class TestJoinCondition:
    def setup_method(self):
        self.gc = GatewayController()

    def test_all_paths_complete(self):
        edges = [
            {"source": "path_a", "target": "join1"},
            {"source": "path_b", "target": "join1"},
        ]
        assert self.gc.check_join_condition("join1", edges, {"path_a", "path_b"}) is True

    def test_not_all_paths_complete(self):
        edges = [
            {"source": "path_a", "target": "join1"},
            {"source": "path_b", "target": "join1"},
        ]
        assert self.gc.check_join_condition("join1", edges, {"path_a"}) is False

    def test_empty_completed_set(self):
        edges = [
            {"source": "path_a", "target": "join1"},
        ]
        assert self.gc.check_join_condition("join1", edges, set()) is False


# =====================================================================
# Gateway Controller — Condition Evaluation
# =====================================================================

class TestConditionEvaluation:
    def setup_method(self):
        self.gc = GatewayController()

    def test_equality_string(self):
        assert self.gc._evaluate_condition("status == approved", {"status": "approved"})

    def test_inequality(self):
        assert self.gc._evaluate_condition("status != pending", {"status": "approved"})

    def test_numeric_gt(self):
        assert self.gc._evaluate_condition("total > 100", {"total": 500})
        assert not self.gc._evaluate_condition("total > 100", {"total": 50})

    def test_numeric_lt(self):
        assert self.gc._evaluate_condition("total < 100", {"total": 50})

    def test_numeric_gte(self):
        assert self.gc._evaluate_condition("total >= 100", {"total": 100})

    def test_numeric_lte(self):
        assert self.gc._evaluate_condition("total <= 100", {"total": 100})

    def test_boolean_truthy(self):
        assert self.gc._evaluate_condition("is_urgent", {"is_urgent": True})
        assert not self.gc._evaluate_condition("is_urgent", {"is_urgent": False})

    def test_missing_variable(self):
        assert not self.gc._evaluate_condition("missing_var", {})

    def test_empty_condition(self):
        # Empty condition should not match
        assert not self.gc._evaluate_condition("", {})


# =====================================================================
# Variable Resolver
# =====================================================================

class TestVariableResolver:
    def test_simple_variable(self):
        resolver = VariableResolver({"name": "Alice", "age": 30})
        assert resolver.resolve_string("{{name}}") == "Alice"
        assert resolver.resolve_string("{{age}}") == "30"

    def test_dotted_path(self):
        resolver = VariableResolver({"customer": {"name": "Bob", "address": {"city": "NYC"}}})
        assert resolver.resolve_string("{{customer.name}}") == "Bob"
        assert resolver.resolve_string("{{customer.address.city}}") == "NYC"

    def test_missing_preserves_template(self):
        resolver = VariableResolver({})
        assert resolver.resolve_string("{{missing}}") == "{{missing}}"

    def test_template_substitution(self):
        resolver = VariableResolver({"name": "Alice", "count": 5})
        result = resolver.resolve_string("Hello {{name}}, you have {{count}} items")
        assert result == "Hello Alice, you have 5 items"

    def test_no_template_passthrough(self):
        resolver = VariableResolver({"x": 1})
        assert resolver.resolve_string("plain text") == "plain text"

    def test_resolve_dict(self):
        resolver = VariableResolver({"user": "Alice"})
        result = resolver.resolve_dict({"greeting": "Hello {{user}}", "count": 5})
        assert result["greeting"] == "Hello Alice"
        assert result["count"] == 5

    def test_resolve_nested_dict(self):
        resolver = VariableResolver({"x": "world"})
        result = resolver.resolve_dict({"outer": {"inner": "hello {{x}}"}})
        assert result["outer"]["inner"] == "hello world"

    def test_resolve_list(self):
        resolver = VariableResolver({"a": "1", "b": "2"})
        result = resolver.resolve_value(["{{a}}", "{{b}}", "literal"])
        assert result == ["1", "2", "literal"]

    def test_resolve_non_string_passthrough(self):
        resolver = VariableResolver({})
        assert resolver.resolve_value(42) == 42
        assert resolver.resolve_value(None) is None
        assert resolver.resolve_value(True) is True
