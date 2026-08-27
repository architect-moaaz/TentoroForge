# backend/services/cost_tracker.py
"""Tracks LLM call costs across the fidelity loop, raises when the project cap
is exceeded so the runner can stop dispatching new iterations."""
from __future__ import annotations

from typing import Literal


# Approximate Sonnet-4.5 pricing as of 2026-05. These rates are intentionally
# slightly conservative (rounded up) to act as a brake.
# Input + output in USD per 1M tokens.
_RATES_USD_PER_M: dict[str, tuple[float, float]] = {
    "vision":          (3.0, 15.0),  # Anthropic vision: input + output
    "patch":           (3.0, 15.0),
    "schema_reprompt": (3.0, 15.0),
    "exemplar_seed":   (3.0, 15.0),
}
_DEFAULT_RATE = (3.0, 15.0)


class BudgetExhausted(Exception):
    """Raised when project-wide LLM cost exceeds the configured cap."""


class CostTracker:
    """Accumulator for per-call LLM costs. Raises BudgetExhausted past the cap."""

    def __init__(self, cap_usd: float):
        if cap_usd <= 0:
            raise ValueError(f"cap_usd must be positive, got {cap_usd}")
        self.cap_usd = cap_usd
        self.total: float = 0.0

    def add(self, kind: Literal["vision", "patch", "schema_reprompt", "exemplar_seed"], tokens_in: int, tokens_out: int) -> float:
        """Add a call's cost to the running total. Returns the cost added."""
        in_rate, out_rate = _RATES_USD_PER_M.get(kind, _DEFAULT_RATE)
        cost = (tokens_in / 1_000_000) * in_rate + (tokens_out / 1_000_000) * out_rate
        self.total += cost
        if self.total > self.cap_usd:
            raise BudgetExhausted(f"project cost cap ${self.cap_usd:.3f} exceeded (now ${self.total:.4f})")
        return cost
