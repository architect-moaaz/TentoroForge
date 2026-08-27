"""Tests for workflow runtime: gateway resolution, state management."""

import pytest

from runtime.gateway_controller import GatewayController


class TestExclusiveGateway:
    """Test XOR gateway resolution."""

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

    def test_default_edge_when_no_condition_matches(self):
        node = {"id": "gw1", "type": "exclusive_gateway"}
        edges = [
            {"source": "gw1", "target": "special", "data": {"condition": "priority == 'critical'"}},
            {"source": "gw1", "target": "normal", "data": {}},  # default edge
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


class TestParallelGateway:
    """Test AND gateway resolution."""

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


class TestJoinCondition:
    """Test parallel join evaluation."""

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


class TestConditionEvaluation:
    """Test condition expression evaluation."""

    def setup_method(self):
        self.gc = GatewayController()

    def test_equality(self):
        assert self.gc._evaluate_condition("status == approved", {"status": "approved"})

    def test_inequality(self):
        assert self.gc._evaluate_condition("status != pending", {"status": "approved"})

    def test_numeric_comparison(self):
        assert self.gc._evaluate_condition("total > 100", {"total": 500})
        assert not self.gc._evaluate_condition("total > 100", {"total": 50})

    def test_boolean_truthy(self):
        assert self.gc._evaluate_condition("is_urgent", {"is_urgent": True})
        assert not self.gc._evaluate_condition("is_urgent", {"is_urgent": False})

    def test_missing_variable(self):
        assert not self.gc._evaluate_condition("missing_var", {})
