"""interaction_authority — Spec E Wave 1.

Validates the planner-emitted `interactions` block (and the equivalent
Table/Kanban prop-level declarations that make it into a page schema)
against the resource registry. Only known entities, only real columns,
only real workflow names for `bulk_actions`.

Flag-gated on ``FORGE_E_INTERACTIONS`` — off by default. When on and a
declaration is unreconcilable, the invalid field is stripped so the
generated app never ships a broken drag/drop or bulk-action that would
hit a missing endpoint. All findings are persisted to
``contracts/interaction_authority.json`` for the frontend chip.

Kept intentionally close-scoped: this module does NOT rewrite pages
that omit interactions (the planner is free to leave them off). It only
sanitises what the planner asked for.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


def is_enabled() -> bool:
    """FORGE_E_INTERACTIONS truthy — the spec's opt-in flag."""
    return os.getenv("FORGE_E_INTERACTIONS", "0").strip().lower() in {
        "1", "true", "yes", "on",
    }


@dataclass
class Finding:
    kind: str          # unknown_entity | unknown_column | unknown_workflow | shape
    where: str         # file + json-pointer-ish path
    detail: str
    action: str        # "stripped" | "warned"


@dataclass
class Report:
    enabled: bool = False
    findings: list[Finding] = field(default_factory=list)
    tables_seen: int = 0
    kanbans_seen: int = 0
    files_written: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "tables_seen": self.tables_seen,
            "kanbans_seen": self.kanbans_seen,
            "files_written": self.files_written,
            "findings": [asdict(f) for f in self.findings],
        }


# ---------------------------------------------------------------------------
# Registry lookups
# ---------------------------------------------------------------------------

def _load_registry(root: Path) -> dict[str, Any]:
    fp = root / "registry.json"
    if not fp.exists():
        return {}
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _entity_lookup(reg: dict[str, Any]) -> dict[str, str]:
    """Norm(entity_name) → canonical entity name."""
    out: dict[str, str] = {}
    for name in (reg.get("entities") or {}):
        out[_norm(name)] = name
    return out


def _fields_of(reg: dict[str, Any], entity: str) -> set[str]:
    ent = (reg.get("entities") or {}).get(entity) or {}
    fields = ent.get("fields") or {}
    return {str(k) for k in fields.keys()}


def _workflow_names(reg: dict[str, Any]) -> set[str]:
    # Workflow bindings are keyed by workflow step name in the current
    # registry shape; treat those as the canonical set of dispatchable
    # workflow names.
    return {str(k) for k in (reg.get("workflow_bindings") or {}).keys()}


# ---------------------------------------------------------------------------
# Schema-page traversal
# ---------------------------------------------------------------------------

def _iter_nodes(node: Any) -> Iterable[dict]:
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _iter_nodes(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_nodes(v)


def _page_entity(schema: dict, stem: str, entities_lu: dict[str, str]) -> str | None:
    """Best-guess entity for a page based on its dataSources / stem."""
    for src in (schema.get("dataSources") or []):
        if isinstance(src, dict) and src.get("entity"):
            can = entities_lu.get(_norm(str(src["entity"])))
            if can:
                return can
    can = entities_lu.get(_norm(stem))
    return can


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_table(
    node: dict,
    entity_hint: str | None,
    reg: dict[str, Any],
    entities_lu: dict[str, str],
    workflows: set[str],
    where: str,
    findings: list[Finding],
) -> bool:
    """Return True when the node was mutated."""
    props = node.get("props") if isinstance(node.get("props"), dict) else None
    if not props:
        return False
    mutated = False

    # entity resolution — dataSource.entity beats page-level hint
    entity = entity_hint
    ds = props.get("dataSource")
    if isinstance(ds, dict) and ds.get("entity"):
        entity = entities_lu.get(_norm(str(ds["entity"]))) or entity

    if props.get("reorderable") is True:
        if not entity:
            findings.append(Finding(
                kind="unknown_entity",
                where=where,
                detail="Table.reorderable set but no resolvable entity",
                action="stripped",
            ))
            props.pop("reorderable", None)
            mutated = True

    if props.get("selectionMode") not in (None, "single", "multi"):
        findings.append(Finding(
            kind="shape",
            where=where,
            detail=f"Table.selectionMode must be 'single'|'multi' — got {props.get('selectionMode')!r}",
            action="stripped",
        ))
        props.pop("selectionMode", None)
        mutated = True

    bulk = props.get("bulkActions")
    if isinstance(bulk, list):
        clean: list[dict] = []
        for i, action in enumerate(bulk):
            if not isinstance(action, dict):
                continue
            wf = action.get("workflow")
            if not isinstance(wf, str) or not wf:
                findings.append(Finding(
                    kind="shape", where=f"{where}.bulkActions[{i}]",
                    detail="workflow name required", action="stripped",
                ))
                continue
            if workflows and wf not in workflows:
                findings.append(Finding(
                    kind="unknown_workflow", where=f"{where}.bulkActions[{i}]",
                    detail=f"workflow {wf!r} not in registry", action="stripped",
                ))
                continue
            clean.append(action)
        if clean != bulk:
            if clean:
                props["bulkActions"] = clean
            else:
                props.pop("bulkActions", None)
            mutated = True
    return mutated


def _validate_kanban(
    node: dict,
    entity_hint: str | None,
    reg: dict[str, Any],
    entities_lu: dict[str, str],
    where: str,
    findings: list[Finding],
) -> bool:
    props = node.get("props") if isinstance(node.get("props"), dict) else None
    if not props:
        return False
    mbl = props.get("moveBetweenLanes")
    if not isinstance(mbl, dict):
        return False
    src_field = mbl.get("sourceField")
    if not isinstance(src_field, str) or not src_field:
        findings.append(Finding(
            kind="shape", where=f"{where}.moveBetweenLanes",
            detail="sourceField required", action="stripped",
        ))
        props.pop("moveBetweenLanes", None)
        return True
    entity = entity_hint
    if not entity:
        findings.append(Finding(
            kind="unknown_entity", where=where,
            detail="Kanban.moveBetweenLanes set but no resolvable entity", action="stripped",
        ))
        props.pop("moveBetweenLanes", None)
        return True
    cols = _fields_of(reg, entity)
    if cols and src_field not in cols:
        findings.append(Finding(
            kind="unknown_column",
            where=f"{where}.moveBetweenLanes.sourceField",
            detail=f"{entity}.{src_field} not in registry columns",
            action="stripped",
        ))
        props.pop("moveBetweenLanes", None)
        return True
    return False


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def validate_output_dir(output_dir: str | Path) -> Report:
    """Sweep every page schema and sanitise interaction declarations."""
    report = Report(enabled=is_enabled())
    root = Path(output_dir)
    if not report.enabled or not root.exists():
        return report

    reg = _load_registry(root)
    entities_lu = _entity_lookup(reg)
    workflows = _workflow_names(reg)

    schemas_dir = root / "src" / "schemas"
    if not schemas_dir.exists():
        return report

    for fp in schemas_dir.glob("**/*.json"):
        try:
            schema = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        entity_hint = _page_entity(schema, fp.stem, entities_lu)
        rel = fp.relative_to(root)
        mutated = False
        for node in _iter_nodes(schema):
            if not isinstance(node, dict):
                continue
            t = node.get("type")
            if t == "Table":
                report.tables_seen += 1
                if _validate_table(node, entity_hint, reg, entities_lu, workflows,
                                   f"{rel}::Table", report.findings):
                    mutated = True
            elif t == "Kanban":
                report.kanbans_seen += 1
                if _validate_kanban(node, entity_hint, reg, entities_lu,
                                    f"{rel}::Kanban", report.findings):
                    mutated = True
        if mutated:
            try:
                fp.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
                report.files_written += 1
            except Exception as exc:
                logger.warning("interaction_authority: failed to write %s: %s", fp, exc)

    return report


def persist_report(report: Report, output_dir: str | Path) -> None:
    root = Path(output_dir)
    if not root.exists():
        return
    contracts = root / "contracts"
    contracts.mkdir(parents=True, exist_ok=True)
    (contracts / "interaction_authority.json").write_text(
        json.dumps(report.to_json(), indent=2) + "\n", encoding="utf-8",
    )
