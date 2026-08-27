"""Workflow JSON validator — Phase 2's O4/O5/O6 backstop.

Runs after the planner/LLM emits workflow definitions. Catches the class of
authoring bugs that shipped in nni3wjf6 with no ceremony:

- O4: `{{status}}` — a value template that references a variable name
      the workflow never sets. Runtime dispatches it as literal string
      "{{status}}" or empty; `status` column silently stays null.
- O5: `{{identify_product.rawAiResponse}}` — dot-path into a node output
      that doesn't declare that field. ai_extract writes fields at the
      root of its output; `.rawAiResponse` doesn't exist.
- O6: `"CURRENT_TIMESTAMP"` — a SQL literal string used where the runtime
      expects a sentinel like `"$now"`. Insert stores the literal string
      or fails on type coercion.

Returns a list of Findings; each has severity ("error"|"warning"), a short
message, and a locator (workflow file + node id + config path). Callers
that want a hard gate set FORGE_WORKFLOW_STRICT=true and treat any error
as ship-blocker; the default is warn-and-continue so an early roll-out
doesn't break existing apps.

Reads a LockedSpec (if present) to know which entities are declared as
event kind — a workflow that writes to an event entity MUST also set its
status column (O12).
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from services.locked_spec import LockedSpec, load_locked_spec
from services.workflow_mutation_guard import collect_provided_vars


Severity = Literal["error", "warning"]


@dataclass
class Finding:
    severity: Severity
    code: str
    message: str
    workflow_file: str
    node_id: str | None = None
    config_path: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# ---------- ref discovery -------------------------------------------------

# Curly-brace ref matcher — captures the inner expression (e.g. `foo.bar[0].baz`).
_REF_RE = re.compile(r"\{\{([^{}]+?)\}\}")

# Sentinel strings that runtime knows about. Everything else that looks like
# a SQL literal ("CURRENT_TIMESTAMP", "NOW()", "current_date") is a bug.
_SQL_LITERAL_BUGS = {
    "current_timestamp", "current_date", "current_time",
    "now()", "now ()", "getdate()", "sysdate",
}

# Recognized runtime sentinels (the correct alternative to literal SQL strings).
_KNOWN_SENTINELS = {"$now", "$today", "$user", "$user.id"}

# Exact-case spellings the runtime keeps as backwards-compat aliases for
# `$now` (_resolveRef in templates/runtime/workflows/index.ts). These WORK at
# runtime, so they are style warnings, not errors. Any other casing/variant
# ("current_timestamp", "getdate()", …) is stored as a literal string → error.
_RUNTIME_LITERAL_ALIASES = {"CURRENT_TIMESTAMP", "NOW()"}


def _walk_values(obj, path: str = "") -> list[tuple[str, str]]:
    """Yield (path, value) for every string leaf in obj. Used to sweep for
    binding refs + SQL literals without knowing the exact node config shape."""
    out: list[tuple[str, str]] = []
    if isinstance(obj, str):
        out.append((path or "$", obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(_walk_values(v, f"{path}.{k}" if path else k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(_walk_values(v, f"{path}[{i}]"))
    return out


def _refs_in(value: str) -> list[str]:
    """All `{{...}}` refs in a string, inner expression only (whitespace-stripped)."""
    return [m.group(1).strip() for m in _REF_RE.finditer(value)]


def _ref_root(ref: str) -> str:
    """First segment of a dot-path ref. `foo.bar[0].baz` → `foo`."""
    # Peel leading segment before `.` or `[`.
    m = re.match(r"[A-Za-z_][A-Za-z0-9_]*", ref)
    return m.group(0) if m else ref


# ---------- per-workflow validators ---------------------------------------

def _declared_names(workflow: dict) -> set[str]:
    """Every name that can appear as a ref-root within this workflow: node
    ids, `trigger`, `input`, `event`, `context`, declared processVariables /
    trigger inputs, and every variable a step PRODUCES (outputVar and
    friends, ai_extract's aiExtractFields — the runtime exposes each
    extracted field as a top-level variable). This is what {{...}} refs
    must resolve to."""
    names: set[str] = {"trigger", "input", "event", "context", "process", "processVariables"}
    # Trigger inputs (processVariables, inputMapping/inputs) + step output
    # vars + the always-present `id` — same resolution scope the mutation
    # guard and file_first_forms use, so the validators can't drift apart.
    names |= collect_provided_vars(workflow)
    for node in ((workflow.get("definition") or {}).get("nodes") or workflow.get("nodes") or []):
        nid = node.get("id")
        if nid:
            names.add(nid)
        cfg = (node.get("data") or {}).get("config") or node.get("config") or {}
        # Step-produced variables: set_variable's variableName plus the
        # outputVar aliases every emitter uses on http_call/db_query/ai_*.
        for key in ("variableName", "outputVariable", "outputVar", "resultVar",
                    "resultVariable", "assignTo"):
            var_name = cfg.get(key)
            if isinstance(var_name, str) and var_name:
                names.add(var_name)
        # ai_extract publishes each extracted field as a top-level variable
        # (runtime ai.ts), so `{{extractedFields}}` etc. resolve downstream.
        fields = cfg.get("aiExtractFields")
        if isinstance(fields, list):
            for f in fields:
                if isinstance(f, str) and f:
                    names.add(f)
                elif isinstance(f, dict) and isinstance(f.get("name"), str):
                    names.add(f["name"])
        # outputParams: an alternative declaration of writes.
        out_params = cfg.get("outputParams")
        if isinstance(out_params, list):
            for p in out_params:
                if isinstance(p, dict):
                    nm = p.get("name") or p.get("target")
                    if isinstance(nm, str) and nm:
                        names.add(nm)
    return names


def _validate_refs(workflow: dict, workflow_file: str) -> list[Finding]:
    """O4: every {{ref}} must have a root the workflow declares."""
    findings: list[Finding] = []
    declared = _declared_names(workflow)
    for node in ((workflow.get("definition") or {}).get("nodes") or workflow.get("nodes") or []):
        nid = node.get("id", "?")
        cfg = (node.get("data") or {}).get("config") or node.get("config") or {}
        for path, val in _walk_values(cfg):
            for ref in _refs_in(val):
                root = _ref_root(ref)
                if not root:
                    continue
                if root in declared:
                    continue
                findings.append(Finding(
                    severity="error",
                    code="undefined-ref",
                    message=f'"{{{{{ref}}}}}" references "{root}" which is not '
                            f'declared as a node id, trigger, input, event, context, '
                            f'or process variable in this workflow.',
                    workflow_file=workflow_file,
                    node_id=nid,
                    config_path=path,
                ))
    return findings


def _validate_sql_literals(workflow: dict, workflow_file: str) -> list[Finding]:
    """O6: `"CURRENT_TIMESTAMP"` and friends stored as literal strings."""
    findings: list[Finding] = []
    for node in ((workflow.get("definition") or {}).get("nodes") or workflow.get("nodes") or []):
        nid = node.get("id", "?")
        cfg = (node.get("data") or {}).get("config") or node.get("config") or {}
        for path, val in _walk_values(cfg):
            low = val.strip().lower()
            if low in _SQL_LITERAL_BUGS:
                aliased = val.strip() in _RUNTIME_LITERAL_ALIASES
                findings.append(Finding(
                    severity="warning" if aliased else "error",
                    code="sql-literal-in-value",
                    message=(
                        f'"{val}" is a legacy alias the runtime maps to "$now" — '
                        f'works, but prefer the "$now" sentinel.'
                        if aliased else
                        f'"{val}" is a SQL literal used as a runtime value. '
                        f'Use a runtime sentinel (e.g. "$now") or a real '
                        f'template expression instead.'
                    ),
                    workflow_file=workflow_file,
                    node_id=nid,
                    config_path=path,
                ))
    return findings


def _validate_event_status_writes(
    workflow: dict, workflow_file: str, spec: LockedSpec | None
) -> list[Finding]:
    """O12: if the workflow writes to an event entity, it must also set the
    status field somewhere in the walk. Without this, event rows land as
    status=pending forever (nni3wjf6 symptom)."""
    if spec is None:
        return []
    event_names = {e.name.lower() for e in spec.entities if e.kind == "event"}
    if not event_names:
        return []

    # Find every db_insert/db_update on an event entity's table.
    event_writes: list[tuple[str, str]] = []  # (node_id, entity_lower)
    status_writes: set[str] = set()  # entity lowercase names that got a status write
    for node in ((workflow.get("definition") or {}).get("nodes") or workflow.get("nodes") or []):
        nid = node.get("id", "?")
        cfg = (node.get("data") or {}).get("config") or node.get("config") or {}
        action = cfg.get("actionType")
        table = str(cfg.get("table") or "").lower()
        values = cfg.get("values")
        # Try to match table against event names (case-insensitive, tolerate
        # trailing s / camelCase). Simple: any event whose lowercased name is
        # a substring of the table or vice versa.
        matched = next(
            (e for e in event_names if e in table or table in e),
            None,
        )
        if matched and action in ("db_insert", "db_update"):
            event_writes.append((nid, matched))
            if isinstance(values, dict) and "status" in {k.lower() for k in values}:
                # Any non-empty status template counts as "written".
                for k, v in values.items():
                    if k.lower() != "status":
                        continue
                    if isinstance(v, str) and v.strip():
                        status_writes.add(matched)

    findings: list[Finding] = []
    written_events = {e for _, e in event_writes}
    for ev in written_events:
        if ev not in status_writes:
            findings.append(Finding(
                severity="warning",
                code="event-status-not-written",
                message=f'Workflow writes to event entity "{ev}" but never '
                        f'writes its "status" column. Event rows will land '
                        f'without a status and stay stuck on the default forever.',
                workflow_file=workflow_file,
            ))
    return findings


# ---------- public API ----------------------------------------------------

def validate_workflow(workflow: dict, workflow_file: str, spec: LockedSpec | None = None) -> list[Finding]:
    """Run all validators over one workflow JSON. Returns flat list of findings."""
    out: list[Finding] = []
    out.extend(_validate_refs(workflow, workflow_file))
    out.extend(_validate_sql_literals(workflow, workflow_file))
    out.extend(_validate_event_status_writes(workflow, workflow_file, spec))
    return out


def validate_output_dir(output_dir: str | Path) -> list[Finding]:
    """Sweep every workflow JSON in `<output_dir>/workflows/`. Loads the
    locked spec if present so the O12 event-status check has context."""
    base = Path(output_dir)
    wf_dir = base / "workflows"
    if not wf_dir.is_dir():
        return []
    spec = load_locked_spec(output_dir)
    findings: list[Finding] = []
    for wf_path in sorted(wf_dir.glob("*.json")):
        try:
            data = json.loads(wf_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        findings.extend(validate_workflow(data, str(wf_path.name), spec))
    return findings


def persist_report(findings: list[Finding], output_dir: str | Path) -> Path:
    """Write findings to contracts/workflow_validation.json for downstream
    consumers (proof pass, self-heal chip, etc.)."""
    base = Path(output_dir)
    contracts_dir = base / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    path = contracts_dir / "workflow_validation.json"
    path.write_text(
        json.dumps([f.to_dict() for f in findings], indent=2),
        encoding="utf-8",
    )
    return path
