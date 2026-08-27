"""Rules-engine fabricated-field gate — Phase 2.3 backstop.

The rules engine sometimes ships rules that reference entities/fields the
LockedSpec never declared. Nni3wjf6 had rules like `scan-user-id-required`
and `scan-status-valid-enum` that blocked inserts because the LLM had
authored plausible-sounding but unreferenceable rules.

This validator sweeps `<output_dir>/src/rules/index.json` (and any nested
rules JSON) and flags rules whose:

- entity        isn't in the locked spec / manifest, OR
- field         isn't declared on the target entity in the plan, OR
- workflow_ref  points at a workflow name not in the manifest.

Rules that violate become findings. Callers persist the report to
`contracts/rules_validation.json` and (optionally) delete or disable the
offending rule via a follow-up pass. This module is validation-only —
never mutates rules on its own.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from services.locked_spec import load_locked_spec
from services.scope_card import load_manifest

logger = logging.getLogger(__name__)

Severity = Literal["error", "warning"]


@dataclass
class Finding:
    severity: Severity
    code: str
    message: str
    rule_file: str
    rule_name: str | None = None
    locator: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _plan_fields_for_entity(plan: dict, entity_name: str) -> set[str]:
    """Pull the declared field names for `entity_name` from a persisted
    plan.json. Case-insensitive match on entity name."""
    if not isinstance(plan, dict):
        return set()
    entities = plan.get("entities")
    entries: list[dict] = []
    if isinstance(entities, dict):
        entries = [
            {"name": k, **(v if isinstance(v, dict) else {})}
            for k, v in entities.items()
        ]
    elif isinstance(entities, list):
        entries = [e for e in entities if isinstance(e, dict)]
    target = entity_name.lower()
    for e in entries:
        name = str(e.get("name") or e.get("entity") or "").lower()
        if name != target:
            continue
        fields = e.get("fields") or e.get("columns") or []
        out: set[str] = set()
        for f in fields:
            if isinstance(f, dict):
                fn = f.get("name") or f.get("column")
                if isinstance(fn, str):
                    out.add(fn.lower())
            elif isinstance(f, str):
                out.add(f.lower())
        return out
    return set()


def _iter_rules(data) -> list[dict]:
    """Rules JSON files can be a flat array or wrap under a `rules` key.
    Return whatever list we can find; ignore anything malformed."""
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        if isinstance(data.get("rules"), list):
            return [r for r in data["rules"] if isinstance(r, dict)]
    return []


def _rule_targets(rule: dict) -> tuple[str | None, str | None]:
    """(entity, field). Rules sometimes use `on`/`when`/`target` keys."""
    for key in ("entity", "on", "target", "when"):
        v = rule.get(key)
        if isinstance(v, str):
            # Support "Scan.userId" dotted form.
            if "." in v:
                left, right = v.split(".", 1)
                return left, right
            return v, None
        if isinstance(v, dict):
            e = v.get("entity") or v.get("table")
            f = v.get("field") or v.get("column")
            if isinstance(e, str):
                return e, f if isinstance(f, str) else None
    return None, None


def _rule_workflow_ref(rule: dict) -> str | None:
    for key in ("workflow", "workflow_ref", "workflowName", "action"):
        v = rule.get(key)
        if isinstance(v, str) and v:
            return v
    return None


def validate_rules(
    rules: list[dict],
    rule_file: str,
    *,
    entity_names: set[str],
    workflow_names: set[str],
    plan: dict | None = None,
) -> list[Finding]:
    """Pure validator — sweeps a rules list and returns findings.

    Args:
        rules: parsed rules from the JSON.
        rule_file: filename for reporting.
        entity_names: lower-cased set of entities allowed in the spec.
        workflow_names: set of allowed workflow names (case-sensitive —
            workflow ids are treated as canonical).
        plan: optional persisted plan for field-level checks.
    """
    out: list[Finding] = []
    for r in rules:
        name = r.get("name") if isinstance(r.get("name"), str) else None
        entity, field = _rule_targets(r)
        if entity is not None:
            if entity.lower() not in entity_names:
                out.append(Finding(
                    severity="error",
                    code="rule-unknown-entity",
                    message=(
                        f'Rule "{name}" targets entity "{entity}" which is not '
                        f'declared in the locked spec. Registered entities: '
                        f'{sorted(entity_names)}'
                    ),
                    rule_file=rule_file,
                    rule_name=name,
                    locator=f"entity={entity}",
                ))
            elif field and plan:
                declared = _plan_fields_for_entity(plan, entity)
                # Only check field membership when the plan actually declared
                # some fields for the entity — otherwise silence is safer than
                # false positives on entities the plan describes lightly.
                if declared and field.lower() not in declared:
                    out.append(Finding(
                        severity="warning",
                        code="rule-unknown-field",
                        message=(
                            f'Rule "{name}" references field "{entity}.{field}" '
                            f'but the plan does not declare that field on '
                            f'{entity}. Fields the plan declares: '
                            f'{sorted(declared)}'
                        ),
                        rule_file=rule_file,
                        rule_name=name,
                        locator=f"field={entity}.{field}",
                    ))
        wf = _rule_workflow_ref(r)
        if wf and wf not in workflow_names:
            out.append(Finding(
                severity="warning",
                code="rule-unknown-workflow",
                message=(
                    f'Rule "{name}" references workflow "{wf}" which is not '
                    f'declared in the manifest.'
                ),
                rule_file=rule_file,
                rule_name=name,
                locator=f"workflow={wf}",
            ))
    return out


def validate_output_dir(output_dir: str | Path) -> list[Finding]:
    """End-to-end: load spec + manifest + plan, sweep every rules JSON."""
    base = Path(output_dir)
    spec = load_locked_spec(output_dir)
    manifest = load_manifest(output_dir)

    if spec is None and manifest is None:
        return []

    entity_names: set[str] = set()
    if spec is not None:
        entity_names |= {e.name.lower() for e in spec.entities}
    if manifest is not None:
        entity_names |= {e.lower() for e in manifest.entities_with_tables}
    workflow_names: set[str] = set(manifest.workflows) if manifest else set()

    plan: dict | None = None
    for candidate in (
        base / "src" / "contracts" / "plan.json",
        base / "contracts" / "plan.json",
        base / "plan.json",
    ):
        if candidate.exists():
            try:
                plan = json.loads(candidate.read_text(encoding="utf-8"))
                break
            except Exception:
                continue

    findings: list[Finding] = []
    for rules_dir in (base / "src" / "rules", base / "rules"):
        if not rules_dir.is_dir():
            continue
        for path in sorted(rules_dir.rglob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            rules = _iter_rules(data)
            if not rules:
                continue
            rel = str(path.relative_to(base).as_posix())
            findings.extend(validate_rules(
                rules,
                rel,
                entity_names=entity_names,
                workflow_names=workflow_names,
                plan=plan,
            ))
    return findings


def persist_report(findings: list[Finding], output_dir: str | Path) -> Path:
    base = Path(output_dir)
    contracts_dir = base / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    path = contracts_dir / "rules_validation.json"
    path.write_text(
        json.dumps([f.to_dict() for f in findings], indent=2),
        encoding="utf-8",
    )
    return path
