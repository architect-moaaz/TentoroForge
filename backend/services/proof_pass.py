"""Proof Pass — Phase 5.1: post-generation assertions.

Runs after generation completes. Combines the outputs of workflow_validator
and contract_validator plus a small set of ship-quality assertions specific
to page renderability:

- **empty-page**: a page whose root is only Heading + Row (no data, no
  form, no list). Flagged as warning — usually the LLM shipped a stub.
- **list-without-repeat**: a page declares a list dataSource but no
  Repeat node exists to iterate it. Rows won't render.
- **repeat-without-list-source**: a Repeat's `bind` doesn't match any
  op:list dataSource on the page. Would render 0 rows silently.
- **duplicate-route**: two page schemas declare the same route.

Writes a consolidated proof_report.json to contracts/ that the frontend
chip can render, and returns True when no errors survived (proof passed).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from services.contract_validator import validate_output_dir as validate_contracts_dir
from services.workflow_validator import validate_output_dir as validate_workflows_dir


Severity = Literal["error", "warning"]


@dataclass
class ProofFinding:
    severity: Severity
    code: str
    message: str
    file: str
    locator: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProofReport:
    passed: bool = True
    error_count: int = 0
    warning_count: int = 0
    findings: list[ProofFinding] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "findings": [f.to_dict() for f in self.findings],
        }


# ---------- proof checks --------------------------------------------------

def _walk_nodes(node):
    if not isinstance(node, dict):
        return
    yield node
    for child in node.get("children") or []:
        yield from _walk_nodes(child)


def _check_empty_pages(schemas_dir: Path) -> list[ProofFinding]:
    """A page whose only descendants are chrome nodes is a stub."""
    _CHROME = {"Heading", "Row", "Stack", "Card", "Section"}
    out: list[ProofFinding] = []
    for schema_path in schemas_dir.rglob("*.json"):
        try:
            data = json.loads(schema_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict) or "route" not in data:
            continue
        root = data.get("root") or {}
        types = {n.get("type") for n in _walk_nodes(root)}
        content_types = types - _CHROME - {None}
        if not content_types:
            out.append(ProofFinding(
                severity="warning",
                code="empty-page",
                message=f'Page has no data-bearing components (only chrome: {sorted(types - {None})}). '
                        f'Likely a stub — user will see just a heading.',
                file=str(schema_path.relative_to(schemas_dir).as_posix()),
                locator="root",
            ))
    return out


def _check_list_without_repeat(schemas_dir: Path) -> list[ProofFinding]:
    """A page with a list dataSource but no Repeat iterating it → nothing renders."""
    out: list[ProofFinding] = []
    for schema_path in schemas_dir.rglob("*.json"):
        try:
            data = json.loads(schema_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict) or "route" not in data:
            continue
        list_names = {
            ds.get("name") for ds in (data.get("dataSources") or [])
            if isinstance(ds, dict) and ds.get("op") == "list" and isinstance(ds.get("name"), str)
        }
        if not list_names:
            continue
        repeat_binds: set[str] = set()
        for n in _walk_nodes(data.get("root") or {}):
            if n.get("type") in ("Repeat", "List") and isinstance(n.get("bind"), str):
                # binds may be nested (`prices.data`); take first segment.
                repeat_binds.add(n["bind"].split(".")[0])
        missing = list_names - repeat_binds
        for name in sorted(missing):
            out.append(ProofFinding(
                severity="warning",
                code="list-without-repeat",
                message=f'DataSource "{name}" (op:list) has no Repeat/List node iterating it. '
                        f'Fetched rows will not render.',
                file=str(schema_path.relative_to(schemas_dir).as_posix()),
                locator=f'dataSources[name="{name}"]',
            ))
    return out


def _check_repeat_without_source(schemas_dir: Path) -> list[ProofFinding]:
    """A Repeat's bind refers to something that isn't a dataSource → 0 rows."""
    out: list[ProofFinding] = []
    for schema_path in schemas_dir.rglob("*.json"):
        try:
            data = json.loads(schema_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict) or "route" not in data:
            continue
        ds_names = {
            ds.get("name") for ds in (data.get("dataSources") or [])
            if isinstance(ds, dict) and isinstance(ds.get("name"), str)
        }
        for n in _walk_nodes(data.get("root") or {}):
            if n.get("type") not in ("Repeat", "List"):
                continue
            bind = n.get("bind")
            if not isinstance(bind, str) or not bind:
                continue
            root = bind.split(".")[0]
            if root in ds_names:
                continue
            out.append(ProofFinding(
                severity="error",
                code="repeat-without-source",
                message=f'{n.get("type")} node binds to "{bind}" but no dataSource '
                        f'with that name exists. It will iterate an empty array.',
                file=str(schema_path.relative_to(schemas_dir).as_posix()),
                locator=f'{n.get("type")}[bind="{bind}"]',
            ))
    return out


def _check_duplicate_routes(schemas_dir: Path) -> list[ProofFinding]:
    """Two page schemas with the same `route` collide in the registry."""
    out: list[ProofFinding] = []
    routes: dict[str, list[str]] = {}
    for schema_path in schemas_dir.rglob("*.json"):
        try:
            data = json.loads(schema_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        route = data.get("route")
        if isinstance(route, str):
            rel = str(schema_path.relative_to(schemas_dir).as_posix())
            routes.setdefault(route, []).append(rel)
    for route, files in routes.items():
        if len(files) > 1:
            out.append(ProofFinding(
                severity="error",
                code="duplicate-route",
                message=f'{len(files)} page schemas share route "{route}": '
                        f'{files}. Only one will resolve at runtime.',
                file=files[0],
                locator="route",
            ))
    return out


# ---------- public API ----------------------------------------------------

def run_proof_pass(output_dir: str | Path) -> ProofReport:
    """Run all proof checks. Aggregates workflow_validator + contract_validator
    + proof-specific page checks into a single report."""
    base = Path(output_dir)
    findings: list[ProofFinding] = []

    # Cross-module: workflow_validator + contract_validator findings become
    # ProofFindings with the same shape.
    for f in validate_workflows_dir(output_dir):
        findings.append(ProofFinding(
            severity=f.severity,
            code=f.code,
            message=f.message,
            file=f"workflows/{f.workflow_file}",
            locator=f.config_path,
        ))
    for f in validate_contracts_dir(output_dir):
        findings.append(ProofFinding(
            severity=f.severity,
            code=f.code,
            message=f.message,
            file=f"src/schemas/{f.page_file}",
            locator=f.locator,
        ))

    # Proof-specific page checks.
    schemas_dir = base / "src" / "schemas"
    if schemas_dir.is_dir():
        findings.extend(_check_empty_pages(schemas_dir))
        findings.extend(_check_list_without_repeat(schemas_dir))
        findings.extend(_check_repeat_without_source(schemas_dir))
        findings.extend(_check_duplicate_routes(schemas_dir))

    errors = sum(1 for f in findings if f.severity == "error")
    warnings = sum(1 for f in findings if f.severity == "warning")
    return ProofReport(
        passed=(errors == 0),
        error_count=errors,
        warning_count=warnings,
        findings=findings,
    )


def persist_report(report: ProofReport, output_dir: str | Path) -> Path:
    base = Path(output_dir)
    contracts_dir = base / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    path = contracts_dir / "proof_report.json"
    path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return path
