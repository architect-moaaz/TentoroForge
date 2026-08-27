"""Validate emitted page schemas against the component contracts.

Why this exists
---------------
The renderer enforces a contract at runtime: unknown node types render a
"⚠ Unknown component" placeholder, invalid props render an invalid-props
box, an unbound Table renders empty forever, a bare Select is a dead
dropdown. Today those failures surface in front of the user; nothing at
generation time checks pages against the SAME contract the renderer
enforces. This validator closes that seam — it reads the exact contract
source (packages/registry/dist/component-contracts.json, extracted from
the library's zod propsSchemas) plus the renderer's built-in node set,
and judges every emitted page.

It is a GATE CHECK, not a guard: it repairs nothing. Findings are either
surfaced (warn) or fail the build (strict), so upstream producers get
fixed instead of a reconciliation pass accumulating.

Checks
------
- ``unknown_type``           node type not in contracts nor a renderer built-in
- ``missing_required_prop``  contract-required prop absent from node.props
- ``unbound_table``          Table with none of rows/data/dataSource
- ``bare_select``            Select with empty/absent options and no optionsFrom
- ``bound_iframe``           CustomBlock html embedding a bound iframe
                             (the recursive app-in-preview class)

Gate wiring (post_generate_fixes quality tail) honors
``FORGE_PAGE_CONTRACT_GATE``: ``off`` | ``warn`` (default) | ``strict``.
Report artifact: ``contracts/page-contract.json``.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Must mirror packages/renderer/src/runtime/dispatch.tsx switch arms —
# valid ``type`` values that never appear in component-contracts.json.
RENDERER_BUILTINS = frozenset({
    "Box", "Text", "Image", "Icon",
    "Stack", "Row", "Grid", "Container", "Spacer",
    "Repeat", "Conditional", "DataBoundary",
    "Slot", "PageOutlet", "Custom",
})

_CONTRACTS_PATH = (
    Path(__file__).resolve().parents[2]
    / "packages" / "registry" / "dist" / "component-contracts.json"
)

_TABLE_BINDING_PROPS = ("rows", "data", "dataSource")

_BOUND_IFRAME_RE = re.compile(
    r"<iframe[^>]*\bsrc=[\"']\{\{[^\"'}]+\}\}[\"']", re.IGNORECASE)

# Schemas that aren't user pages (the shell frame has its own authority).
_SKIP_FILES = frozenset({"shell.json"})


def load_contracts() -> dict[str, dict] | None:
    try:
        doc = json.loads(_CONTRACTS_PATH.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[page-contract] contracts unavailable: %s", exc)
        return None


def _required_props(contract: dict) -> list[str]:
    return [p for p, spec in contract.items()
            if isinstance(spec, dict) and not spec.get("optional")
            and p != "children"]


def _check_node(node: dict, page: str, contracts: dict,
                issues: list[dict]) -> None:
    ctype = node.get("type")
    props = node.get("props") if isinstance(node.get("props"), dict) else {}
    if not isinstance(ctype, str):
        return

    def add(code: str, msg: str, **extra: Any) -> None:
        issues.append({"code": code, "page": page, "component": ctype,
                       "node_id": node.get("id"), "message": msg, **extra})

    contract = contracts.get(ctype)
    if contract is None:
        if ctype not in RENDERER_BUILTINS:
            add("unknown_type",
                f"'{ctype}' is not in the component registry — the "
                "renderer will show an Unknown-component placeholder")
        return

    for prop in _required_props(contract):
        if prop not in props:
            add("missing_required_prop",
                f"'{ctype}' requires prop '{prop}' — the renderer will "
                "reject the node as invalid props", prop=prop)

    if ctype == "Table":
        if not any(props.get(p) for p in _TABLE_BINDING_PROPS):
            add("unbound_table",
                "Table has no rows/data/dataSource binding — it will "
                "render empty forever")

    if ctype == "Select":
        opts = props.get("options")
        has_opts = isinstance(opts, list) and len(opts) > 0
        if not has_opts and not props.get("optionsFrom"):
            add("bare_select",
                "Select has no options and no optionsFrom — dead dropdown")

    if ctype == "CustomBlock":
        html = props.get("html")
        if isinstance(html, str) and _BOUND_IFRAME_RE.search(html):
            add("bound_iframe",
                "CustomBlock embeds a bound iframe — non-PDF/HTML file "
                "URLs recurse the app inside itself (file_preview class)")


def _walk(node: Any, page: str, contracts: dict, issues: list[dict]) -> None:
    if not isinstance(node, dict):
        return
    _check_node(node, page, contracts, issues)
    kids = node.get("children")
    if isinstance(kids, list):
        for child in kids:
            _walk(child, page, contracts, issues)


def validate_schema_dict(doc: Any, page_name: str,
                         contracts: dict[str, dict]) -> list[dict]:
    """Validate ONE page-schema document. Returns its issue list.

    This is the producer-side entry point: the page agent calls it on
    the LLM's output BEFORE writing, so violations can be fed back for
    a revise turn instead of shipping and being caught post-hoc.
    """
    issues: list[dict] = []
    if isinstance(doc, dict):
        _walk(doc.get("root"), page_name, contracts, issues)
    return issues


def format_issues_for_revise(issues: list[dict]) -> str:
    """Render violations as a REVISE block for the authoring agent."""
    lines = ["Your page schema violates the component contract. "
             "Fix EVERY issue below and re-emit the full schema:"]
    for i in issues:
        where = f"{i.get('component')}" + (
            f" (id={i['node_id']})" if i.get("node_id") else "")
        lines.append(f"- [{i['code']}] {where}: {i['message']}")
    return "\n".join(lines)


def validate_pages(output_dir: str | Path, *,
                   contracts: dict[str, dict] | None = None) -> dict:
    """Validate every ``src/schemas/*.json`` page. Never raises.

    Returns ``{"issues": [...], "summary": {pages, errors, skipped}}``.
    All findings are errors (each one is a user-visible runtime defect);
    the warn/strict distinction is the CALLER's gate policy, not a
    per-issue severity.
    """
    root = Path(output_dir)
    report: dict[str, Any] = {
        "issues": [], "summary": {"pages": 0, "errors": 0, "skipped": False}}

    if contracts is None:
        contracts = load_contracts()
        if contracts is None:
            report["summary"]["skipped"] = True
            return report

    schemas = root / "src" / "schemas"
    if not schemas.is_dir():
        return report

    issues: list[dict] = []
    for path in sorted(schemas.glob("*.json")):
        if path.name in _SKIP_FILES:
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            issues.append({"code": "unparseable_schema", "page": path.name,
                           "component": None, "node_id": None,
                           "message": f"schema is not valid JSON: {exc}"})
            report["summary"]["pages"] += 1
            continue
        report["summary"]["pages"] += 1
        issues.extend(validate_schema_dict(doc, path.name, contracts))

    report["issues"] = issues
    report["summary"]["errors"] = len(issues)
    return report
