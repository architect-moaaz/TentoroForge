"""Gateway controller — handles exclusive, parallel, event-based gateways,
condition nodes, and AI-decide branching."""

import logging
from typing import Any

from runtime.variable_resolver import VariableResolver

logger = logging.getLogger(__name__)


class GatewayController:
    """Evaluates gateway conditions and determines outgoing paths."""

    def resolve_condition_node(
        self,
        node: dict,
        edges: list[dict],
        variables: dict,
    ) -> list[str]:
        """Resolve a condition node using node.data.config.expression + edgeType then/else.

        Reads expression from node config, resolves variable templates,
        evaluates the expression, and returns targets from edges with
        edgeType "then" (if True) or "else" (if False).
        """
        config = node.get("data", {}).get("config", {})
        expression = config.get("expression", "")

        # Resolve variable templates in the expression
        resolver = VariableResolver(variables)
        resolved_expr = resolver.resolve_string(expression)

        result = self._evaluate_condition(resolved_expr, variables)
        edge_type = "then" if result else "else"

        outgoing = self._outgoing_edges(node["id"], edges)
        targets = []
        default_targets = []

        for edge in outgoing:
            e_type = edge.get("data", {}).get("edgeType", "default")
            if e_type == edge_type:
                targets.append(edge["target"])
            elif e_type == "default":
                default_targets.append(edge["target"])

        if targets:
            logger.info(
                "Condition %s: expression '%s' → %s, targets=%s",
                node["id"], resolved_expr, result, targets,
            )
            return targets

        # Fallback: if no then/else edge found, use default edges
        if default_targets:
            logger.info(
                "Condition %s: no '%s' edge, using default → %s",
                node["id"], edge_type, default_targets,
            )
            return default_targets

        logger.warning("Condition %s: no outgoing path resolved", node["id"])
        return []

    def resolve_ai_decide_node(
        self,
        node: dict,
        edges: list[dict],
        ai_result: bool,
    ) -> list[str]:
        """Route based on AI decision boolean — same then/else edge routing."""
        edge_type = "then" if ai_result else "else"
        outgoing = self._outgoing_edges(node["id"], edges)
        targets = []
        default_targets = []

        for edge in outgoing:
            e_type = edge.get("data", {}).get("edgeType", "default")
            if e_type == edge_type:
                targets.append(edge["target"])
            elif e_type == "default":
                default_targets.append(edge["target"])

        if targets:
            logger.info(
                "AI decide %s: decision=%s → %s path, targets=%s",
                node["id"], ai_result, edge_type, targets,
            )
            return targets

        if default_targets:
            return default_targets

        logger.warning("AI decide %s: no outgoing path resolved", node["id"])
        return []

    def resolve_exclusive_gateway(
        self,
        node: dict,
        edges: list[dict],
        variables: dict,
    ) -> list[str]:
        """XOR gateway — pick the first edge whose condition evaluates to True,
        or the default edge if none match."""
        outgoing = self._outgoing_edges(node["id"], edges)
        default_targets = []

        for edge in outgoing:
            edge_data = edge.get("data", {})
            condition = edge_data.get("condition")

            if not condition:
                default_targets.append(edge["target"])
                continue

            if self._evaluate_condition(condition, variables):
                logger.info(
                    "Exclusive gateway %s: condition '%s' matched → %s",
                    node["id"], condition, edge["target"],
                )
                return [edge["target"]]

        if default_targets:
            logger.info(
                "Exclusive gateway %s: no condition matched, using default → %s",
                node["id"], default_targets[0],
            )
            return [default_targets[0]]

        logger.warning("Exclusive gateway %s: no outgoing path resolved", node["id"])
        return []

    def resolve_parallel_gateway(
        self,
        node: dict,
        edges: list[dict],
        variables: dict,
    ) -> list[str]:
        """AND gateway — activate ALL outgoing edges simultaneously."""
        outgoing = self._outgoing_edges(node["id"], edges)
        targets = [e["target"] for e in outgoing]
        logger.info(
            "Parallel gateway %s: activating %d parallel paths",
            node["id"], len(targets),
        )
        return targets

    def resolve_event_gateway(
        self,
        node: dict,
        edges: list[dict],
        variables: dict,
    ) -> list[str]:
        """Event-based gateway — waits for first event to determine path.
        For now, treat like exclusive gateway (first matching or default)."""
        return self.resolve_exclusive_gateway(node, edges, variables)

    def resolve_decision_node(
        self,
        node: dict,
        edges: list[dict],
        variables: dict,
    ) -> list[str]:
        """Resolve a decision node by evaluating its decision table.

        1. Reads the decision table definition from node.data.config.decisionTable
        2. Calls evaluate_decision_table with the variables as inputs
        3. Routes based on whether any rules matched (then/else edges)

        Returns list of next node IDs.
        """
        config = node.get("data", {}).get("config", {})
        decision_table = config.get("decisionTable", {})

        if not decision_table:
            logger.warning("Decision node %s: no decisionTable in config", node["id"])
            # Fall back to default edges
            outgoing = self._outgoing_edges(node["id"], edges)
            return [e["target"] for e in outgoing]

        from runtime.decision_evaluator import evaluate_decision_table

        result = evaluate_decision_table(decision_table, variables)
        matched = bool(result.get("matched_rule_ids"))

        edge_type = "then" if matched else "else"
        outgoing = self._outgoing_edges(node["id"], edges)
        targets = []
        default_targets = []

        for edge in outgoing:
            e_type = edge.get("data", {}).get("edgeType", "default")
            if e_type == edge_type:
                targets.append(edge["target"])
            elif e_type == "default":
                default_targets.append(edge["target"])

        if targets:
            logger.info(
                "Decision %s: matched=%s → %s path, targets=%s, outputs=%s",
                node["id"], matched, edge_type, targets, result.get("outputs"),
            )
            return targets

        if default_targets:
            logger.info(
                "Decision %s: no '%s' edge, using default → %s",
                node["id"], edge_type, default_targets,
            )
            return default_targets

        logger.warning("Decision %s: no outgoing path resolved", node["id"])
        return []

    def check_join_condition(
        self,
        join_node_id: str,
        edges: list[dict],
        completed_node_ids: set[str],
    ) -> bool:
        """Check if all incoming paths to a parallel join have completed."""
        incoming = self._incoming_edges(join_node_id, edges)
        sources = {e["source"] for e in incoming}
        all_met = sources.issubset(completed_node_ids)
        if not all_met:
            pending = sources - completed_node_ids
            logger.info(
                "Join %s: waiting for %d more paths: %s",
                join_node_id, len(pending), pending,
            )
        return all_met

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _outgoing_edges(self, node_id: str, edges: list[dict]) -> list[dict]:
        return [e for e in edges if e.get("source") == node_id]

    def _incoming_edges(self, node_id: str, edges: list[dict]) -> list[dict]:
        return [e for e in edges if e.get("target") == node_id]

    def _evaluate_condition(self, condition: str, variables: dict) -> bool:
        """Safely evaluate a condition expression.

        First tries the FEEL-lite parser for full expression support.
        Falls back to the legacy string-split logic for backward compatibility.

        Supports:
        - FEEL-lite expressions (via parser): "age >= 18 and status = 'active'"
        - Fully resolved expressions: "1500 > 1000", "'approved' == 'approved'"
        - Variable lookups: "status == approved"
        - Bare variable name: truthy check
        """
        try:
            condition = condition.strip()
            if not condition:
                return False

            # Try FEEL-lite parser first
            try:
                from runtime.feel_lite.evaluator import evaluate_expression
                result = evaluate_expression(condition, variables)
                return bool(result)
            except Exception:
                pass  # Fall through to legacy logic

            # Legacy string-split logic for backward compatibility
            for op in ("==", "!=", ">=", "<=", ">", "<"):
                if op in condition:
                    parts = condition.split(op, 1)
                    if len(parts) == 2:
                        left_raw = parts[0].strip()
                        right_raw = parts[1].strip()

                        # Try to resolve as literals first (fully-resolved expressions)
                        left = self._coerce_value(left_raw)
                        right = self._coerce_value(right_raw)

                        # If left side looks like a variable name (not a literal),
                        # try looking it up in variables
                        if isinstance(left, str) and left == left_raw and left in variables:
                            left = variables[left]

                        if op == "==":
                            return left == right
                        elif op == "!=":
                            return left != right
                        elif op == ">":
                            return float(left) > float(right)
                        elif op == "<":
                            return float(left) < float(right)
                        elif op == ">=":
                            return float(left) >= float(right)
                        elif op == "<=":
                            return float(left) <= float(right)

            # Truthy check on variable
            return bool(variables.get(condition, self._coerce_value(condition)))

        except Exception:
            logger.warning("Failed to evaluate condition: %s", condition)
            return False

    def _coerce_value(self, raw: str) -> Any:
        """Coerce a string value to appropriate Python type."""
        raw = raw.strip().strip("'\"")
        if raw.lower() == "true":
            return True
        if raw.lower() == "false":
            return False
        if raw.lower() in ("null", "none"):
            return None
        try:
            return int(raw)
        except ValueError:
            pass
        try:
            return float(raw)
        except ValueError:
            pass
        return raw
