"""A KPI may not be formatted as something its own metric cannot be.

Live on opmk18qr, a tile labelled "Utilization Rate" carried
``format: "percent"`` while its dataSource was a plain ``count`` over
LeaveBalance. Ten rows became **1,000%** on the dashboard. The percent
formatter was not broken — it correctly rendered 10 as a ratio. What was
missing is that nobody checked a *count can never be a ratio*.

This is the same shape as the delta bug beside it, and as several others this
week: two components each hold a plausible half of a contract, and nothing
sits between them asking whether they agree. So this module is that check, and
it is deliberately a type statement rather than a heuristic — count, sum and
max produce a magnitude; a magnitude rendered as a percent is a number nobody
computed.

What it will NOT do is invent the rate. Turning a count into a real
utilisation figure needs a numerator and a denominator that the composer does
not have. Demoting the format leaves an honest "10" under a label that is
still thinner than it should be — a visible prompt to author a real ratio,
rather than a fabricated 1,000% that reads as authoritative.
"""

from __future__ import annotations

from typing import Any

# Ops whose result is a magnitude, never a ratio. Anything not listed here —
# avg, ratio, rate, or an op this module has never heard of — is left alone:
# an unmodelled op may genuinely be a ratio, and a confident wrong demotion is
# worse than silence.
_MAGNITUDE_OPS = {"count", "sum", "max", "min"}


def honest_format(fmt: str, op: str) -> str:
    """The format this metric is entitled to claim."""
    if fmt != "percent":
        return fmt
    return "number" if (op or "").strip().lower() in _MAGNITUDE_OPS else fmt


def _sources_by_name(page: dict) -> dict[str, str]:
    """dataSource name -> the fn its `value` metric uses."""
    out: dict[str, str] = {}
    for ds in page.get("dataSources") or []:
        if not isinstance(ds, dict):
            continue
        name = ds.get("name")
        if not name:
            continue
        metrics = ds.get("metrics") or {}
        value = metrics.get("value") if isinstance(metrics, dict) else None
        fn = (value or {}).get("fn") if isinstance(value, dict) else None
        out[str(name)] = str(fn or ds.get("fn") or ds.get("op") or "")
    return out


def _source_of(value: Any) -> str | None:
    """The dataSource name a `{{name.value}}` binding reads from."""
    if not isinstance(value, str):
        return None
    inner = value.strip()
    if not (inner.startswith("{{") and inner.endswith("}}")):
        return None
    return inner[2:-2].strip().split(".")[0] or None


def _walk(node: Any, visit) -> None:
    if isinstance(node, dict):
        visit(node)
        for v in node.values():
            _walk(v, visit)
    elif isinstance(node, list):
        for v in node:
            _walk(v, visit)


def reconcile_kpi_formats(page: dict) -> dict[str, Any]:
    """Demote every percent-formatted tile whose metric is a magnitude.

    Mutates `page` in place. Idempotent: a second run finds nothing, because
    the first already rewrote the format.
    """
    sources = _sources_by_name(page)
    notes: list[str] = []

    def visit(node: dict) -> None:
        if node.get("type") != "MetricTile":
            return
        props = node.get("props")
        if not isinstance(props, dict) or props.get("format") != "percent":
            return
        name = _source_of(props.get("value"))
        if not name or name not in sources:
            return  # cannot see the metric — leave the author's choice alone
        op = sources[name]
        fixed = honest_format("percent", op)
        if fixed != "percent":
            props["format"] = fixed
            notes.append(
                f"{props.get('label') or name!r}: percent -> {fixed} "
                f"(metric is a {op}, which is a magnitude and not a ratio)")

    _walk(page.get("root"), visit)
    return {"changed": len(notes), "notes": notes}
