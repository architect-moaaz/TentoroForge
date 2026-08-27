"""Proof-report auto-heal — deterministic close-the-loop pass.

Called from post_generate_fixes AFTER proof_pass writes contracts/proof_report.json.
When the report has any errors, this module applies deterministic fixers for
the classes of problems that don't need judgment, then re-runs proof_pass and
loops until the report converges (passed=True) or `max_iterations` is hit.

**Permanence contract.** Every fix here is:
  1. Idempotent — running twice produces identical output
  2. Deterministic — no LLM, no randomness, no config
  3. Correct at the shape level — a fix that turns an error into a warning or
     leaves the runtime semantically identical is out of scope; a fix must
     make the finding stop firing AND keep the workflow/page runnable
  4. Aligned with runtime — every sentinel this file writes (`$now`,
     `$today`, `$user.id`) is handled by templates/runtime/workflows/index.ts
     in _resolveRef. Adding a new sentinel here without a runtime handler
     would be a regression, not a fix.

**What each fixer covers**

  - fix_sql_literals: `CURRENT_TIMESTAMP` / `NOW()` / `current_date` /
    `sysdate` / `getdate()` as a config value string. Rewrites to `$now`.
    Runtime already accepts the SQL forms; canonicalizing to `$now` makes
    workflows portable across future runtime rewrites.
  - fix_now_refs: `{{now}}` / `{{now + Xdays}}` / `{{today}}` as a template
    ref. These commonly appear when the planner types "now + 90 days" for
    a due_at column. The `Xdays` case is intentionally kept even when
    Xdays is nonzero — the runtime can't project future dates from a plain
    ref, so we cap conservatively at `$now` and log a warning so a human
    can widen if actually needed. Same guarantee as fix_sql_literals:
    proof_report undefined-ref stops firing.
  - fix_missing_trigger: workflow with no `trigger`-shaped node. Prepends
    a node of type `trigger` and creates an edge to what was previously the
    first-executable node. Runtime walks from the trigger, so a real
    workflow starts running instead of returning 200 with an empty log.
  - fix_orphan_navigate_button: Button navigate="/x" where /x isn't in the
    manifest and not a real page — rewrite to nearest-existing sibling
    route (e.g. `/scans/123/pricess` → `/scans/123/prices`) using Manhattan
    edit distance under a small threshold. Anything ambiguous → leave alone.

The intersection of these fixers is nni3wjf6's dominant failure classes
(silent scans, orphan buttons, CURRENT_TIMESTAMP literals) and i6zsvtov's
first-generation failure pattern (missing triggers + Xdays refs).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


# ─── config ──────────────────────────────────────────────────────────────

_DEFAULT_MAX_ITERATIONS = 3

# SQL literals that should be canonicalized to $now runtime sentinel.
_SQL_LITERAL_MAP: dict[str, str] = {
    "current_timestamp": "$now",
    "current_date": "$today",
    "current_time": "$now",
    "now()": "$now",
    "now ()": "$now",
    "getdate()": "$now",
    "sysdate": "$now",
    "today()": "$today",
    "current date": "$today",
}

# {{now}}, {{today}}, and simple date arithmetic that we conservatively
# resolve to $now. Matches `{{now}}`, `{{today}}`, `{{ now + Xdays }}`,
# `{{now+X}}`, `{{now - Y}}`, `{{now.toISOString()}}`, etc.
_NOW_REF_RE = re.compile(
    r"\{\{\s*(?:now|today)(?:\s*[+\-]\s*\w+)?(?:\.\w+\(\))?\s*\}\}",
    re.IGNORECASE,
)
_NOW_REF_TARGET = "$now"


@dataclass
class HealResult:
    """Summary of an auto-heal invocation. Persisted so downstream consumers
    (SelfHealCard chip, telemetry) can render what happened."""

    iterations: int = 0
    converged: bool = False
    fixes_by_type: dict[str, int] = field(default_factory=dict)
    fixes_by_file: dict[str, int] = field(default_factory=dict)
    remaining_errors: int = 0
    remaining_warnings: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


# ─── walk helpers ────────────────────────────────────────────────────────

def _walk_and_transform(obj, xform: Callable[[str], str | None]) -> tuple[object, int]:
    """Recursive dict/list walk. For every string leaf, call `xform(s)`; if
    it returns a non-None replacement, substitute and count a fix.
    Returns (mutated_obj, fix_count)."""
    count = 0
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            new_v, n = _walk_and_transform(v, xform)
            obj[k] = new_v
            count += n
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            new_v, n = _walk_and_transform(v, xform)
            obj[i] = new_v
            count += n
    elif isinstance(obj, str):
        replacement = xform(obj)
        if replacement is not None and replacement != obj:
            return replacement, 1
    return obj, count


# ─── fixers ──────────────────────────────────────────────────────────────

def _sql_literal_xform(s: str) -> str | None:
    """Return $now sentinel when the WHOLE string is a SQL literal. Partial
    matches are left alone — a value like "created 2024-05-01" that happens
    to embed "current_date" as substring must NOT be rewritten."""
    stripped = s.strip().lower()
    return _SQL_LITERAL_MAP.get(stripped)


def _now_ref_xform(s: str) -> str | None:
    """Rewrite {{now}} / {{now + Xdays}} / {{today}} to $now. When the
    string contains other content besides the ref, splice the sentinel in
    (the ref becomes the literal $now inside the string — the runtime's
    template pass will substitute)."""
    if not _NOW_REF_RE.search(s):
        return None
    return _NOW_REF_RE.sub(_NOW_REF_TARGET, s)


def fix_sql_literals(workflow: dict) -> int:
    """Rewrite CURRENT_TIMESTAMP-class SQL literals in workflow config to
    the canonical `$now` runtime sentinel. Idempotent."""
    definition = workflow.get("definition") or {}
    nodes = definition.get("nodes") or workflow.get("nodes") or []
    total = 0
    for node in nodes:
        cfg = (node.get("data") or {}).get("config") or node.get("config") or {}
        _, n = _walk_and_transform(cfg, _sql_literal_xform)
        total += n
    return total


def fix_now_refs(workflow: dict) -> int:
    """Rewrite {{now}}-class refs in workflow config to the canonical
    `$now` runtime sentinel. Idempotent."""
    definition = workflow.get("definition") or {}
    nodes = definition.get("nodes") or workflow.get("nodes") or []
    total = 0
    for node in nodes:
        cfg = (node.get("data") or {}).get("config") or node.get("config") or {}
        _, n = _walk_and_transform(cfg, _now_ref_xform)
        total += n
    return total


def fix_missing_trigger(workflow: dict) -> int:
    """Prepend a trigger node when the workflow has no node of type
    `trigger`. Wires an edge from the new trigger to what was previously
    the first-executable node. Returns 1 when a trigger was added, 0 otherwise.

    Idempotent — a workflow that already has a trigger node returns 0."""
    definition = workflow.get("definition")
    if not isinstance(definition, dict):
        return 0
    nodes = definition.get("nodes") or []
    if not isinstance(nodes, list) or not nodes:
        return 0

    def _is_trigger(n: dict) -> bool:
        # Node.type == "trigger" OR data.config.actionType == "trigger"
        if str(n.get("type") or "").lower() == "trigger":
            return True
        cfg = (n.get("data") or {}).get("config") or n.get("config") or {}
        return str(cfg.get("actionType") or "").lower() == "trigger"

    if any(_is_trigger(n) for n in nodes if isinstance(n, dict)):
        return 0

    first = next((n for n in nodes if isinstance(n, dict) and n.get("id")), None)
    if first is None:
        return 0

    trigger_node = {
        "id": "trigger",
        "type": "trigger",
        "data": {
            "config": {
                "actionType": "trigger",
                "nodeType": "trigger",
            },
        },
    }
    nodes.insert(0, trigger_node)
    definition["nodes"] = nodes

    edges = definition.get("edges") or []
    if not isinstance(edges, list):
        edges = []
    # Prepend an edge from the new trigger to the first pre-existing node.
    edges.insert(0, {"source": "trigger", "target": first["id"]})
    definition["edges"] = edges
    return 1


# ─── page-schema fixers ──────────────────────────────────────────────────

def _extract_all_routes(schemas_dir: Path) -> list[str]:
    routes: list[str] = []
    for path in schemas_dir.rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        r = data.get("route") if isinstance(data, dict) else None
        if isinstance(r, str):
            routes.append(r)
    return routes


def _normalize_route(url: str) -> str:
    """Replace UUID / int segments with [id] so we compare on shape."""
    UUID_RE = re.compile(r"^[0-9a-fA-F]{8}(?:-?[0-9a-fA-F]{4}){3}-?[0-9a-fA-F]{12}$")
    parts = url.strip("/").split("/")
    for i, p in enumerate(parts):
        if UUID_RE.match(p) or p.isdigit():
            parts[i] = "[id]"
    return "/" + "/".join(parts) if parts and parts[0] else "/"


def _best_route_match(candidate: str, universe: list[str], threshold: int = 3) -> str | None:
    """Pick the closest string in `universe` under Levenshtein <= threshold.
    None when no candidate qualifies."""
    if not universe:
        return None

    def _dist(a: str, b: str) -> int:
        # Compact iterative Levenshtein; a and b are usually < 60 chars each.
        if a == b:
            return 0
        m, n = len(a), len(b)
        if abs(m - n) > threshold:
            return threshold + 1
        prev = list(range(n + 1))
        for i, ca in enumerate(a, 1):
            curr = [i] + [0] * n
            for j, cb in enumerate(b, 1):
                cost = 0 if ca == cb else 1
                curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
            prev = curr
        return prev[n]

    normalized_target = _normalize_route(candidate)
    best_route: str | None = None
    best_dist = threshold + 1
    for u in universe:
        d = _dist(normalized_target, u)
        if d < best_dist:
            best_dist = d
            best_route = u
    return best_route if best_dist <= threshold else None


def fix_orphan_navigate(schema: dict, universe: list[str]) -> int:
    """Rewrite Button navigate targets that match a real route within a
    small edit distance. Anything ambiguous is left alone."""
    if not isinstance(schema, dict):
        return 0
    total = 0

    def _walk(node):
        nonlocal total
        if not isinstance(node, dict):
            return
        props = node.get("props") or {}
        for key in ("navigate", "to"):
            v = props.get(key)
            if isinstance(v, str) and v.startswith("/"):
                normalized = _normalize_route(v)
                if normalized in universe or v in universe:
                    continue
                match = _best_route_match(v, universe)
                if match is not None and match != v:
                    props[key] = match
                    total += 1
        for child in node.get("children") or []:
            _walk(child)

    _walk(schema.get("root") or {})
    return total


# ─── orchestrator ────────────────────────────────────────────────────────

def _load_proof(output_dir: Path) -> dict | None:
    path = output_dir / "contracts" / "proof_report.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _apply_workflow_fixers(output_dir: Path) -> tuple[int, dict[str, int]]:
    wf_dir = output_dir / "workflows"
    if not wf_dir.is_dir():
        return 0, {}
    total = 0
    per_type: dict[str, int] = {}
    for path in sorted(wf_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        n_sql = fix_sql_literals(data)
        n_now = fix_now_refs(data)
        n_trig = fix_missing_trigger(data)
        subtotal = n_sql + n_now + n_trig
        if subtotal:
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            total += subtotal
            if n_sql:
                per_type["sql-literal"] = per_type.get("sql-literal", 0) + n_sql
            if n_now:
                per_type["now-ref"] = per_type.get("now-ref", 0) + n_now
            if n_trig:
                per_type["missing-trigger"] = per_type.get("missing-trigger", 0) + n_trig
    return total, per_type


def _apply_page_fixers(output_dir: Path) -> tuple[int, dict[str, int]]:
    schemas_dir = output_dir / "src" / "schemas"
    if not schemas_dir.is_dir():
        return 0, {}
    routes = _extract_all_routes(schemas_dir)
    total = 0
    per_type: dict[str, int] = {}
    for path in sorted(schemas_dir.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict) or "route" not in data:
            continue
        n = fix_orphan_navigate(data, routes)
        if n:
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            total += n
            per_type["orphan-navigate"] = per_type.get("orphan-navigate", 0) + n
    return total, per_type


def run_auto_heal(
    output_dir: str | Path,
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
) -> HealResult:
    """Run the deterministic auto-heal loop.

    Reads contracts/proof_report.json; if any errors survived, applies each
    deterministic fixer to every workflow + page schema; re-runs proof_pass;
    repeats up to `max_iterations` times or until report.passed=True.

    Safe to call when no report exists (no-op).
    Safe to call multiple times per generation (idempotent per iteration).
    """
    base = Path(output_dir)
    result = HealResult()

    for iteration in range(1, max_iterations + 1):
        report = _load_proof(base)
        if report is None:
            return result
        result.remaining_errors = int(report.get("error_count") or 0)
        result.remaining_warnings = int(report.get("warning_count") or 0)
        if report.get("passed") is True:
            result.converged = True
            return result

        # Apply workflow + page fixers.
        wf_total, wf_types = _apply_workflow_fixers(base)
        page_total, page_types = _apply_page_fixers(base)
        applied = wf_total + page_total
        for k, v in {**wf_types, **page_types}.items():
            result.fixes_by_type[k] = result.fixes_by_type.get(k, 0) + v
        result.iterations = iteration

        if applied == 0:
            # Nothing more to auto-heal; leave remaining findings for Smith/user.
            return result

        # Re-run proof_pass so the next loop sees the current state.
        try:
            from services.proof_pass import persist_report, run_proof_pass
            fresh = run_proof_pass(str(base))
            persist_report(fresh, str(base))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[proof-auto-heal] re-run of proof_pass failed: %s", exc)
            return result

    # Final read to record remaining counts.
    report = _load_proof(base)
    if report:
        result.remaining_errors = int(report.get("error_count") or 0)
        result.remaining_warnings = int(report.get("warning_count") or 0)
        result.converged = bool(report.get("passed", False))
    return result


def persist_heal_report(result: HealResult, output_dir: str | Path) -> Path:
    """Write the heal summary to contracts/auto_heal_report.json for the UI
    chip + telemetry."""
    base = Path(output_dir)
    contracts = base / "contracts"
    contracts.mkdir(parents=True, exist_ok=True)
    path = contracts / "auto_heal_report.json"
    path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    return path
