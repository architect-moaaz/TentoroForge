"""Smith changes the application's FRAME — any part of it, however small.

The frame is what is around every screen: the signed-in layout (its rail, top
bar or dock, the header row with the bell and the account menu), the public
pages' header and footer, the phone's tab bar and drawer. It is the platform's
code, kept current by `sync_app.refresh_frame`, and until now nothing could
change it for one application: "centre the menu", "put a search box in the
top bar", "move the bell to the left" had no tool, and the kind of frame
(`designSystem.shell.chrome`) was the only lever. A person can ask for
anything about it.

So a frame file becomes the application's own the first time it is changed:
the change is made to that file's code with edits — the way a screen is
changed — compiled, and kept in the Blueprint as a `frameCode` row, which is
versioned and undoable like `pageCode` and which `refresh_frame` writes from
then on in place of the platform's version.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

from services.llm_client import tell

logger = logging.getLogger(__name__)

#: Rounds of compile-and-fix before the change is refused.
ROUNDS = 3

#: What each frame file holds — what the loop chooses from.
FRAME_PARTS: dict[str, str] = {
    "src/app/(dashboard)/layout.tsx": (
        "the signed-in frame around every screen: the navigation (rail, top bar or dock, "
        "as `designSystem.shell.chrome` decides), the header row with the language switch, "
        "the bell and the account menu, the breadcrumb, the page container"),
    "src/app/(dashboard)/NotificationBell.tsx": "the bell and its list of notifications",
    "src/app/(dashboard)/AccountMenu.tsx": "the account menu: the person's name, role, sign out",
    "src/app/(dashboard)/MobileNav.tsx": "the phone's drawer menu (behind the menu button)",
    "src/app/(dashboard)/MobileTabBar.tsx": "the phone's bottom tab bar",
    "src/app/(dashboard)/PersonaChrome.tsx": "the persona frame some applications use instead of a rail",
    "src/app/(dashboard)/RouteBreadcrumb.tsx": "the breadcrumb above each signed-in screen",
    "src/components/PublicPageFrame.tsx": "the public pages' header (brand, links, sign in) and footer",
    "src/components/PublicNavLinks.tsx": "the links in the public header",
    "src/components/AppNavigator.tsx": "the quick navigator (jump to a screen)",
}

EDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "edits": {"type": "array", "items": {"type": "object", "properties": {
            "find": {"type": "string"}, "replace": {"type": "string"}},
            "required": ["find", "replace"], "additionalProperties": False}},
        "rationale": {"type": "string",
                      "description": "what changed, in one or two sentences the person can read"},
    },
    "required": ["edits", "rationale"],
    "additionalProperties": False,
}

SYSTEM = (
    "You change ONE file of a generated application's frame — the part around every screen. "
    "Next.js 15 App Router, React 19, TypeScript strict, Tailwind with the application's "
    "semantic colour classes (bg-card, text-foreground, border-border, bg-primary, "
    "text-muted-foreground…; never hex). Make exactly the change asked and keep everything "
    "else as it is: every control the frame has (navigation, the language switch, the bell, "
    "the account menu, sign in/out) stays and keeps working unless the ask says to remove it. "
    "The file stays the kind of module it is: a server component (no `\"use client\"` at the "
    "top) uses no hooks or event handlers — a search box there is a plain "
    "`<form action=… method=\"get\">`, and it may render the client components it can import "
    "(`@/sdk/i18n`, `@/components/*`, its neighbours); a client component may use state and "
    "handlers. "
    "Reply with `edits`: each `find` copied EXACTLY from the code (whitespace included, long "
    "enough to occur once), applied in order; and `rationale`."
)


class FrameChangeError(ValueError):
    """The frame could not be changed, with the reason in words."""


def normalise(file: str) -> str:
    rel = str(file or "").strip().lstrip("/")
    if rel.startswith("app/"):
        rel = rel[4:]
    return rel


def apply_edits(code: str, edits: list[dict]) -> str:
    """Each `find` must occur exactly once in the code as it stands."""
    for i, e in enumerate(edits or [], 1):
        find, replace = str(e.get("find") or ""), str(e.get("replace") or "")
        if not find:
            raise FrameChangeError(f"edit {i} has no `find`")
        n = code.count(find)
        if n != 1:
            raise FrameChangeError(f"edit {i}'s `find` occurs {n} times in the current code — it must "
                                   "be copied exactly and occur once")
        code = code.replace(find, replace, 1)
    return code


def typecheck(app_root: Path, rel: str, code: str, timeout: float = 240.0) -> list[str]:
    """Compile the frame file in place with `code`; the errors in that file.

    The frame imports its neighbours (`./NotificationBell`), so it cannot be
    compiled from a copy elsewhere the way a page is: the candidate is put in
    place for the compile and the file as it was is put back afterwards — the
    caller writes the accepted version."""
    tsc_path = shutil.which("tsc", path=str(app_root / "node_modules" / ".bin"))
    if not tsc_path:
        raise FrameChangeError("there is no TypeScript compiler in the application yet, so a change "
                               "to its frame cannot be checked")
    target = app_root / rel
    original = target.read_text("utf-8") if target.is_file() else None
    check = app_root / ".forge-check" / f"frame-{os.getpid()}-{threading.get_ident()}"
    shutil.rmtree(check, ignore_errors=True)
    check.mkdir(parents=True)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(code, "utf-8")
        (check / "tsconfig.json").write_text(json.dumps({
            "extends": "../../tsconfig.json",
            "compilerOptions": {"incremental": False, "noEmit": True},
            "include": [f"../../{rel}", "../../next-env.d.ts", "../../src/types/**/*.d.ts"],
        }))
        proc = subprocess.run([tsc_path, "-p", str(check / "tsconfig.json"), "--pretty", "false"],
                              cwd=str(app_root), capture_output=True, text=True, encoding="utf-8",
                              timeout=timeout)
        errors, ours = [], False
        for line in (proc.stdout + proc.stderr).splitlines():
            # tsc names the file relative to its cwd; under a symlinked root
            # that is a longer path ending in the same one.
            where = line.split(".tsx(", 1)[0] + ".tsx" if ".tsx(" in line else ""
            if where.endswith(rel):
                errors.append(line[line.index(rel):])
                ours = True
            elif ours and line.startswith(" "):
                errors[-1] += " " + line.strip()
            else:
                ours = False
        return errors
    finally:
        shutil.rmtree(check, ignore_errors=True)
        if original is None:
            target.unlink(missing_ok=True)
        else:
            target.write_text(original, "utf-8")


_FORM = re.compile(r"<form\b([^>]*)>(.*?)</form>", re.S)
_ACTION = re.compile(r"""\baction=\{?\s*["'`]([^"'`]+)["'`]""")
_FIELD = re.compile(r"""\bname=["']([A-Za-z_][\w-]*)["']""")


def unwired_queries(code: str, doc: dict) -> list[str]:
    """What a form in the frame sends to a screen that does not read it.

    The search box a person asked for in the nav bar submitted `q` to the menu,
    and the menu never read `q`: the change was reported done, and the search
    found nothing (F&B replay, 2026-10-01). A control that leads somewhere is
    only working when the place it leads does it — read off the target
    screen's own code, the way the action-integrity checks read a button."""
    from services.smith.compose import _page_for_route, code_row

    out: list[str] = []
    for attrs, inner in _FORM.findall(code):
        if re.search(r"""method=["']post["']""", attrs, re.I):
            continue
        action = _ACTION.search(attrs)
        route = (action.group(1) if action else "").split("?")[0].strip() or "/"
        if not route.startswith("/"):
            continue
        page = _page_for_route(doc, route)
        row = code_row(doc, str((page or {}).get("id"))) if page else None
        if row is None:
            continue                      # a screen not written as code: nothing to read it off
        text = str(row.get("load") or "") + "\n" + str(row.get("view") or "")
        for name in dict.fromkeys(_FIELD.findall(inner)):
            reads = re.search(rf"""searchParams(\?\.|\.)\s*{re.escape(name)}\b|searchParams\[["']{re.escape(name)}["']\]|\.get\(["']{re.escape(name)}["']\)""", text)
            if not reads:
                out.append(f"the frame sends `{name}` to `{route}`, and `{route}` does not read it")
    return out


def _client(reasoning: Any = None) -> Any:
    from services.blueprint.executors import tiered_router
    return tiered_router(reasoning=reasoning).for_task("page_code", "ui_engineer")


def change_frame(svc: Any, file: str, brief: str, *, app_root: str, client: Any = None,
                 reasoning: Any = None, check: Any = None) -> dict:
    """Change one frame file to `brief`, compiled, as one version. Returns
    `{applied, file, rationale, version}` or raises FrameChangeError."""
    from services.blueprint.service import BlueprintInvalid
    from services.smith.sync_app import FRAME_FILES, frame_template, owned_frame

    rel = normalise(file)
    if rel not in FRAME_FILES:
        raise FrameChangeError(f"`{file}` is not part of the frame. The frame's files: "
                               + "; ".join(f"`{f}` — {FRAME_PARTS.get(f, '')}" for f in FRAME_FILES))
    brief = (brief or "").strip()
    if not brief:
        raise FrameChangeError("nothing was described, so there is nothing to change in the frame")
    root = Path(app_root)
    current = owned_frame(svc.doc).get(rel)
    if current is None:
        on_disk = root / rel
        current = on_disk.read_text("utf-8") if on_disk.is_file() else frame_template(root, svc.doc, rel)
    if not current:
        raise FrameChangeError(f"the application has no `{rel}` to change")
    call = client or _client(reasoning)
    compile_ = check or (lambda code: typecheck(root, rel, code))
    # WHERE THINGS ARE. A search box was pointed at `/menu` in an app whose
    # menu is `/`: the frame links to screens, and only the app knows them.
    screens = "The application's screens (name → route; link only to these):\n" + "\n".join(
        f"- {p.get('name')} → {p.get('route')}" + (" (public)" if str(p.get("access") or "") == "public" else "")
        for p in svc.doc.get("pages") or [] if isinstance(p, dict) and p.get("route")
        and p.get("status") != "DEPRECATED")
    note = ""
    tell(reasoning, f"Changing the frame ({rel}): {brief}", "step")
    for round_ in range(1, ROUNDS + 1):
        user = (f"The change asked for: \"{brief}\".\n\n{screens}\n\nThe file `{rel}` — {FRAME_PARTS.get(rel, '')}:\n"
                f"```tsx\n{current}\n```" + (f"\n\nYour last reply was refused:\n{note}\nFix that." if note else ""))
        reply = call(system=SYSTEM, user=user, schema=EDIT_SCHEMA)
        try:
            data = json.loads(str(getattr(reply, "text", reply)))
            candidate = apply_edits(current, data.get("edits") or [])
        except (ValueError, FrameChangeError) as exc:
            note = str(exc)
            continue
        if candidate == current:
            note = "the edits changed nothing — the change asked for is not in the file yet"
            continue
        errors = compile_(candidate)
        if errors:
            note = "it does not compile:\n" + "\n".join(errors[:12])
            logger.info("[frame] %s round %d: %d error(s)", rel, round_, len(errors))
            continue
        before = svc.snapshot()
        rows = [r for r in svc.doc.get("frameCode") or [] if isinstance(r, dict) and r.get("file") != rel]
        rows.append({"file": rel, "rationale": brief, "code": candidate})
        svc.doc["frameCode"] = rows
        try:
            svc.validate()
        except BlueprintInvalid as exc:
            svc.doc = before
            raise FrameChangeError(f"the changed frame does not fit the Blueprint: {exc}") from exc
        record = svc.commit(user_request=brief, smith_interpretation=f"change the frame: {rel}",
                            before=before, affected=[])
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(candidate, "utf-8")
        return {"applied": True, "file": rel, "rationale": str(data.get("rationale") or "").strip(),
                "version": int(record["version"]), "unwired": unwired_queries(candidate, svc.doc)}
    raise FrameChangeError(f"the frame was not changed after {ROUNDS} tries — {note}")


def run(output_dir: str, file: str, brief: str, *, reasoning: Any = None) -> dict:
    """The write tool's envelope: `{applied, said, finding, touched, version}`."""
    from services.blueprint.service import BlueprintService
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
        out = change_frame(svc, file, brief, app_root=str(Path(output_dir) / "app"), reasoning=reasoning)
    except FrameChangeError as exc:
        text = f"The frame was not changed: {exc}"
        return {"applied": False, "said": text, "finding": text, "touched": [], "version": 0}
    except Exception as exc:  # noqa: BLE001 — a tool degrades, it does not crash
        logger.exception("[frame] change failed")
        text = f"The frame was not changed — {type(exc).__name__}: {exc}"
        return {"applied": False, "said": text, "finding": text, "touched": [], "version": 0}
    said = (f"Changed the application's frame (`{out['file']}`, version {out['version']})"
            + (f": {out['rationale']}" if out["rationale"] else ".")
            + " This part of the frame is now the application's own.")
    unwired = out.get("unwired") or []
    finding = ("Not working yet: " + "; ".join(unwired) + ". Make that screen use it — `write_page_code` "
               "so its list narrows by it (`ctx.searchParams` in load.ts) — then `open_page` the screen "
               "with a value from its data in the query and see the list narrow." if unwired else "")
    return {"applied": True, "said": said, "finding": finding, "touched": [f"app/{out['file']}"],
            "version": out["version"]}


__all__ = ["FRAME_PARTS", "FrameChangeError", "apply_edits", "change_frame", "normalise", "run", "typecheck"]
