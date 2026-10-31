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

WHO IS SIGNED IN is the shell's own read (`DrawnView.load`, written beside it
as `<Shell>.load.ts`): the layout runs every shell's read on the server
(`DrawnShellLoad.ts`) and the frame shows what it returned for a slot — the
person's card, their organisation — and the drawing's sample for any slot it
left out.

A DESIGN OF SEVERAL PRODUCTS HAS A FRAME FOR EACH (`convert.portals`): the
candidate's, the recruiter's, the administrator's. The wrapper draws the one
the page you are on was drawn in; a page no portal drew (signing in, a page
the design left out) gets the frame of the portal the signed-in role's pages
are drawn in. On a phone, a page drawn for the phone too is shown bare: the
phone drawing is the whole screen, and a desktop sidebar around it is not.

EVERY FRAME IS SHOWN IN `DrawnFrame` (a platform file, written with the shell):
below 1024px the drawn sidebar is a drawer behind a menu button and the page
gives way by its auto-layout classes (`DrawnFrame.css`); and the drawn words
are shown in the language the person chose, from `product.words` (`words`).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

WRAPPER = Path("src/components/DrawnShell.tsx")
SHELL_LOAD = Path("src/components/DrawnShellLoad.ts")
DRAWN_DIR = Path("src/components/drawn")
#: The drawer and the narrow-screen rules every drawn frame is shown in, and
#: the words in the chosen language (`DrawnFrame.tsx`). Platform files: written
#: with the shell, so an app built before them has them too.
FRAME_FILES = (Path("src/components/DrawnFrame.tsx"), Path("src/components/DrawnFrame.css"))
_FOUNDATION = Path(__file__).resolve().parents[2] / "templates" / "app-foundation"

DEFAULT_WRAPPER = '''"use client";
// The design draws no frame of its own: the application draws its own.
import * as React from "react";

export const DRAWN_SHELL = false;

export default function DrawnShell(props: { children?: React.ReactNode; controls?: React.ReactNode; role?: string;
                                           data?: Record<string, Record<string, unknown>> }) {
  return <>{props.children}</>;
}
'''

# WHAT THE SHELLS SHOW OF THE SIGNED-IN PERSON, read on the server by the
# layout and handed to the wrapper: `{shell key: {slot: value}}`.
DEFAULT_SHELL_LOAD = '''// No drawn shell reads anything: each shows its drawing as drawn.
export async function loadShell(): Promise<Record<string, Record<string, unknown>>> {
  return {};
}
'''


def _shells(doc: dict) -> list[dict]:
    return [v for v in doc.get("drawnViews") or [] if isinstance(v, dict) and v.get("kind") == "shell"
            and v.get("status") != "DEPRECATED" and v.get("code")]


def _shell(doc: dict) -> dict | None:
    shells = _shells(doc)
    return shells[0] if shells else None


def _live_pages(doc: dict) -> list[dict]:
    return [p for p in doc.get("pages") or [] if isinstance(p, dict) and p.get("status") != "DEPRECATED"
            and p.get("route")]


def portal_routes(doc: dict, shells: list[dict]) -> list[list[str]]:
    """``[[route, shell key]]`` — the frame each drawn page was drawn in."""
    from services.drawn.convert import _spec_frames
    from services.figma.store import frame_ref

    by_portal = {str(s.get("portal") or ""): str(s["key"]) for s in shells}
    portal_of = {frame_ref(str(src.get("id") or ""), str(f["nodeId"])): str(f.get("portal") or "")
                 for src, f in _spec_frames(doc)}
    out = []
    for page in _live_pages(doc):
        key = by_portal.get(portal_of.get(str(page.get("figmaFrame") or ""), ""))
        if key:
            out.append([str(page["route"]), key])
    return out


def role_portals(doc: dict, routes: list[list[str]]) -> dict[str, str]:
    """``{role name: shell key}`` — the frame a role's pages are drawn in, so
    a page no portal drew is framed as that person's other pages are."""
    from collections import Counter

    names = {str(r.get("id")): str(r.get("name") or "") for r in doc.get("roles") or []
             if isinstance(r, dict) and r.get("id")}
    key_of = dict((route, key) for route, key in routes)
    counts: dict[str, Counter] = {}
    for page in _live_pages(doc):
        key = key_of.get(str(page["route"]))
        if not key:
            continue
        for user in page.get("users") or []:
            name = names.get(str(user), str(user))
            if name:
                counts.setdefault(name, Counter())[key] += 1
    return {name: c.most_common(1)[0][0] for name, c in counts.items()}


def phone_routes(doc: dict) -> list[str]:
    """The pages drawn for the phone: too (`drawn.pairs`), or only — a push
    notification drawn at phone size is the whole phone screen as well."""
    from services.blueprint.page_planner import page_frames
    from services.drawn.convert import _spec_frames
    from services.drawn.pairs import PHONE_MAX, phone_of
    from services.figma.store import frame_ref

    twins = set(phone_of(doc))
    narrow = {frame_ref(str(s.get("id") or ""), str(f["nodeId"])) for s, f in _spec_frames(doc)
              if 0 < float(f.get("width") or 0) < PHONE_MAX}
    return sorted({str(p["route"]) for p in _live_pages(doc)
                   if page_frames(p) & twins or str(p.get("figmaFrame") or "") in narrow})


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
    # A NAME IS MATCHED AMONG THIS FRAME'S OWN PAGES. Matched across the app,
    # the agency's, the enterprise's and the recruiter's "Home" and "Messages"
    # all opened the candidate's (wzml1sa6, 2026-10-30).
    own = {route for route, _key in portal_routes(doc, [shell])}
    by_name = {str(p.get("name") or "").strip().lower(): str(p.get("route")) for p in _live_pages(doc)
               if not own or str(p.get("route")) in own}
    live = {str(p["route"]) for p in _live_pages(doc)}
    # WHO MAY OPEN IT, as the app's own menu says: DITANS Operations was shown
    # Taxonomy, Identity and Moderation, whose pages are other staff roles', and
    # each sent it away (wzml1sa6, 2026-10-30).
    from services.blueprint.projection import restricted_roles
    roles_of = {str(p["route"]): restricted_roles(doc, p) for p in _live_pages(doc)
                if str(p.get("access") or "") == "role_restricted"}
    out = []
    for row in (shell.get("sample") or {}).get("nav") or []:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "")
        target = links.get(label.strip().lower())
        # An entry bound to a page by hand (`href`, a live route) keeps it.
        bound = str(row.get("href") or "")
        href = (bound if bound in live else "") or by_frame.get(target or "", "") \
            or by_name.get(label.strip().lower(), "")
        entry = {**{k: v for k, v in row.items() if k not in ("id", "active", "roles")}, "href": href or "#"}
        if roles_of.get(href):
            entry["roles"] = roles_of[href]
        out.append(entry)
    return out


def _props(shell: dict) -> str:
    """The drawn view's props besides `nav`, `controls` and the page."""
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
    # WHAT THE SHELL'S OWN READ RETURNS, else the drawing's sample: the
    # candidate's sidebar said "Sara Ahmed" to every candidate (wzml1sa6).
    rest = " ".join(f"{s['name']}={{live(props.data, {json.dumps(s['name'])}, {json.dumps(sample.get(s['name']))})}}"
                    for s in others if sample.get(s["name"]) is not None)
    return " ".join(x for x in (" ".join(handlers), " ".join(forms), rest) if x)


def _wrapper(shells: list[tuple[dict, list[dict]]], routes: list[list[str]], roles: dict[str, str],
             phone: list[str], app_name: str = "") -> str:
    """The wrapper the layout renders: the frame for this page, bound, inside
    `DrawnFrame` — the drawer the sidebar becomes on a narrow screen, and the
    design's words in the chosen language."""
    imports, frames, table = [], [], []
    for i, (shell, nav) in enumerate(shells):
        imports.append(f'import ShellView{i} from "./drawn/{shell["name"]}";')
        frames.append(
            f"function Frame{i}(props: FrameProps) {{\n"
            "  const router = useRouter();\n"
            f"  const nav = useNav(NAV{i}, props.role);\n"
            f"  return <ShellView{i} nav={{nav as any}} controls={{props.controls}} {_props(shell)}>"
            "{props.children}</ShellView" + str(i) + ">;\n"
            "}\n")
        table.append(f"  {json.dumps(str(shell['key']))}: Frame{i},")
        frames.insert(0, f"const NAV{i} = {json.dumps(nav, indent=2, ensure_ascii=False)};\n")
    return (
        '"use client";\n'
        "// The design's own frame, bound: its menu led to the pages, the page you are on lit —\n"
        "// the frame of the product the page was drawn in, when the design draws several.\n"
        'import * as React from "react";\n'
        'import { usePathname, useRouter } from "next/navigation";\n'
        'import { useIsPhone } from "@/components/DrawnResponsive";\n'
        'import { DrawnFrame } from "@/components/DrawnFrame";\n'
        'import { DrawnWords } from "@/sdk/i18n";\n'
        + "\n".join(imports) + "\n\n"
        "export const DRAWN_SHELL = true;\n\n"
        "type Entry = { href: string; roles?: string[]; [key: string]: unknown };\n"
        "type FrameProps = { children?: React.ReactNode; controls?: React.ReactNode; role?: string; data?: Record<string, unknown> };\n\n"
        "// What the shell's own read returned for this slot, else the drawing's sample.\n"
        "function live<T>(data: Record<string, unknown> | undefined, slot: string, drawn: T): T {\n"
        "  return data && slot in data ? (data[slot] as T) : drawn;\n"
        "}\n\n"
        "// An entry whose page the signed-in role may not open is not offered.\n"
        "function useNav(all: Entry[], role?: string) {\n"
        "  const path = usePathname() || \"/\";\n"
        "  const entries = all.filter((n) => !role || !n.roles?.length || n.roles.includes(role));\n"
        "  const best = entries.map((n) => n.href).filter((h) => h !== \"#\" && (path === h || path.startsWith(h + \"/\")))\n"
        "    .sort((a, b) => b.length - a.length)[0];\n"
        "  return entries.map((n, i) => ({ ...n, id: String(i), active: n.href === best }));\n"
        "}\n\n"
        + "\n".join(frames) + "\n"
        "const FRAMES: Record<string, (props: FrameProps) => React.ReactElement> = {\n"
        + "\n".join(table) + "\n};\n"
        f"const FIRST = {json.dumps(str(shells[0][0]['key']))};\n"
        f"const ROUTES: [string, string][] = {json.dumps(routes, indent=2)};\n"
        f"const ROLES: Record<string, string> = {json.dumps(roles, indent=2, ensure_ascii=False)};\n"
        f"const PHONE: string[] = {json.dumps(phone, indent=2)};\n\n"
        "function matches(route: string, path: string): boolean {\n"
        "  const pattern = \"^\" + route.replace(/\\[\\.\\.\\.[^\\]]+\\]/g, \".+\").replace(/\\[[^\\]]+\\]/g, \"[^/]+\") + \"/?$\";\n"
        "  return new RegExp(pattern).test(path);\n"
        "}\n\n"
        "export default function DrawnShell(props: { children?: React.ReactNode; controls?: React.ReactNode; role?: string;\n"
        "                                            data?: Record<string, Record<string, unknown>> }) {\n"
        "  const path = usePathname() || \"/\";\n"
        "  const phone = useIsPhone();\n"
        "  if (phone && PHONE.some((r) => matches(r, path))) return <><DrawnWords />{props.children}</>;\n"
        "  const drawn = ROUTES.find(([r]) => matches(r, path));\n"
        "  const wanted = drawn ? drawn[1] : ROLES[props.role ?? \"\"] ?? FIRST;\n"
        "  const key = FRAMES[wanted] ? wanted : FIRST;\n"
        "  const Frame = FRAMES[key];\n"
        f"  return <DrawnFrame appName={{{json.dumps(app_name, ensure_ascii=False)}}}>\n"
        "    <Frame controls={props.controls} role={props.role} data={props.data?.[key]}>{props.children}</Frame>\n"
        "  </DrawnFrame>;\n"
        "}\n"
    )


def project_drawn(doc: dict, output_dir: str | Path, app_root: str | Path) -> dict[str, Any]:
    """Write the drawn shell and copy the drawn pictures. Idempotent."""
    from services.drawn.assets import copy_into

    root = Path(app_root)
    copied = copy_into(output_dir, root)
    shells = _shells(doc)
    wrapper = root / WRAPPER
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    if not shells:
        if not wrapper.is_file() or "DRAWN_SHELL = true" in wrapper.read_text("utf-8"):
            wrapper.write_text(DEFAULT_WRAPPER, encoding="utf-8")
        (root / SHELL_LOAD).write_text(DEFAULT_SHELL_LOAD, encoding="utf-8")
        return {"assets": copied, "shell": False}
    drawn = root / DRAWN_DIR
    drawn.mkdir(parents=True, exist_ok=True)
    components = {str(v.get("name")): str(v.get("code")) for v in doc.get("drawnViews") or []
                  if isinstance(v, dict) and v.get("kind") == "component"}
    bound = []
    for shell in shells:
        (drawn / f"{shell['name']}.tsx").write_text(str(shell["code"]), encoding="utf-8")
        for name, code in components.items():
            if re.search(r'from "\./' + re.escape(name) + r'"', str(shell["code"])):
                (drawn / f"{name}.tsx").write_text(code, encoding="utf-8")
        bound.append((shell, nav_routes(doc, shell)))
    for rel in FRAME_FILES:
        (root / rel).write_text((_FOUNDATION / rel).read_text("utf-8"), encoding="utf-8")
    routes = portal_routes(doc, shells)
    roles = role_portals(doc, routes)
    wrapper.write_text(_wrapper(bound, routes, roles, phone_routes(doc),
                                 str((doc.get("application") or {}).get("name") or "")), encoding="utf-8")
    reads = _shell_loads(shells, drawn)
    (root / SHELL_LOAD).write_text(_shell_loader(reads), encoding="utf-8")
    return {"assets": copied, "shell": True, "shells": len(shells), "nav": sum(len(n) for _s, n in bound),
            "phone": len(phone_routes(doc)), "reads": len(reads)}


def _shell_loads(shells: list[dict], drawn: Path) -> list[tuple[str, str]]:
    """Write each shell's own read beside it: ``[(shell key, module name)]``."""
    out = []
    for shell in shells:
        name = f"{shell['name']}.load"
        path = drawn / f"{name}.ts"
        if str(shell.get("load") or "").strip():
            path.write_text(str(shell["load"]), encoding="utf-8")
            out.append((str(shell["key"]), name))
        elif path.is_file():
            path.unlink()
    return out


def _shell_loader(reads: list[tuple[str, str]]) -> str:
    """The layout's one call: every shell's read for the signed-in person,
    run on the server. A read that fails leaves its shell as drawn."""
    if not reads:
        return DEFAULT_SHELL_LOAD
    imports = "\n".join(f'import {{ load as read{i} }} from "./drawn/{name}";' for i, (_k, name) in enumerate(reads))
    table = "\n".join(f"  [{json.dumps(key, ensure_ascii=False)}, read{i}]," for i, (key, _n) in enumerate(reads))
    return (
        "// What each drawn shell shows of the signed-in person: its own read (the shell's `load`).\n"
        'import { currentUser, type PageContext } from "@/sdk/server";\n'
        + imports + "\n\n"
        "const READS: [string, (ctx: PageContext) => Promise<unknown>][] = [\n" + table + "\n];\n\n"
        "export async function loadShell(): Promise<Record<string, Record<string, unknown>>> {\n"
        "  const user = await currentUser();\n"
        "  if (!user) return {};\n"
        "  const ctx: PageContext = { params: {}, searchParams: {}, user };\n"
        "  const out: Record<string, Record<string, unknown>> = {};\n"
        "  await Promise.all(READS.map(async ([key, read]) => {\n"
        "    try {\n"
        "      const value = await read(ctx);\n"
        "      if (value && typeof value === \"object\") out[key] = value as Record<string, unknown>;\n"
        "    } catch (err) {\n"
        "      console.warn(`[shell] ${key} could not be read:`, err);\n"
        "    }\n"
        "  }));\n"
        "  return out;\n"
        "}\n"
    )
