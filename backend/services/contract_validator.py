"""Page-schema contract validator — Phase 3's page-side complement to
workflow_validator.py.

Reads the persisted Manifest (Phase 0's scope_card) as authority for what
pages are allowed to exist, then sweeps every generated page schema for
three page-level contract violations:

- **Route contract**: a page schema whose `route` isn't declared in the
  manifest shouldn't have been authored. Symptom: the 27 phantom pages
  in nni3wjf6 (visitors, admins, scan-2/3/4, etc.).
- **Action contract**: every Button `navigate` / `workflow` / `href` /
  `to` must target a route or workflow that exists.
- **Binding contract**: every `{{name.path}}` must reference a dataSource
  declared on the page (dataSources[].name), a `bind` binding scope, or
  a well-known root (`user`, `item`, `row`, `scope`).

Findings are the same Finding dataclass as workflow_validator (so callers
can concat both lists and drive a single UI chip).
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from services.scope_card import Manifest, load_manifest


Severity = Literal["error", "warning"]


@dataclass
class Finding:
    severity: Severity
    code: str
    message: str
    page_file: str
    node_type: str | None = None
    locator: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


_REF_RE = re.compile(r"\{\{([^{}]+?)\}\}")
_WELL_KNOWN_SCOPES = {"user", "item", "row", "scope", "index", "i"}


def _ref_root(ref: str) -> str:
    m = re.match(r"[A-Za-z_][A-Za-z0-9_]*", ref.strip())
    return m.group(0) if m else ""


def _walk_nodes(node: dict):
    """Yield every node in a page schema tree depth-first."""
    if not isinstance(node, dict):
        return
    yield node
    for child in node.get("children") or []:
        yield from _walk_nodes(child)


def _walk_strings(obj, path: str = ""):
    if isinstance(obj, str):
        yield (path or "$", obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_strings(v, f"{path}[{i}]")


# ---------- validators ----------------------------------------------------

def _validate_route(schema: dict, page_file: str, manifest: Manifest) -> list[Finding]:
    """The page's route must be in the manifest."""
    route = schema.get("route")
    if not isinstance(route, str):
        return []
    declared = {p.path for p in manifest.pages}
    if route not in declared:
        return [Finding(
            severity="error",
            code="route-not-in-manifest",
            message=f'Page route "{route}" is not declared in the manifest. '
                    f'Either add it to the manifest during scope-card '
                    f'confirmation or remove the page. Declared routes: '
                    f'{sorted(declared)}',
            page_file=page_file,
            locator="route",
        )]
    return []


def _validate_actions(schema: dict, page_file: str, manifest: Manifest) -> list[Finding]:
    """Every Button navigate/workflow/href must target something real."""
    out: list[Finding] = []
    manifest_routes = {p.path for p in manifest.pages}
    manifest_workflows = {w for w in manifest.workflows}
    # Also accept the runtime-primitive workflow names (auth, cart) since
    # those aren't in the manifest but do exist at runtime.
    runtime_workflows = {"Login", "Register", "Logout", "Checkout"}
    for node in _walk_nodes(schema.get("root") or {}):
        props = node.get("props") or {}
        # navigate to a route.
        nav = props.get("navigate") or props.get("to")
        if isinstance(nav, str) and nav.startswith("/"):
            # Normalize dynamic segments in the URL to their manifest form.
            # e.g. /scans/abc123 → /scans/[id] for lookup.
            normalized = _normalize_route(nav)
            if normalized not in manifest_routes and nav not in manifest_routes:
                out.append(Finding(
                    severity="error",
                    code="orphan-navigate",
                    message=f'Button navigate="{nav}" targets a page not in the manifest.',
                    page_file=page_file,
                    node_type=node.get("type"),
                    locator=f"props.navigate={nav}",
                ))
        # workflow name.
        wf = props.get("workflow")
        if isinstance(wf, str) and wf:
            if wf not in manifest_workflows and wf not in runtime_workflows:
                out.append(Finding(
                    severity="warning",  # planner may add custom workflows
                    code="orphan-workflow",
                    message=f'Button workflow="{wf}" is not in the manifest. '
                            f'If this is a custom workflow the planner authored, '
                            f'ensure it exists in workflows/.',
                    page_file=page_file,
                    node_type=node.get("type"),
                    locator=f"props.workflow={wf}",
                ))
    return out


def _normalize_route(url: str) -> str:
    """Replace UUIDs / numeric ids in URL segments with [id] so we can look
    up dynamic routes in the manifest. /scans/abc-def-123/prices → /scans/[id]/prices."""
    parts = url.strip("/").split("/")
    UUID_RE = re.compile(r"^[0-9a-fA-F]{8}(?:-?[0-9a-fA-F]{4}){3}-?[0-9a-fA-F]{12}$")
    for i, part in enumerate(parts):
        if UUID_RE.match(part) or part.isdigit():
            parts[i] = "[id]"
    return "/" + "/".join(parts)


def _validate_bindings(schema: dict, page_file: str) -> list[Finding]:
    """Every {{root.rest}} must reference a declared dataSource or a
    well-known scope (user/item/row/…)."""
    ds_names = {ds.get("name") for ds in (schema.get("dataSources") or []) if isinstance(ds, dict)}
    ds_names = {n for n in ds_names if isinstance(n, str)}
    out: list[Finding] = []
    for node in _walk_nodes(schema.get("root") or {}):
        # Nodes may declare `as` to introduce a scope (Repeat).
        local_scope = node.get("as")
        for path, val in _walk_strings({"props": node.get("props") or {}}):
            for m in _REF_RE.finditer(val):
                root = _ref_root(m.group(1))
                if not root:
                    continue
                if root in ds_names:
                    continue
                if root in _WELL_KNOWN_SCOPES:
                    continue
                if isinstance(local_scope, str) and root == local_scope:
                    continue
                out.append(Finding(
                    severity="warning",
                    code="orphan-binding",
                    message=f'{{{{{m.group(1).strip()}}}}} references "{root}" '
                            f'which is not a declared dataSource or well-known scope. '
                            f'Add a dataSource[name="{root}"] or fix the ref.',
                    page_file=page_file,
                    node_type=node.get("type"),
                    locator=path,
                ))
    return out


# ---------- public API ----------------------------------------------------

def validate_page_schema(schema: dict, page_file: str, manifest: Manifest) -> list[Finding]:
    out: list[Finding] = []
    out.extend(_validate_route(schema, page_file, manifest))
    out.extend(_validate_actions(schema, page_file, manifest))
    out.extend(_validate_bindings(schema, page_file))
    return out


def validate_output_dir(output_dir: str | Path) -> list[Finding]:
    """Sweep every page schema under `<output_dir>/src/schemas/`. Returns
    empty when no manifest is present (soft-fail — legacy pipeline path)."""
    base = Path(output_dir)
    manifest = load_manifest(output_dir)
    if manifest is None:
        return []
    schemas_dir = base / "src" / "schemas"
    if not schemas_dir.is_dir():
        return []
    findings: list[Finding] = []
    for schema_path in sorted(schemas_dir.rglob("*.json")):
        # Skip non-page files (registry.ts uses .ts; only JSON page schemas here).
        try:
            data = json.loads(schema_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict) or "route" not in data:
            continue
        rel = schema_path.relative_to(schemas_dir).as_posix()
        findings.extend(validate_page_schema(data, rel, manifest))
    return findings


def persist_report(findings: list[Finding], output_dir: str | Path) -> Path:
    base = Path(output_dir)
    contracts_dir = base / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    path = contracts_dir / "contract_validation.json"
    path.write_text(json.dumps([f.to_dict() for f in findings], indent=2), encoding="utf-8")
    return path
