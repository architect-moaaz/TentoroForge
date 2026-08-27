"""Post-generate pass: fold hallucinated chart component types into
``Chart`` + ``chartType`` prop.

The library exposes ONE chart component — ``Chart`` — with a
``chartType: "line" | "bar" | "area" | "pie" | "donut" | "funnel"``
prop. The LLM composers occasionally emit component types that don't
exist in the library (``LineChart``, ``AreaChart``, ``BarChart``,
``PieChart``, ``DonutChart``), copying the shape of popular chart
library exports. The renderer's ``registry`` doesn't know these names
so it renders the "Component X is not registered" placeholder — a
horizontal grey bar where the chart should be.

This module rewrites those nodes in place: ``type: "LineChart"`` →
``type: "Chart"`` with ``chartType`` set to ``"line"`` (preserved from
the alias when the LLM didn't set one). Idempotent, fail-open.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# Hallucinated component name → chartType value the library actually reads.
_CHART_ALIASES = {
    "LineChart":       "line",
    "AreaChart":       "area",
    "BarChart":        "bar",
    "ColumnChart":     "bar",
    "PieChart":        "pie",
    "DonutChart":      "donut",
    "DoughnutChart":   "donut",
    "FunnelChart":     "funnel",
    "ScatterChart":    "scatter",
    "BubbleChart":     "bubble",
    "RadarChart":      "radar",
    "TreemapChart":    "treemap",
    "SparklineChart":  "sparkline",
    "Sparkline":       "sparkline",
    "GaugeChart":      "gauge",  # will be routed further downstream if needed
}


def _walk(node: Any) -> Iterable[dict]:
    if isinstance(node, dict):
        yield node
        for c in node.get("children") or []:
            yield from _walk(c)
    elif isinstance(node, list):
        for c in node:
            yield from _walk(c)


def _rewrite_schema(schema: dict) -> int:
    """Rewrite every hallucinated chart alias inside one schema tree.
    Returns count of nodes rewritten. Mutates in place.
    """
    count = 0
    for node in _walk(schema.get("root")):
        t = node.get("type")
        if t in _CHART_ALIASES:
            props = node.setdefault("props", {})
            # Preserve any explicit chartType the LLM already set —
            # only fill from the alias when missing.
            props.setdefault("chartType", _CHART_ALIASES[t])
            node["type"] = "Chart"
            count += 1
    return count


def apply_chart_type_alias(output_dir: str | Path) -> dict[str, Any]:
    """Walk every page schema, rewrite hallucinated chart types. Never
    raises. Returns ``{"patched": <files>, "rewritten": <nodes>}``.
    """
    root = Path(output_dir)
    sdir = root / "src" / "schemas"
    if not sdir.is_dir():
        return {"patched": 0, "rewritten": 0}

    patched_files = 0
    rewritten_nodes = 0
    for path in sorted(sdir.rglob("*.json")):
        if path.name in ("shell.json", "nav-flow.json"):
            continue
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        n = _rewrite_schema(schema)
        if n:
            try:
                path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
                patched_files += 1
                rewritten_nodes += n
            except Exception as exc:  # noqa: BLE001
                logger.warning("[chart-alias] write failed %s: %s", path, exc)

    if patched_files:
        logger.info(
            "[chart-alias] rewrote %d node(s) across %d file(s)",
            rewritten_nodes, patched_files,
        )
    return {"patched": patched_files, "rewritten": rewritten_nodes}


__all__ = ["apply_chart_type_alias"]
