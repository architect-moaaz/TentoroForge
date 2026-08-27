"""File-preview guard — no recursive-app iframes in document previews.

LLM-authored detail pages sometimes render a file preview as a raw
``CustomBlock`` iframe: ``<iframe src="{{document.filePath}}">``. When
the bound value is empty or not a servable file (seeded rows, missing
uploads), the iframe resolves to an app route and Next renders the app
INSIDE its own detail page (atb0m97x "Document Intelligence under the
doc preview").

The frozen doc-intel reference app carries the proven pattern:

* serve through the ``/api/files/preview?src=...`` route (ships with
  every app that has file storage),
* embed with ``<object type="application/pdf">`` — unlike an iframe, an
  object shows its INLINE FALLBACK content when the target isn't a real
  PDF, so a bogus path degrades to "preview unavailable" instead of a
  recursive app render,
* offer an "Open PDF ↗" escape hatch in a new tab.

This guard rewrites any CustomBlock whose html embeds an ``<iframe>``
with a Mustache-bound src into that pattern, preserving the original
binding. Additive + idempotent; report at contracts/file-preview.json.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from services.artifact_authority import should_assert_only_any
from typing import Any

logger = logging.getLogger(__name__)

_IFRAME_RE = re.compile(
    r"<iframe[^>]*\bsrc=[\"'](\{\{[^\"'}]+\}\})[\"'][^>]*>\s*</iframe>",
    re.IGNORECASE,
)

_PREVIEW_ROUTE = "/api/files/preview"


def _preview_html(binding: str, *, via_route: bool) -> str:
    src = f"{_PREVIEW_ROUTE}?src={binding}" if via_route else binding
    return (
        '<div style="display:flex;flex-direction:column;gap:8px;">'
        f'<a href="{src}" target="_blank" rel="noopener" '
        'style="align-self:flex-end;padding:6px 12px;background:#0f172a;'
        "color:#fff;text-decoration:none;border-radius:4px;"
        'font:500 13px system-ui;">Open PDF ↗</a>'
        f'<object data="{src}" type="application/pdf" '
        'style="width:100%;height:640px;border:1px solid #E5E5E5;'
        'border-radius:4px;display:block;background:#f5f5f5;">'
        '<div style="padding:24px;text-align:center;color:#666;'
        'font:14px system-ui;">Inline preview unavailable — use the '
        "Open PDF button above.</div></object></div>"
    )


def _has_preview_route(root: Path) -> bool:
    return (root / "src" / "app" / "api" / "files" / "preview").is_dir()


def apply_file_preview_guard(output_dir: str | Path) -> dict:
    """Rewrite raw bound-iframe CustomBlocks to the safe object pattern."""
    root = Path(output_dir)
    schemas_dir = root / "src" / "schemas"
    report: dict[str, Any] = {"rewritten": [], "asserts_logged": 0,
                              "summary": {"rewritten": 0}}
    if not schemas_dir.is_dir():
        return report

    via_route = _has_preview_route(root)

    for path in sorted(schemas_dir.rglob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(doc, dict):
            continue
        # Composer-authored pages are ASSERT-only: the composer's decision is the
    # authority, so log drift instead of rewriting it.
        if should_assert_only_any(doc):
            report["asserts_logged"] += 1
            continue
        rel = str(path.relative_to(schemas_dir))
        dirty = False

        def walk(node: Any) -> None:
            nonlocal dirty
            if isinstance(node, dict):
                props = node.get("props")
                if (node.get("type") == "CustomBlock"
                        and isinstance(props, dict)
                        and isinstance(props.get("html"), str)):
                    m = _IFRAME_RE.search(props["html"])
                    if m:
                        binding = m.group(1)
                        props["html"] = _preview_html(binding,
                                                      via_route=via_route)
                        dirty = True
                        report["rewritten"].append(
                            {"page": rel, "binding": binding,
                             "via_route": via_route})
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(doc)
        if dirty:
            path.write_text(json.dumps(doc, indent=2) + "\n",
                            encoding="utf-8")

    report["summary"]["rewritten"] = len(report["rewritten"])
    contracts = root / "contracts"
    try:
        contracts.mkdir(parents=True, exist_ok=True)
        (contracts / "file-preview.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        logger.warning("file-preview guard: report write failed: %s", e)
    return report
