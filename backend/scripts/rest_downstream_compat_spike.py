"""Task-A spike: does the existing REST transformer's tree drop into the
services/figma/ downstream?

No live Figma — this is a pure schema-shape compatibility check. It takes a
Figma REST node document, runs the already-built `figma_to_schema.build_page_schema`
(the REST-JSON -> PageV2 transformer), and feeds the resulting tree through every
services/figma consumer, reporting which accept it unchanged and which need a
REST-tree equivalent. This removes the main risk in the REST-extraction estimate.

Run from backend/:  python3 scripts/rest_downstream_compat_spike.py [fixture.json]
"""
from __future__ import annotations

import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FIXTURE = sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/figma/commitbiz_login.json"


def _root(page: dict) -> dict:
    kids = page.get("children") or []
    if len(kids) == 1 and isinstance(kids[0], dict):
        return kids[0]
    return {"type": "Stack", "props": {}, "children": kids}


def _try(label: str, fn) -> None:
    try:
        out = fn()
        print(f"  [OK]   {label}: {out}")
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] {label}: {type(exc).__name__}: {str(exc)[:160]}")
        if "-v" in sys.argv:
            traceback.print_exc()


def main() -> None:
    from services.figma_to_schema import build_page_schema

    doc = json.load(open(FIXTURE))
    # A /v1/files response wraps the node tree in `document`; build_page_schema
    # wants the node itself.
    if isinstance(doc.get("document"), dict):
        doc = doc["document"]
    page = build_page_schema(doc).page
    root = _root(page)
    print(f"fixture: {FIXTURE}")
    print(f"transformed tree: root type {root.get('type')}, "
          f"{sum(1 for _ in _iter(root))} nodes\n")

    print("TREE-BASED CONSUMERS (expected to work unchanged):")
    from services.figma import chrome as _chrome
    _try("chrome.lone_chrome(root)", lambda: f"{len(_chrome.lone_chrome(root))} chrome fp(s)")
    _try("chrome.chrome_for([root, root])", lambda: f"{len(_chrome.chrome_for([root, root]))} shared fp(s)")
    shared = _chrome.chrome_for([root, root])
    _try("chrome.split(root, shared)", lambda: f"content kept, {len(_chrome.split(root, shared)[1])} removed")
    _try("chrome.rail_as_drawn(chrome nodes)",
         lambda: f"{len(_chrome.rail_as_drawn([root]))} rail entr(y/ies)")

    from services.figma import realize as _realize
    _try("realize.realize(root, [] )",
         lambda: f"{len(_realize.realize(root, [], row_mapper=None)[1])} live source(s) (empty classifications)")

    from services.figma import rows as _rows
    region = next((n for n in _iter(root) if len(n.get("children") or []) >= 2), root)
    _try("rows.row_blocks(a region)", lambda: f"{len(_rows.row_blocks(region))} row block(s)")

    print("\nGEOMETRY CONSUMER (boxes path, REST-ready):")
    from services.figma import regions as _regions
    boxes = _boxes_from_doc(doc)
    w, h = _frame_size(doc)
    _try(f"regions.candidates(code='', boxes={len(boxes)})",
         lambda: f"{len(_regions.candidates('', w, h, boxes=boxes))} candidate region(s)")

    print("\nCODE-STRING CONSUMERS (need a REST-tree equivalent — expected N/A):")
    print("  [N/A]  palette.from_code — regexes the TSX className string; feed the tree/tokens instead")
    print("  [N/A]  regions.regions(code) — code-inset regex; the boxes path above replaces it")
    print("  [N/A]  tables.drawn_tables(code) — walks the code string; needs a tree walker")

    print("\nVERDICT: the [OK] lines are modules that accept the REST transformer's tree as-is.")
    print("Any [FAIL] is a shape mismatch to fix; the three [N/A] are the known rework items.")


def _iter(node):
    if isinstance(node, dict):
        yield node
        for c in node.get("children") or []:
            yield from _iter(c)


def _boxes_from_doc(doc: dict) -> list[dict]:
    out: list[dict] = []

    def walk(n: dict) -> None:
        bb = n.get("absoluteBoundingBox") or n.get("boundingBox")
        if isinstance(bb, dict):
            out.append({"id": n.get("id"), "name": n.get("name"),
                        "x": bb.get("x", 0), "y": bb.get("y", 0),
                        "width": bb.get("width", 0), "height": bb.get("height", 0)})
        for c in n.get("children") or []:
            if isinstance(c, dict):
                walk(c)

    walk(doc)
    return out


def _frame_size(doc: dict) -> tuple[float, float]:
    bb = doc.get("absoluteBoundingBox") or {}
    return float(bb.get("width") or 1440), float(bb.get("height") or 1024)


if __name__ == "__main__":
    main()
