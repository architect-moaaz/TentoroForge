"""One dialect for an op:"aggregate" metric.

Two generators disagreed about how a KPI metric is written, and nothing on the
render side spoke both:

  * The runtime contract — `data-engine.computeSimple`, the preview resolver in
    `frontend/src/lib/preview-resolve.ts`, and the shape
    `widget_data_source_guard` emits — is
    ``{"fn": "sum", "field": "price"}``. `fn` selects a Drizzle aggregate and
    `field` must name a real COLUMN, because it is compiled to SQL.
  * The LLM page composer authors
    ``{"expression": "sum(quantity * price)", "format": "currency"}``.

An `expression` metric has no parser anywhere, so `resolveAggregate` iterated a
metric with no `fn`, `computeSimple` built `count()` or bailed, and a tile that
looked correctly declared resolved to 0 — the "correctly-NAMED aggregate source
that still resolves to garbage" half of the blank-KPI bug.

This module is the single translator. It normalises the `expression` dialect
into the runtime one so the dialect never reaches a resolver, and it is
deliberately lossless about arithmetic:

    count(id)              -> {"fn": "count"}
    count(*)               -> {"fn": "count"}
    sum(price)             -> {"fn": "sum",  "field": "price"}
    avg(rating)            -> {"fn": "avg",  "field": "rating"}
    sum(quantity * price)  -> {"fn": "sum",  "expr": "quantity * price"}

The last case is the honest one. `field` MUST be a column — `cols["quantity *
price"]` is `undefined` and `sum(undefined)` throws, which `resolveAggregate`
swallows into 0. So an arithmetic argument is kept as `expr` and `field` is
left off: the SQL side degrades to 0 by its own documented rule ("sum/avg/min/max
need a real column"), while a row-level resolver that CAN evaluate arithmetic
(the editor preview) reads `expr` and gets the right number. Writing a fake
`field` would have made both sides silently wrong instead of one side honestly
empty.

Never raises. An expression this cannot parse is left exactly as it was, so a
future dialect degrades to today's behaviour rather than to a crash.
"""
from __future__ import annotations

import glob
import json
import os
import re

#: The aggregate functions the runtime can actually compute, plus the aliases
#: an authoring agent reaches for.
_FN_ALIASES = {
    "count": "count",
    "sum": "sum",
    "total": "sum",
    "avg": "avg",
    "average": "avg",
    "mean": "avg",
    "min": "min",
    "minimum": "min",
    "max": "max",
    "maximum": "max",
}

VALID_FNS = frozenset({"count", "sum", "avg", "min", "max"})

#: `sum ( quantity * price )` — function name plus everything inside the outer
#: parens. Anchored, so prose that merely mentions a function is not mistaken
#: for one.
_CALL_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*$", re.DOTALL)

#: A bare column reference: the whole argument is one identifier.
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: `count(id)` and `count(*)` mean "how many rows". `id` is not a column the
#: runtime needs — `count()` takes none — and carrying it through made the
#: metric look like it wanted `COUNT(id)` over a column that may not exist.
_COUNT_STAR = {"*", "1", "id", "*)"}


def parse_expression(expression: object) -> dict | None:
    """``"sum(quantity * price)"`` -> ``{"fn": "sum", "expr": "quantity * price"}``.

    Returns None when the text is not an aggregate call this can vouch for, so
    the caller leaves the original metric untouched rather than guessing.
    """
    if not isinstance(expression, str) or not expression.strip():
        return None
    m = _CALL_RE.match(expression.strip())
    if not m:
        return None
    fn = _FN_ALIASES.get(m.group(1).strip().lower())
    if not fn:
        return None
    arg = m.group(2).strip()
    # `count(distinct owner)` is still a row count to the runtime, which has no
    # DISTINCT aggregate; counting rows is closer than failing to compute.
    arg = re.sub(r"^distinct\s+", "", arg, flags=re.IGNORECASE).strip()

    if fn == "count" or not arg or arg.lower() in _COUNT_STAR:
        return {"fn": "count"} if fn == "count" else None
    if _IDENT_RE.match(arg):
        return {"fn": fn, "field": arg}
    # Arithmetic (or anything else compound). Keep it verbatim under `expr` and
    # emit NO `field`: see the module docstring for why a synthetic field name
    # would be worse than an honest zero.
    return {"fn": fn, "expr": arg}


def normalize_metric(metric: object) -> dict | None:
    """Return `metric` in the runtime dialect, or None when it needs no change.

    A metric that already carries a valid `fn` is authoritative — an authoring
    agent that wrote both wins with the machine-readable half.
    """
    if not isinstance(metric, dict):
        return None
    if metric.get("fn") in VALID_FNS:
        return None
    parsed = parse_expression(metric.get("expression"))
    if parsed is None:
        return None
    out = {k: v for k, v in metric.items() if k != "expression"}
    out.update(parsed)
    return out


def normalize_source(source: object) -> int:
    """Normalise every metric on one dataSource IN PLACE. Returns how many changed."""
    if not isinstance(source, dict):
        return 0
    metrics = source.get("metrics")
    if not isinstance(metrics, dict):
        return 0
    changed = 0
    for key, metric in list(metrics.items()):
        fixed = normalize_metric(metric)
        if fixed is not None:
            metrics[key] = fixed
            changed += 1
    return changed


def normalize_sources(sources: object) -> int:
    """Normalise a page's whole `dataSources` list IN PLACE. Returns the count."""
    if not isinstance(sources, list):
        return 0
    return sum(normalize_source(s) for s in sources)


def repair_output_dir(output_dir: str) -> dict:
    """Rewrite `src/schemas/**/*.json` so no `expression` metric survives on disk.

    Generation is where this is fixed properly (see `page_planner.plan_page`),
    but every project already generated carries the old dialect in its page
    schemas, and those files are what the app and the editor read. This repairs
    them in place. Idempotent; a file it cannot parse is skipped, never lost.
    """
    sdir = os.path.join(output_dir, "src", "schemas")
    report = {"files": 0, "metrics": 0}
    if not os.path.isdir(sdir):
        return report
    for fp in sorted(glob.glob(os.path.join(sdir, "**", "*.json"), recursive=True)):
        try:
            with open(fp, encoding="utf-8") as fh:
                schema = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(schema, dict):
            continue
        changed = normalize_sources(schema.get("dataSources"))
        if not changed:
            continue
        try:
            with open(fp, "w", encoding="utf-8") as fh:
                json.dump(schema, fh, indent=2, sort_keys=True)
                fh.write("\n")
        except OSError:
            continue
        report["files"] += 1
        report["metrics"] += changed
    return report
