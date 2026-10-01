"""Bring the running application back in step with its definition.

The Blueprint is what the application IS; the files under `app/` are what it
was last written out as. Every change writes both, so they agree — until they
do not: a change whose seam re-projected too little, a platform fix that
changed what a projection writes, a file edited by hand. Then the person sees
one thing and Smith, reading the definition, sees another, and there is no
change for Smith to make: the definition already says what was asked.

Test2, 2026-09-28: Location Explorer was public in the Blueprint and still
served from the signed-in area, off the public menu. "Make Location Explorer
public" found nothing to change; "I still cannot see it in the menu" found
the page in the menu files it read. Smith gave up twice with "I could not
turn that into a change I am sure of" — the right answer was to write the
application out again from what it already says.

Deterministic: every projection, as an undo runs them (`reproject`), and a
report of what actually moved — files compared before and after, so "nothing
was out of step" is said when it is true rather than a list of every file
rewritten identically.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Where the projections write. Dependencies and build output are not the
#: application's definition and are not read.
_WATCHED = ("src", "public")
_SKIP = ("node_modules", ".next", ".forge-check", ".forge-look")


def _fingerprint(app_root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for top in _WATCHED:
        base = app_root / top
        if not base.is_dir():
            continue
        for f in base.rglob("*"):
            if not f.is_file() or any(part in _SKIP for part in f.parts):
                continue
            try:
                out[str(f.relative_to(app_root))] = hashlib.sha1(f.read_bytes()).hexdigest()
            except OSError:
                continue
    return out


#: The engine an app runs on, as the platform ships it: template directory
#: under `templates/runtime` -> where the app keeps its copy.
ENGINE_DIRS: dict[str, str] = {
    "feel-lite": "src/lib/feel-lite",
    "workflows": "src/lib/workflows",
    "rules": "src/lib/rules",
    "events": "src/lib/events",
}


def refresh_engine(app_root: str | Path, doc: dict | None = None) -> list[str]:
    """The app's copy of the platform's engine brought up to the platform's.

    An app carries the workflow engine, the formula engine and the SDK as
    files it was built with, and nothing replaced them afterwards. F&B was
    built before the fix that made a lookup on a missing key match nothing;
    the fix shipped, F&B kept the old engine, and its duplicate check went on
    refusing every new category — on a definition that was right, so no
    change Smith could make to the app would ever pass (2026-10-01). These
    files are the platform's, not the app's: never written by an agent, never
    the person's. So every turn starts on the current ones.

    A file is written only when its content differs, so an app already
    current is untouched (a running preview does not recompile), nothing is
    deleted, and what a projection owns (`PROJECTED_PATHS`) is never written.
    Returns the paths that changed, relative to the app."""
    import shutil

    from services.blueprint.assembly import PROJECTED_PATHS
    from services.runtime_injector import _TEMPLATE_DIR

    root = Path(app_root)
    changed: list[str] = []
    for src_name, dst_rel in ENGINE_DIRS.items():
        src = _TEMPLATE_DIR / src_name
        if not src.is_dir():
            continue
        for f in sorted(src.rglob("*")):
            if not f.is_file() or "__tests__" in f.parts or f.name.endswith((".test.ts", ".spec.ts")):
                continue
            rel = f"{dst_rel}/{f.relative_to(src).as_posix()}"
            if any(rel == p or rel.startswith(p.rstrip("/") + "/") for p in PROJECTED_PATHS):
                continue
            dst = root / rel
            data = f.read_bytes()
            try:
                if dst.read_bytes() == data:
                    continue
            except OSError:
                pass
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, dst)
            changed.append(rel)
    if doc is not None:
        from services.blueprint.ui_engineer import ensure_sdk
        before = _fingerprint(root)
        ensure_sdk(doc, root)
        after = _fingerprint(root)
        changed += sorted(k for k in after if k.startswith("src/sdk/") and before.get(k) != after[k])
    if changed:
        logger.info("[engine] %s: %d engine file(s) brought up to the platform's: %s",
                    root, len(changed), ", ".join(changed[:8]))
    return changed


#: The app's frame — the platform's, not the app's: no agent writes these and
#: no projection does; the Blueprint reaches them through `shell.json`,
#: `design-dna.json` and the tokens they read. An app built before a frame
#: change (a new chrome, the language switch) kept the old frame for good, so
#: a shell the definition now asked for had no frame able to draw it.
FRAME_FILES: tuple[str, ...] = (
    "src/app/(dashboard)/layout.tsx", "src/app/(dashboard)/NotificationBell.tsx",
    "src/app/(dashboard)/AccountMenu.tsx", "src/app/(dashboard)/MobileNav.tsx",
    "src/app/(dashboard)/MobileTabBar.tsx", "src/app/(dashboard)/PersonaChrome.tsx",
    "src/app/(dashboard)/RouteBreadcrumb.tsx",
    "src/components/PublicPageFrame.tsx", "src/components/PublicNavLinks.tsx",
    "src/components/AppNavigator.tsx",
)


def frame_template(app_root: str | Path, doc: dict, rel: str) -> str | None:
    """The platform's version of a frame file, filled as a build fills it."""
    from services.runtime_injector import _resolve_app_name

    src = Path(__file__).resolve().parents[2] / "templates" / "app-foundation" / rel
    if not src.is_file():
        return None
    app = doc.get("application") or {}
    return src.read_text("utf-8").replace(
        "__APP_NAME__", _resolve_app_name(Path(app_root), app.get("name"), app.get("domain")))


def owned_frame(doc: dict) -> dict[str, str]:
    """`{file: code}` — the frame files this application owns (`frameCode`)."""
    return {str(r.get("file")): str(r.get("code") or "") for r in doc.get("frameCode") or []
            if isinstance(r, dict) and r.get("file") and r.get("code")}


def refresh_frame(app_root: str | Path, doc: dict) -> list[str]:
    """The app's frame written out: each file the application owns from its
    `frameCode` row, every other one as the platform's current version, filled
    as a build fills it (`__APP_NAME__`). Written only where the file differs,
    so a current app is untouched. Returns what changed."""
    root = Path(app_root)
    owned = owned_frame(doc)
    changed: list[str] = []
    for rel in FRAME_FILES:
        text = owned.get(rel) or frame_template(root, doc, rel)
        if text is None:
            continue
        dst = root / rel
        try:
            if dst.read_text("utf-8") == text:
                continue
        except OSError:
            pass
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text, "utf-8")
        changed.append(rel)
    return changed


#: What an app is written out by: the projections and the files they copy.
#: A change to any of these is a platform change an existing app has not had.
_PLATFORM_SOURCES = ("services/blueprint", "services/smith/reproject.py",
                     "templates/runtime", "templates/app-foundation/src")
_STAMP: dict[str, str] = {}
STAMP_FILE = "platform-stamp"


def platform_stamp() -> str:
    """A fingerprint of the code that writes an application out — computed
    once per process, since it changes only when the platform is deployed."""
    if "v" not in _STAMP:
        backend = Path(__file__).resolve().parents[2]
        h = hashlib.sha1()
        for rel in _PLATFORM_SOURCES:
            base = backend / rel
            files = [base] if base.is_file() else sorted(
                f for f in base.rglob("*") if f.is_file() and "__pycache__" not in f.parts)
            for f in files:
                h.update(str(f.relative_to(backend)).encode())
                try:
                    h.update(f.read_bytes())
                except OSError:
                    continue
        _STAMP["v"] = h.hexdigest()[:16]
    return _STAMP["v"]


def catch_up(output_dir: str | Path) -> list[str]:
    """The application written out again when the platform that writes it has
    changed since it was last written: the files that moved, or [].

    A fix to a projection reached only the apps built after it. F&B's
    definition sent its administrator to the back office; its `account.ts`
    had been projected before the projection wrote each role's landing, so
    the administrator landed on the customers' menu, and the turn spent
    twelve steps trying to edit a generated file by hand (2026-10-01). The
    platform's own fixes are the platform's to deliver: once per platform
    version, at the start of the next turn, before anyone reads anything."""
    out = Path(output_dir)
    app_root = out / "app"
    stamp_path = out / ".forge" / STAMP_FILE
    if not (app_root / "package.json").is_file() or not (out / ".forge" / "blueprint" / "current.json").is_file():
        return []
    stamp = platform_stamp()
    try:
        if stamp_path.read_text("utf-8").strip() == stamp:
            return []
    except OSError:
        pass
    from services.blueprint.service import BlueprintService
    done = sync(BlueprintService.load(output_dir=str(out)), str(app_root))
    stamp_path.write_text(stamp, "utf-8")
    moved = done["changed"] + done["added"] + done["removed"]
    if moved:
        logger.info("[catch-up] %s: written out for platform %s, %d file(s) moved: %s",
                    out, stamp, len(moved), ", ".join(moved[:8]))
    return moved


def sync(svc: Any, app_root: str) -> dict:
    """Write every projection from `svc.doc`; what changed, added and went."""
    from services.smith.reproject import everything

    from services.blueprint.schema_push import push_now

    root = Path(app_root)
    before = _fingerprint(root)
    refresh_engine(root, svc.doc)
    refresh_frame(root, svc.doc)
    everything(svc, app_root)
    after = _fingerprint(root)
    changed = sorted(k for k in after if k in before and before[k] != after[k])
    added = sorted(k for k in after if k not in before)
    removed = sorted(k for k in before if k not in after)
    # THE DATABASE IS PART OF THE APPLICATION TOO. A record added before its
    # table could be created (Test2's Area) is in the schema files and not in
    # the database; bringing the app in step brings that in step as well.
    pushed = push_now(root)
    try:
        (root.parent / ".forge" / STAMP_FILE).write_text(platform_stamp(), "utf-8")
    except OSError:
        pass
    return {"changed": changed, "added": added, "removed": removed,
            "database": "in step" if pushed["applied"] else pushed["reason"]}


def summary_of(out: dict) -> str:
    moved = out["changed"] + out["added"] + out["removed"]
    db = out.get("database") or ""
    db_line = (" Its database schema is in step too." if db == "in step"
               else f" The database schema could not be brought in step now: {db}." if db else "")
    if not moved:
        return ("The application already matches its definition — nothing was out of step." + db_line
                + " If something still looks wrong, tell me what you see and where.")
    head = ", ".join(moved[:6]) + (f" and {len(moved) - 6} more" if len(moved) > 6 else "")
    return (f"The application was out of step with its definition, so I wrote it out again from "
            f"what it says: {len(moved)} file(s) brought back in line ({head}).{db_line} Reload the "
            f"preview to see it.")


def run(output_dir: str, *, reasoning: Any = None) -> dict:
    """The seam envelope: `{applied, diff_summary, edited_paths, reason}`."""
    from services.blueprint.service import BlueprintService
    from services.llm_client import tell

    app_root = Path(output_dir) / "app"
    if not (app_root / "package.json").is_file():
        return {"applied": False, "edited_paths": [],
                "reason": "The application has not been built yet, so there is nothing to bring in step."}
    try:
        svc = BlueprintService.load(output_dir=output_dir)
        tell(reasoning, "Writing the application out again from its definition.", "step")
        out = sync(svc, str(app_root))
    except Exception as exc:  # noqa: BLE001 — a tool degrades, it does not crash
        logger.exception("[sync_app] %s", output_dir)
        return {"applied": False, "edited_paths": [], "reason": f"{type(exc).__name__}: {exc}"}
    moved = out["changed"] + out["added"] + out["removed"]
    return {"applied": True, "edited_paths": moved, "diff_summary": summary_of(out), **out}


__all__ = ["ENGINE_DIRS", "FRAME_FILES", "catch_up", "frame_template", "owned_frame", "refresh_frame", "platform_stamp", "refresh_engine", "run", "summary_of", "sync"]
