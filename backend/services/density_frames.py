"""Density-aware page frames (G5 / item 4).

Every generated page currently renders in the same wide content frame.
That's right for dashboards and tables, and visibly wrong for a page
whose entire content is one form — the "form lost in space" look the
reference-app audit called out: a 480px-worth of fields stretched
across a 1400px canvas.

This pass derives ONE decision per page from the schema's actual
composition — ``density: sparse | regular | dense`` — and gives sparse
pages a centered narrow column (max-w-2xl). Everything else keeps the
wide frame. The decision is also stamped on the page doc as
``"density"`` so future composers/emitters can consume it directly
instead of re-deriving.

Classification (structural, no LLM):
  - ``sparse``  — no wide widget (Table/Chart/Kanban/…) anywhere, and
    the page's substance is a single interaction surface: a Form, or a
    couple of light content nodes. Create/edit/login pages land here.
  - ``dense``   — 2+ wide widgets or 8+ substantial nodes (dashboards,
    split views).
  - ``regular`` — everything else.

Application is a className append on the page root (validateProps
preserves className universally), marker-guarded for idempotency.
Redirect aliases and pages whose root already constrains width are
skipped. Runs in post_generate_fixes after route dedup, before the
materializer.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from services.delivery_gate import _node_type, _walk

logger = logging.getLogger(__name__)

# Nodes that need horizontal room — one of these anywhere means the
# page is not sparse.
_WIDE_TYPES = {
    "Table", "Chart", "Kanban", "Calendar", "CardGrid", "Heatmap",
    "Schematic", "ResourceTimeline", "Gantt", "DataGrid", "Board",
}
# Pure structure/chrome — never counts toward substance.
_LAYOUT_TYPES = {
    "Stack", "Section", "Grid", "Row", "Cluster", "Column", "Container",
    "Box", "Page", "Spacer", "Divider", "Slot", "Card",
}

_SPARSE_CLASS = "mx-auto w-full max-w-2xl"


def classify_density(page: dict) -> str:
    """sparse | regular | dense, from composition alone."""
    types = [_node_type(n) for n in _walk(page)
             if isinstance(n, dict) and _node_type(n)]
    if "Redirect" in types:
        return "regular"  # aliases render for milliseconds — leave alone
    wide = sum(1 for t in types if t in _WIDE_TYPES)
    substantial = [t for t in types if t not in _LAYOUT_TYPES and t]
    if wide >= 2 or len(substantial) >= 8:
        return "dense"
    if wide == 0 and ("Form" in types or len(substantial) <= 2):
        return "sparse"
    return "regular"


def _apply_sparse_frame(doc: dict) -> bool:
    """Center-constrain the page root. Returns True if changed."""
    root = doc.get("root")
    if not isinstance(root, dict):
        return False
    props = root.setdefault("props", {})
    if not isinstance(props, dict):
        return False
    existing = props.get("className")
    existing = existing if isinstance(existing, str) else ""
    if "max-w-" in existing:
        return False  # a width constraint already exists — authored or ours
    props["className"] = (existing + " " + _SPARSE_CLASS).strip()
    return True


def apply_density_frames(output_dir: str | Path) -> dict:
    """Classify every page, stamp ``density``, frame the sparse ones."""
    root = Path(output_dir)
    counts = {"sparse": 0, "regular": 0, "dense": 0}
    framed: list[str] = []
    sdir = root / "src" / "schemas"
    if not sdir.is_dir():
        return {"counts": counts, "framed": framed}
    for p in sorted(sdir.rglob("*.json")):
        if p.name in ("shell.json", "registry.ts"):
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(doc, dict) or not isinstance(doc.get("root"), dict):
            continue
        density = classify_density(doc)
        counts[density] += 1
        changed = doc.get("density") != density
        doc["density"] = density
        if density == "sparse" and _apply_sparse_frame(doc):
            changed = True
            framed.append(str(p.relative_to(sdir)))
        if changed:
            try:
                p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                logger.warning("[density] could not write %s: %s", p, exc)
    if framed:
        logger.info("[density] centered narrow frame on %d sparse page(s): %s",
                    len(framed), ", ".join(framed[:6]))
    return {"counts": counts, "framed": framed}


__all__ = ["apply_density_frames", "classify_density"]
