"""Unit tests for the decision table and decision graph evaluator."""

import pytest
from runtime.decision_evaluator import (
    evaluate_decision_table,
    evaluate_decision_graph,
)


# =====================================================================
# Decision Table — Hit Policies
# =====================================================================

def _make_table(hit_policy, inputs, outputs, rules):
    """Helper to build a decision table definition dict."""
    return {
        "id": "test-table",
        "name": "Test Table",
        "hitPolicy": hit_policy,
        "inputs": inputs,
        "outputs": outputs,
        "rules": rules,
    }


DISCOUNT_INPUTS = [
    {"id": "i1", "label": "customer_type", "expression": "customer_type", "type": "string"},
    {"id": "i2", "label": "order_total", "expression": "order_total", "type": "number"},
]

DISCOUNT_OUTPUTS = [
    {"id": "o1", "label": "Discount", "name": "discount", "type": "number"},
]

DISCOUNT_RULES = [
    {"id": "r1", "inputEntries": ['"gold"', ">= 1000"], "outputEntries": [15]},
    {"id": "r2", "inputEntries": ['"gold"', "< 1000"], "outputEntries": [10]},
    {"id": "r3", "inputEntries": ['"silver"', ">= 500"], "outputEntries": [7]},
    {"id": "r4", "inputEntries": ['"silver"', "< 500"], "outputEntries": [5]},
    {"id": "r5", "inputEntries": ["-", "-"], "outputEntries": [0]},
]


class TestHitPolicyUnique:
    def test_gold_high_order(self):
        table = _make_table("U", DISCOUNT_INPUTS, DISCOUNT_OUTPUTS, DISCOUNT_RULES)
        result = evaluate_decision_table(table, {"customer_type": "gold", "order_total": 2000})
        assert result["matched_rule_ids"] == ["r1", "r5"]  # gold>=1000 and wildcard
        # U takes first match
        assert result["outputs"]["discount"] == 15

    def test_silver_low_order(self):
        table = _make_table("U", DISCOUNT_INPUTS, DISCOUNT_OUTPUTS, DISCOUNT_RULES)
        result = evaluate_decision_table(table, {"customer_type": "silver", "order_total": 200})
        assert "r4" in result["matched_rule_ids"]
        assert result["outputs"]["discount"] == 5

    def test_no_match(self):
        """Table with no wildcard rule and no match returns empty."""
        rules = [
            {"id": "r1", "inputEntries": ['"gold"', ">= 1000"], "outputEntries": [15]},
        ]
        table = _make_table("U", DISCOUNT_INPUTS, DISCOUNT_OUTPUTS, rules)
        result = evaluate_decision_table(table, {"customer_type": "bronze", "order_total": 100})
        assert result["matched_rule_ids"] == []
        assert result["result"] is None


class TestHitPolicyFirst:
    def test_first_matching_rule_wins(self):
        table = _make_table("F", DISCOUNT_INPUTS, DISCOUNT_OUTPUTS, DISCOUNT_RULES)
        result = evaluate_decision_table(table, {"customer_type": "gold", "order_total": 2000})
        assert result["outputs"]["discount"] == 15

    def test_wildcard_is_last_resort(self):
        table = _make_table("F", DISCOUNT_INPUTS, DISCOUNT_OUTPUTS, DISCOUNT_RULES)
        result = evaluate_decision_table(table, {"customer_type": "bronze", "order_total": 100})
        assert result["outputs"]["discount"] == 0


class TestHitPolicyAny:
    def test_all_agree(self):
        """When all matching rules agree, Any returns the shared output."""
        rules = [
            {"id": "r1", "inputEntries": ["-", ">= 100"], "outputEntries": [10]},
            {"id": "r2", "inputEntries": ['"gold"', "-"], "outputEntries": [10]},
        ]
        table = _make_table("A", DISCOUNT_INPUTS, DISCOUNT_OUTPUTS, rules)
        result = evaluate_decision_table(table, {"customer_type": "gold", "order_total": 500})
        assert result["outputs"]["discount"] == 10


class TestHitPolicyCollect:
    def test_collects_all_matching(self):
        rules = [
            {"id": "r1", "inputEntries": ["-", ">= 100"], "outputEntries": [5]},
            {"id": "r2", "inputEntries": ["-", ">= 500"], "outputEntries": [10]},
            {"id": "r3", "inputEntries": ["-", ">= 1000"], "outputEntries": [15]},
        ]
        table = _make_table("C", DISCOUNT_INPUTS, DISCOUNT_OUTPUTS, rules)
        result = evaluate_decision_table(table, {"customer_type": "any", "order_total": 750})
        # Should match r1 and r2
        assert len(result["outputs"]) == 2
        assert result["outputs"][0]["discount"] == 5
        assert result["outputs"][1]["discount"] == 10


class TestHitPolicyRuleOrder:
    def test_returns_in_rule_order(self):
        rules = [
            {"id": "r1", "inputEntries": ["-", "-"], "outputEntries": ['"low"']},
            {"id": "r2", "inputEntries": ["-", ">= 100"], "outputEntries": ['"medium"']},
            {"id": "r3", "inputEntries": ["-", ">= 1000"], "outputEntries": ['"high"']},
        ]
        outputs = [{"id": "o1", "label": "Level", "name": "level", "type": "string"}]
        table = _make_table("R", DISCOUNT_INPUTS, outputs, rules)
        result = evaluate_decision_table(table, {"customer_type": "any", "order_total": 5000})
        assert len(result["outputs"]) == 3
        assert result["outputs"][0]["level"] == "low"
        assert result["outputs"][1]["level"] == "medium"
        assert result["outputs"][2]["level"] == "high"


class TestHitPolicyPriority:
    def test_highest_priority_wins(self):
        rules = [
            {"id": "r1", "inputEntries": ["-", "-"], "outputEntries": [0], "priority": 3},
            {"id": "r2", "inputEntries": ["-", ">= 100"], "outputEntries": [10], "priority": 1},
            {"id": "r3", "inputEntries": ["-", ">= 500"], "outputEntries": [5], "priority": 2},
        ]
        table = _make_table("P", DISCOUNT_INPUTS, DISCOUNT_OUTPUTS, rules)
        result = evaluate_decision_table(table, {"customer_type": "any", "order_total": 750})
        # All three match, but priority 1 (r2) should win
        assert result["outputs"]["discount"] == 10


# =====================================================================
# Decision Table — Cell Matching
# =====================================================================

class TestCellMatching:
    def _eval(self, cell_expr, input_expr, input_val):
        """Evaluate a single-cell, single-rule table."""
        table = {
            "id": "t1",
            "name": "Test",
            "hitPolicy": "F",
            "inputs": [{"id": "i1", "label": "x", "expression": input_expr, "type": "any"}],
            "outputs": [{"id": "o1", "label": "Result", "name": "result", "type": "string"}],
            "rules": [
                {"id": "r1", "inputEntries": [cell_expr], "outputEntries": ["matched"]},
            ],
        }
        result = evaluate_decision_table(table, {input_expr: input_val})
        return len(result["matched_rule_ids"]) > 0

    def test_wildcard_dash(self):
        assert self._eval("-", "x", 42)

    def test_wildcard_empty(self):
        assert self._eval("", "x", 42)

    def test_exact_number(self):
        assert self._eval("42", "x", 42)
        assert not self._eval("42", "x", 43)

    def test_exact_string(self):
        assert self._eval('"approved"', "status", "approved")
        assert not self._eval('"approved"', "status", "rejected")

    def test_greater_than(self):
        assert self._eval("> 100", "x", 200)
        assert not self._eval("> 100", "x", 50)

    def test_less_equal(self):
        assert self._eval("<= 50", "x", 50)
        assert not self._eval("<= 50", "x", 51)

    def test_range(self):
        assert self._eval("[18..65]", "age", 30)
        assert not self._eval("[18..65]", "age", 10)

    def test_list(self):
        assert self._eval('[1, 2, 3]', "x", 2)
        assert not self._eval('[1, 2, 3]', "x", 5)

    def test_negation(self):
        assert self._eval("not(0)", "x", 5)
        assert not self._eval("not(0)", "x", 0)


# =====================================================================
# Decision Table — Multiple Outputs
# =====================================================================

class TestMultipleOutputs:
    def test_two_output_columns(self):
        table = {
            "id": "t1",
            "name": "Shipping",
            "hitPolicy": "F",
            "inputs": [
                {"id": "i1", "label": "weight", "expression": "weight", "type": "number"},
            ],
            "outputs": [
                {"id": "o1", "label": "Method", "name": "method", "type": "string"},
                {"id": "o2", "label": "Cost", "name": "cost", "type": "number"},
            ],
            "rules": [
                {"id": "r1", "inputEntries": ["< 5"], "outputEntries": ['"standard"', 5]},
                {"id": "r2", "inputEntries": [">= 5"], "outputEntries": ['"express"', 15]},
            ],
        }
        result = evaluate_decision_table(table, {"weight": 3})
        assert result["outputs"]["method"] == "standard"
        assert result["outputs"]["cost"] == 5

        result2 = evaluate_decision_table(table, {"weight": 10})
        assert result2["outputs"]["method"] == "express"
        assert result2["outputs"]["cost"] == 15


# =====================================================================
# Decision Table — Dotted Inputs
# =====================================================================

class TestDottedInputs:
    def test_nested_input_resolution(self):
        table = {
            "id": "t1",
            "name": "Nested",
            "hitPolicy": "F",
            "inputs": [
                {"id": "i1", "label": "customer.type", "expression": "customer.type", "type": "string"},
            ],
            "outputs": [
                {"id": "o1", "label": "Discount", "name": "discount", "type": "number"},
            ],
            "rules": [
                {"id": "r1", "inputEntries": ['"vip"'], "outputEntries": [20]},
                {"id": "r2", "inputEntries": ["-"], "outputEntries": [0]},
            ],
        }
        result = evaluate_decision_table(table, {"customer": {"type": "vip"}})
        assert result["outputs"]["discount"] == 20


# =====================================================================
# Decision Graph Evaluator
# =====================================================================

class TestDecisionGraph:
    def test_simple_chain(self):
        """Input → Decision → output."""
        graph = {
            "nodes": [
                {"id": "input1", "type": "input", "expression": "age"},
                {
                    "id": "decision1",
                    "type": "decision",
                    "decisionTable": {
                        "id": "dt1",
                        "name": "Age Check",
                        "hitPolicy": "F",
                        "inputs": [{"id": "i1", "label": "age", "expression": "age", "type": "number"}],
                        "outputs": [{"id": "o1", "label": "Category", "name": "category", "type": "string"}],
                        "rules": [
                            {"id": "r1", "inputEntries": ["< 18"], "outputEntries": ['"minor"']},
                            {"id": "r2", "inputEntries": [">= 18"], "outputEntries": ['"adult"']},
                        ],
                    },
                },
            ],
            "edges": [
                {"source": "input1", "target": "decision1"},
            ],
        }
        result = evaluate_decision_graph(graph, {"age": 25})
        assert result["node_results"]["input1"] == 25
        decision_result = result["node_results"]["decision1"]
        assert decision_result["outputs"]["category"] == "adult"

    def test_chained_decisions(self):
        """Two decisions in sequence: first determines discount, second adds shipping."""
        graph = {
            "nodes": [
                {
                    "id": "discount_decision",
                    "type": "decision",
                    "decisionTable": {
                        "id": "dt1", "name": "Discount", "hitPolicy": "F",
                        "inputs": [{"id": "i1", "label": "total", "expression": "total", "type": "number"}],
                        "outputs": [{"id": "o1", "label": "Discount", "name": "discount", "type": "number"}],
                        "rules": [
                            {"id": "r1", "inputEntries": [">= 100"], "outputEntries": [10]},
                            {"id": "r2", "inputEntries": ["-"], "outputEntries": [0]},
                        ],
                    },
                },
                {
                    "id": "shipping_decision",
                    "type": "decision",
                    "expression": "total - discount + 5",
                },
            ],
            "edges": [
                {"source": "discount_decision", "target": "shipping_decision"},
            ],
        }
        result = evaluate_decision_graph(graph, {"total": 200})
        # discount_decision should set discount=10 in context
        # shipping_decision evaluates: 200 - 10 + 5 = 195
        assert result["node_results"]["shipping_decision"] == 195.0

    def test_graph_with_knowledge_node(self):
        """Knowledge source node provides computed value."""
        graph = {
            "nodes": [
                {"id": "k1", "type": "knowledge", "expression": "base_rate * 1.1"},
                {
                    "id": "d1",
                    "type": "decision",
                    "expression": "k1 + surcharge",
                },
            ],
            "edges": [
                {"source": "k1", "target": "d1"},
            ],
        }
        result = evaluate_decision_graph(graph, {"base_rate": 100, "surcharge": 5})
        assert abs(result["node_results"]["k1"] - 110.0) < 0.001
        assert abs(result["node_results"]["d1"] - 115.0) < 0.001

    def test_diamond_dependency(self):
        """Diamond pattern: A → B, A → C, B → D, C → D."""
        graph = {
            "nodes": [
                {"id": "A", "type": "input", "expression": "value"},
                {"id": "B", "type": "knowledge", "expression": "A * 2"},
                {"id": "C", "type": "knowledge", "expression": "A + 10"},
                {"id": "D", "type": "decision", "expression": "B + C"},
            ],
            "edges": [
                {"source": "A", "target": "B"},
                {"source": "A", "target": "C"},
                {"source": "B", "target": "D"},
                {"source": "C", "target": "D"},
            ],
        }
        result = evaluate_decision_graph(graph, {"value": 5})
        assert result["node_results"]["A"] == 5
        assert result["node_results"]["B"] == 10.0
        assert result["node_results"]["C"] == 15.0
        assert result["node_results"]["D"] == 25.0

    def test_no_edges(self):
        """Nodes with no edges still get executed."""
        graph = {
            "nodes": [
                {"id": "n1", "type": "knowledge", "expression": "x + 1"},
            ],
            "edges": [],
        }
        result = evaluate_decision_graph(graph, {"x": 10})
        assert result["node_results"]["n1"] == 11.0

    def test_empty_graph(self):
        result = evaluate_decision_graph({"nodes": [], "edges": []}, {})
        assert result["node_results"] == {}
        assert result["outputs"] == {}


# =====================================================================
# Edge cases and timing
# =====================================================================

class TestEdgeCases:
    def test_returns_duration_ms(self):
        table = _make_table("F", DISCOUNT_INPUTS, DISCOUNT_OUTPUTS, DISCOUNT_RULES)
        result = evaluate_decision_table(table, {"customer_type": "gold", "order_total": 500})
        assert "duration_ms" in result
        assert isinstance(result["duration_ms"], int)

    def test_empty_rules_list(self):
        table = _make_table("F", DISCOUNT_INPUTS, DISCOUNT_OUTPUTS, [])
        result = evaluate_decision_table(table, {"customer_type": "gold", "order_total": 500})
        assert result["matched_rule_ids"] == []
        assert result["result"] is None

    def test_missing_input_entries(self):
        """Rule with fewer input entries than columns should still work."""
        rules = [{"id": "r1", "inputEntries": ['"gold"'], "outputEntries": [10]}]
        table = _make_table("F", DISCOUNT_INPUTS, DISCOUNT_OUTPUTS, rules)
        result = evaluate_decision_table(table, {"customer_type": "gold", "order_total": 100})
        assert "r1" in result["matched_rule_ids"]

    def test_unknown_hit_policy_defaults_to_first(self):
        table = _make_table("Z", DISCOUNT_INPUTS, DISCOUNT_OUTPUTS, DISCOUNT_RULES)
        result = evaluate_decision_table(table, {"customer_type": "gold", "order_total": 2000})
        # Should fallback to First behavior
        assert result["outputs"]["discount"] == 15
