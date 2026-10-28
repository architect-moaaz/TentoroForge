"""The drawn pieces the app needs beyond its pages: the shell and the pictures.

The pages carry their drawn views as parts (`binder`). What every page shares
is written here: the icons and pictures Figma rendered (`assets.copy_into`),
and the drawn shell — the converted sidebar and top bar, as
`src/components/drawn/DrawnShell.tsx`, with the wrapper the app's layout
renders it through (`src/components/DrawnShell.tsx`). The wrapper is the
binding of the shell: the menu entries the drawing shows, each led to the page
its prototype link reaches, the one you are on lit, and the application's own
notifications and account menu where the drawing puts its bell.

Without a drawn shell the wrapper is the template's: it says `DRAWN_SHELL =
false`, and the layout draws its own frame as before.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

WRAPPER = Path("src/components/DrawnShell.tsx")
DRAWN_DIR = Path("src/components/drawn")

DEFAULT_WRAPPER = '''"use client";
// The design draws no frame of its own: the application draws its own.
import * as React from "react";

export const DRAWN_SHELL = false;

export default function DrawnShell(props: { children?: React.ReactNode; controls?: React.ReactNode }) {
  return <>{props.children}</>;
}
'''


def _shell(doc: dict) -> dict | None:
    return next((v for v in doc.get("drawnViews") or [] if isinstance(v, dict) and v.get("kind") == "shell"
                 and v.get("status") != "DEPRECATED"), None)


def nav_routes(doc: dict, shell: dict) -> list[dict]:
    """The drawn menu, each entry with the route of the page it leads to: by
    the prototype's own link from that entry, else the page whose name it is."""
    from services.blueprint.page_planner import page_frames

    by_frame: dict[str, str] = {}
    for page in doc.get("pages") or []:
        if isinstance(page, dict) and page.get("status") != "DEPRECATED" and page.get("route"):
            for f in page_frames(page):
                by_frame.setdefault(f, str(page["route"]))
    links: dict[str, str] = {}
    frame = str(shell.get("frame") or "")
    for source in doc.get("designSources") or []:
        for f in source.get("frames") or []:
            if str(f.get("nodeId")) == frame.split("/")[-1]:
                for link in f.get("links") or []:
                    if link.get("via") and link.get("to"):
                        links.setdefault(str(link["via"]).strip().lower(), str(link["to"]))
    by_name = {str(p.get("name") or "").strip().lower(): str(p.get("route")) for p in doc.get("pages") or []
               if isinstance(p, dict) and p.get("route")}
    out = []
    for row in (shell.get("sample") or {}).get("nav") or []:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "")
        target = links.get(label.strip().lower())
        href = by_frame.get(target or "", "") or by_name.get(label.strip().lower(), "") or str(row.get("href") or "")
        out.append({**{k: v for k, v in row.items() if k not in ("id", "active")}, "href": href or "#"})
    return out


def _wrapper(shell: dict, nav: list[dict]) -> str:
    from services.drawn.contract import change_handler

    contract = shell.get("contract") or {}
    handlers = []
    for action in contract.get("actions") or []:
        name = str(action.get("name") or "")
        if not name:
            continue
        if str(action.get("on") or "") == "nav":
            handlers.append(f"{name}={{(row) => router.push(row.href)}}")
        else:
            handlers.append(f"{name}={{() => {{}}}}")
    forms = []
    for slot in contract.get("data") or []:
        if slot.get("kind") == "form":
            fields = {str(f.get("name")): "" for f in slot.get("fields") or [] if f.get("name")}
            forms.append(f"{slot['name']}={{{json.dumps(fields)}}} {change_handler(slot['name'])}={{() => {{}}}}")
    others = [s for s in contract.get("data") or [] if s.get("kind") not in ("form",) and s.get("name") != "nav"]
    sample = shell.get("sample") or {}
    rest = " ".join(f"{s['name']}={{{json.dumps(sample.get(s['name']))}}}" for s in others
                    if sample.get(s["name"]) is not None)
    return (
        '"use client";\n'
        "// The design's own frame, bound: its menu led to the pages, the page you are on lit.\n"
        'import * as React from "react";\n'
        'import { usePathname, useRouter } from "next/navigation";\n'
        'import ShellView from "./drawn/DrawnShell";\n\n'
        "export const DRAWN_SHELL = true;\n\n"
        f"const NAV = {json.dumps(nav, indent=2, ensure_ascii=False)};\n\n"
        "export default function DrawnShell(props: { children?: React.ReactNode; controls?: React.ReactNode }) {\n"
        "  const path = usePathname() || \"/\";\n"
        "  const router = useRouter();\n"
        "  const best = NAV.map((n) => n.href).filter((h) => h !== \"#\" && (path === h || path.startsWith(h + \"/\")))\n"
        "    .sort((a, b) => b.length - a.length)[0];\n"
        "  const nav = NAV.map((n, i) => ({ ...n, id: String(i), active: n.href === best }));\n"
        "  return (\n"
        f"    <ShellView nav={{nav as any}} controls={{props.controls}} {' '.join(handlers)} {' '.join(forms)} {rest}>\n"
        "      {props.children}\n"
        "    </ShellView>\n"
        "  );\n"
        "}\n"
    )


def project_drawn(doc: dict, output_dir: str | Path, app_root: str | Path) -> dict[str, Any]:
    """Write the drawn shell and copy the drawn pictures. Idempotent."""
    from services.drawn.assets import copy_into

    root = Path(app_root)
    copied = copy_into(output_dir, root)
    shell = _shell(doc)
    wrapper = root / WRAPPER
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    if shell is None:
        if not wrapper.is_file() or "DRAWN_SHELL = true" in wrapper.read_text("utf-8"):
            wrapper.write_text(DEFAULT_WRAPPER, encoding="utf-8")
        return {"assets": copied, "shell": False}
    drawn = root / DRAWN_DIR
    drawn.mkdir(parents=True, exist_ok=True)
    (drawn / "DrawnShell.tsx").write_text(str(shell["code"]), encoding="utf-8")
    components = {str(v.get("name")): str(v.get("code")) for v in doc.get("drawnViews") or []
                  if isinstance(v, dict) and v.get("kind") == "component"}
    for name, code in components.items():
        if re.search(r'from "\./' + re.escape(name) + r'"', str(shell["code"])):
            (drawn / f"{name}.tsx").write_text(code, encoding="utf-8")
    nav = nav_routes(doc, shell)
    wrapper.write_text(_wrapper(shell, nav), encoding="utf-8")
    return {"assets": copied, "shell": True, "nav": len(nav)}
