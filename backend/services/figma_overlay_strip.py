"""Strip the `_figmaDerived` full-bleed escape from pages that live in the shell.

`_figmaDerived: true` makes schema-page.tsx render the page inside a
`fixed inset-0 z-[60]` layer so a Figma-authored full-viewport design isn't
wrapped in dashboard chrome. That is correct ONLY for standalone pages.
When the flag survives onto a page the shell actually navigates to (it's in
the sidebar/topbar menu), the overlay paints ABOVE the shell header
(z-50) and every chrome control under it — the dxlc5m31 "hamburger won't
click" bug.

Rule: a page reachable from the shell menu is by definition an in-shell
page, so it must never carry the escape flag. Standalone Figma pages
(login, landing, one-off flows outside the menu) keep it.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _shell_menu_routes(output_dir: str) -> set[str]:
    """Every route the shell chrome links to (NavLink/navigate strings)."""
    shell_path = Path(output_dir) / "src" / "schemas" / "shell.json"
    routes: set[str] = set()
    if not shell_path.is_file():
        return routes
    try:
        shell = json.loads(shell_path.read_text(encoding="utf-8"))
    except Exception:
        return routes

    def walk(node) -> None:
        if isinstance(node, dict):
            for key in ("navigate", "href", "route"):
                v = node.get(key) or (node.get("props") or {}).get(key) \
                    if isinstance(node.get("props"), dict) else node.get(key)
                if isinstance(v, str) and v.startswith("/"):
                    routes.add(v.rstrip("/") or "/")
            props = node.get("props")
            if isinstance(props, dict):
                for key in ("navigate", "href", "route"):
                    v = props.get(key)
                    if isinstance(v, str) and v.startswith("/"):
                        routes.add(v.rstrip("/") or "/")
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(shell)
    return routes


def strip_figma_overlay(output_dir: str) -> dict:
    """Remove `_figmaDerived` from every schema whose route the shell menu
    links to. Returns {"stripped": n, "files": [...]}. Idempotent."""
    schemas_dir = Path(output_dir) / "src" / "schemas"
    if not schemas_dir.is_dir():
        return {"stripped": 0, "files": []}
    menu_routes = _shell_menu_routes(output_dir)
    if not menu_routes:
        return {"stripped": 0, "files": []}

    stripped: list[str] = []
    for path in sorted(schemas_dir.rglob("*.json")):
        if path.name == "shell.json":
            continue
        try:
            page = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(page, dict) or not page.get("_figmaDerived"):
            continue
        route = page.get("route")
        if not isinstance(route, str):
            # Derive from the file path: src/schemas/foo/bar.json → /foo/bar,
            # home.json / index.json → /.
            rel = path.relative_to(schemas_dir).with_suffix("")
            parts = [p for p in rel.parts if p not in ("home", "index")]
            route = "/" + "/".join(parts)
        route = route.rstrip("/") or "/"
        if route not in menu_routes:
            continue
        page.pop("_figmaDerived", None)
        path.write_text(json.dumps(page, indent=2) + "\n", encoding="utf-8")
        stripped.append(str(path.relative_to(output_dir)))

    return {"stripped": len(stripped), "files": stripped}
