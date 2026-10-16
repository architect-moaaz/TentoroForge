"""What a draft would cost and take to build — a range, never a quote.

From the builds measured on 2026-10-12 to 2026-10-14 (small and medium apps
built through the panel): about $0.38 per unit, a unit being one screen or
one process, and 23 minutes × (units ÷ 15)^0.47 of build time. Fixes after
the build are shown at a quarter of the build's cost, the convention the
executive summary uses. The spread is the spread those builds showed.
"""
from __future__ import annotations

MEASURED_ON = "2026-10-12 to 2026-10-14"
COST_PER_UNIT = 0.38
COST_SPREAD = 0.35
MINUTES_AT_15 = 23.0
TIME_EXPONENT = 0.47
TIME_SPREAD = 0.25
FIXES_SHARE = 0.25


def units(screens: int, processes: int) -> int:
    return max(1, int(screens) + int(processes))


def estimate(screens: int, processes: int) -> dict:
    u = units(screens, processes)
    cost = COST_PER_UNIT * u
    minutes = MINUTES_AT_15 * (u / 15) ** TIME_EXPONENT
    return {"units": u, "measured_on": MEASURED_ON,
            "cost": {"low": round(cost * (1 - COST_SPREAD), 2), "high": round(cost * (1 + COST_SPREAD), 2)},
            "minutes": {"low": int(minutes * (1 - TIME_SPREAD)), "high": int(minutes * (1 + TIME_SPREAD)) + 1},
            "fixes": {"low": round(cost * (1 - COST_SPREAD) * FIXES_SHARE, 2),
                      "high": round(cost * (1 + COST_SPREAD) * FIXES_SHARE, 2)}}


__all__ = ["estimate", "units", "MEASURED_ON"]
