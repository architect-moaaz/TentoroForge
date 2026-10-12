"""Smith changes any file of the application, directly — and the change lasts.

Every one-line fix used to be a brief to an agent that rewrote a whole page or
a whole definition: minutes per step, a reply the turn could not use, and on
UAT 12 of Smith's 121 replies in ten days ended with something changed
(2026-10-07). A fix is an exact edit — the text that is there, the text that
should be — and what happens to it depends on whose the file is:

* **page** — a coded page's view, load or part. The edit goes into the page's
  code in the Blueprint (`pageCode`), is type-checked, and the files are
  written from it, so a rebuild keeps it.
* **definition** — a file the projection writes from the Blueprint (a
  workflow's definition, the schema, who may open what, where a role lands).
  Edited in place it would be written over on the next turn and disagree with
  the definition every check reads, so the edit is made to the definition
  (`edit_definition`, the text `read_section` shows) and the app is written
  out again from it.
* **platform** — the engine, the SDK, the runtime routes, the frame: the
  platform's, copied into every app. A fault there is every app's; the edit is
  kept for THIS app as a recorded patch, re-applied after each platform
  refresh, and filed for the platform. It is held to proof: a try must show
  the fault before the edit, and a try after it must pass, or the patch is
  taken back at the end of the turn. When the platform's own copy changes at
  that spot — the fix folded in, or the code moved on — the patch retires.
* **app** — anything else in `app/`: edited in place and recorded, so a
  rewrite of the file brings the edit back.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PATCHES_FILE = "patches.json"
#: The platform's own list of open patches, across every app, for the people
#: who fold them in (`open_patches`).
REGISTRY_DIR = "_platform_patches"

#: Directories under `app/` that are built or installed, never edited.
_NEVER = ("node_modules/", ".next/", ".next-review/", ".next-verify/", ".forge-check/", ".turbo/")

#: Files written from the definition, and the section that writes each.
_DEFINITION = (
    (re.compile(r"^src/lib/workflows/definitions/[^/]+\.json$"), "workflows"),
    (re.compile(r"^src/lib/workflows/launch-roles\.ts$"), "pages (each page's `access` and `users`) and workflows (`launchedFrom`)"),
    (re.compile(r"^src/lib/entity-access\.ts$"), "pages (each page's `access`, `users` and the records it shows)"),
    (re.compile(r"^src/lib/(ownership-rules|sensitive-columns|searchable-columns|embedding-columns|append-only-entities)\.ts$"), "security"),
    (re.compile(r"^src/lib/account(-table)?\.ts$"), "navigation.initialRoute, roles and the account entity in data.entities"),
    (re.compile(r"^src/db/schema/(?!_forge|user\.ts|index\.ts)[^/]+\.ts$"), "data.entities"),
    (re.compile(r"^src/db/seed\.json$"), "data.entities (sample rows)"),
    (re.compile(r"^src/schemas/"), "pages"),
    (re.compile(r"^src/middleware\.ts$"), "pages (each page's `access`)"),
    (re.compile(r"^src/app/tokens\.css$"), "designSystem"),
    (re.compile(r"^src/lib/(entity-aliases\.ts|fk-labels\.json|languages\.ts)$"), "data.entities"),
    (re.compile(r"^rules/blueprint-rules\.json$"), "businessRules"),
)

#: The SDK modules generated from the definition; the rest of `src/sdk` is the platform's.
_SDK_GENERATED = ("src/sdk/schema.ts", "src/sdk/pages.ts", "src/sdk/workflows.ts", "src/sdk/widgets.ts")


# --------------------------------------------------------------------------- #
# Whose file is it
# --------------------------------------------------------------------------- #

def _platform_paths() -> tuple[list[str], list[str]]:
    """(directories, files) the platform owns inside an app."""
    from services.smith.sync_app import (DB_SCRIPTS, ENGINE_DIRS, ENGINE_FOUNDATION_FILES, FRAME_FILES,
                                         RUNTIME_FILES, WORKFLOW_ROUTES)
    dirs = [d.rstrip("/") + "/" for d in ENGINE_DIRS.values()] + ["src/sdk/", "vendor/"]
    files = ([rel for _t, rel in RUNTIME_FILES] + list(DB_SCRIPTS) + list(ENGINE_FOUNDATION_FILES)
             + list(WORKFLOW_ROUTES) + list(FRAME_FILES)
             + ["src/app/api/data/[...path]/route.ts", "src/lib/schema-page.tsx",
                "src/lib/SchemaPageBoundary.tsx", "vercel.json", "src/auth.ts"])
    return dirs, files


def classify(doc: dict, rel: str) -> dict:
    """`{kind, ...}` for an app-relative path: `page` (with page and key),
    `definition` (with the section that writes it), `platform` or `app`."""
    from services.blueprint.app_sdk import code_page_files

    for row in doc.get("pageCode") or []:
        if not isinstance(row, dict) or not str(row.get("view") or "").strip():
            continue
        for path in code_page_files(doc, row):
            if path == rel:
                key = ("view" if rel.endswith("/view.tsx") else "load" if rel.endswith("/load.ts")
                       else f"parts.{Path(rel).stem}" if "/parts/" in rel else "")
                if key:
                    return {"kind": "page", "page": str(row.get("page")), "key": key}
    for rx, section in _DEFINITION:
        if rx.search(rel):
            return {"kind": "definition", "section": section}
    if rel in _SDK_GENERATED:
        return {"kind": "definition", "section": "the definition as a whole (the SDK is generated from it)"}
    dirs, files = _platform_paths()
    if rel in files or any(rel.startswith(d) for d in dirs):
        # Inside the engine's directories, what the projection writes is the definition's.
        if rel.startswith("src/lib/workflows/") and rel.endswith("launch-roles.ts"):
            return {"kind": "definition", "section": "pages and workflows"}
        return {"kind": "platform"}
    return {"kind": "app"}


def platform_text(rel: str) -> str | None:
    """The platform's current copy of an app's platform file, or None when it
    is written by code rather than copied (or not the platform's)."""
    from services.runtime_injector import _TEMPLATE_DIR
    from services.smith.sync_app import DB_SCRIPTS, ENGINE_DIRS, ENGINE_FOUNDATION_FILES, RUNTIME_FILES
    foundation = Path(__file__).resolve().parents[2] / "templates" / "app-foundation"
    candidates: list[Path] = []
    for src, dst in ENGINE_DIRS.items():
        if rel.startswith(dst.rstrip("/") + "/"):
            candidates.append(_TEMPLATE_DIR / src / rel[len(dst.rstrip("/")) + 1:])
    candidates += [_TEMPLATE_DIR / t for t, a in RUNTIME_FILES if a == rel]
    if rel in DB_SCRIPTS or rel in ENGINE_FOUNDATION_FILES or rel.startswith("src/sdk/"):
        candidates.append(foundation / rel)
    for c in candidates:
        if c.is_file():
            try:
                return c.read_text("utf-8")
            except (OSError, UnicodeDecodeError):
                return None
    return None


# --------------------------------------------------------------------------- #
# The patch record
# --------------------------------------------------------------------------- #

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _patches_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / ".forge" / PATCHES_FILE


def load_patches(output_dir: str | Path) -> list[dict]:
    try:
        data = json.loads(_patches_path(output_dir).read_text("utf-8"))
        return [p for p in data if isinstance(p, dict)] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_patches(output_dir: str | Path, patches: list[dict]) -> None:
    path = _patches_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(patches, indent=1, ensure_ascii=False), "utf-8")
    tmp.replace(path)


def _register(output_dir: str | Path, patch: dict) -> None:
    """Every platform patch's state, for the platform's people: one line per
    change, beside every app's folder."""
    if patch.get("kind") != "platform":
        return
    try:
        reg = Path(output_dir).parent / REGISTRY_DIR
        reg.mkdir(parents=True, exist_ok=True)
        with (reg / "patches.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"app": Path(output_dir).name, "at": _now(),
                                 **{k: patch.get(k) for k in ("id", "path", "status", "why", "find", "replace",
                                                              "proof", "note")}},
                                ensure_ascii=False) + "\n")
    except OSError:
        logger.warning("[patches] could not register %s", patch.get("id"), exc_info=True)


def open_patches(output_root: str | Path) -> list[dict]:
    """Every app's platform patches that are still in force or awaiting proof."""
    out = []
    for f in sorted(Path(output_root).glob(f"*/.forge/{PATCHES_FILE}")):
        app = f.parent.parent.name
        for p in load_patches(f.parent.parent):
            if p.get("kind") == "platform" and p.get("status") in ("active", "pending"):
                out.append({"app": app, **p})
    return out


def _replace_once(text: str, find: str, replace: str, where: str) -> tuple[str | None, str]:
    """(new text, "") or (None, why not)."""
    if not find:
        return None, "`find` is empty — give the exact text that is there now."
    n = text.count(find)
    if n == 0:
        return None, (f"The text to find is not in {where}. Read it again (it may have changed) and give "
                      "the exact text, spaces and line breaks included.")
    if n > 1:
        return None, f"The text to find appears {n} times in {where}; include more of what surrounds it."
    return text.replace(find, replace, 1), ""


def reapply(output_dir: str | Path) -> list[str]:
    """Bring every kept patch back after something rewrote its file, and
    retire a platform patch whose spot the platform has since changed.
    Returns one line per patch that moved."""
    patches = load_patches(output_dir)
    if not patches:
        return []
    app = Path(output_dir) / "app"
    said: list[str] = []
    changed = False
    for p in patches:
        if p.get("status") != "active":
            continue
        rel, find, replace = str(p.get("path")), str(p.get("find") or ""), str(p.get("replace") or "")
        if p.get("kind") == "platform":
            fresh = platform_text(rel)
            if fresh is not None and (replace in fresh or find not in fresh):
                p.update(status="retired", note=("the platform now has this fix" if replace in fresh
                                                 else "the platform changed this code; the patch no longer applies"),
                         retired=_now())
                changed = True
                _register(output_dir, p)
                said.append(f"{rel}: platform patch {p.get('id')} retired — {p['note']}")
                continue
        target = app / rel
        try:
            text = target.read_text("utf-8")
        except OSError:
            continue
        if replace and replace in text and find not in text:
            continue                                   # still in place
        if find in text and text.count(find) == 1:
            target.write_text(text.replace(find, replace, 1), "utf-8")
            said.append(f"{rel}: patch {p.get('id')} put back")
        elif find not in text:
            p.update(status="retired", note="the file no longer holds the text the patch changed", retired=_now())
            changed = True
            _register(output_dir, p)
            said.append(f"{rel}: patch {p.get('id')} retired — {p['note']}")
    if changed:
        _save_patches(output_dir, patches)
    if said:
        logger.info("[patches] %s: %s", Path(output_dir).name, "; ".join(said))
    return said


def settle(output_dir: str | Path, ids: list[str], proven: bool) -> list[str]:
    """A turn's pending platform patches: kept when a try after them passed,
    taken back when not. Returns what the person is told."""
    if not ids:
        return []
    patches = load_patches(output_dir)
    app = Path(output_dir) / "app"
    said: list[str] = []
    for p in patches:
        if p.get("id") not in ids or p.get("status") != "pending":
            continue
        if proven:
            p.update(status="active", proven=_now())
            said.append(f"Kept the platform patch to `{p.get('path')}` for this app — a try after it passed — "
                        "and filed it for the platform to fold in.")
        else:
            target = app / str(p.get("path"))
            try:
                text = target.read_text("utf-8")
                if str(p.get("replace")) in text:
                    target.write_text(text.replace(str(p.get("replace")), str(p.get("find")), 1), "utf-8")
            except OSError:
                pass
            p.update(status="reverted", note="no try after it passed", retired=_now())
            said.append(f"Took back the change to `{p.get('path')}`: no try after it showed it fixed anything.")
        _register(output_dir, p)
    _save_patches(output_dir, patches)
    return said


# --------------------------------------------------------------------------- #
# The edits
# --------------------------------------------------------------------------- #

def _app_rel(output_dir: str, path: str) -> tuple[str | None, str]:
    from services.smith.reads import ReadRefused, _jail, _secret_name
    try:
        target = _jail(output_dir, path)
    except ReadRefused as exc:
        return None, str(exc)
    app = (Path(output_dir) / "app").resolve()
    if app not in target.parents:
        return None, f"`{path}` is not a file of the application (`app/`)."
    rel = target.relative_to(app).as_posix()
    if any(rel.startswith(n) or f"/{n}" in f"/{rel}" for n in _NEVER):
        return None, f"`{path}` is built or installed output; change its source instead."
    if _secret_name(target):
        return None, f"`{path}` holds credentials and is not edited here."
    return rel, ""


def edit_file(output_dir: str, path: str, find: str, replace: str, why: str = "") -> dict:
    """Change `find` (exact, once) to `replace` in an app file. Returns
    `{applied, said, finding, touched, kind, patch}`."""
    from services.blueprint.service import BlueprintService

    rel, refused = _app_rel(output_dir, path)
    if rel is None:
        return {"applied": False, "said": "", "finding": refused, "touched": []}
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
        doc = svc.doc
    except FileNotFoundError:
        svc, doc = None, {}
    kind = classify(doc, rel)
    why = " ".join(str(why or "").split())

    if kind["kind"] == "definition":
        return {"applied": False, "said": "", "touched": [], "kind": "definition",
                "finding": (f"`{rel}` is written from the definition — {kind['section']} — and an edit here "
                            "would be written over on the next turn and disagree with what every check "
                            "reads. Make the edit in the definition with `edit_definition` (read_section "
                            "shows its text); the app is written out again from it.")}

    if kind["kind"] == "page" and svc is not None:
        return _edit_page(svc, output_dir, rel, kind, find, replace, why)

    target = Path(output_dir) / "app" / rel
    try:
        text = target.read_text("utf-8")
    except FileNotFoundError:
        return {"applied": False, "said": "", "touched": [],
                "finding": f"There is no `{rel}` in the app. `list_files` shows what is there."}
    except UnicodeDecodeError:
        return {"applied": False, "said": "", "touched": [], "finding": f"`{rel}` is not a text file."}
    new, why_not = _replace_once(text, find, replace, f"`{rel}`")
    if new is None:
        return {"applied": False, "said": "", "touched": [], "finding": why_not}
    target.write_text(new, "utf-8")
    patch = {"id": uuid.uuid4().hex[:10], "path": rel, "kind": kind["kind"], "find": find, "replace": replace,
             "why": why, "at": _now(), "status": "pending" if kind["kind"] == "platform" else "active"}
    patches = load_patches(output_dir) + [patch]
    _save_patches(output_dir, patches)
    _register(output_dir, patch)
    if kind["kind"] == "platform":
        said = (f"Changed the platform's `{rel}` for this app" + (f": {why}" if why else "") +
                " — kept only if a try after it passes.")
    else:
        said = f"Changed `{rel}`" + (f": {why}" if why else "") + "."
    return {"applied": True, "said": said, "finding": "", "touched": [f"app/{rel}"],
            "kind": kind["kind"], "patch": patch["id"]}


def _edit_page(svc: Any, output_dir: str, rel: str, kind: dict, find: str, replace: str, why: str) -> dict:
    from services.blueprint.app_sdk import code_page_files
    from services.blueprint.ui_engineer import typecheck

    row = next(r for r in svc.doc.get("pageCode") or [] if isinstance(r, dict) and str(r.get("page")) == kind["page"])
    key = kind["key"]
    current = (str((row.get("parts") or {}).get(key[6:]) or "") if key.startswith("parts.")
               else str(row.get(key) or ""))
    new, why_not = _replace_once(current, find, replace, f"`{rel}` (as the page's code holds it)")
    if new is None:
        return {"applied": False, "said": "", "touched": [], "finding": why_not}
    edited = json.loads(json.dumps(row))
    if key.startswith("parts."):
        edited.setdefault("parts", {})[key[6:]] = new
    else:
        edited[key] = new
    app_root = Path(output_dir) / "app"
    try:
        errors = typecheck(svc.doc, app_root, kind["page"], str(edited.get("load") or ""),
                           str(edited.get("view") or ""), parts=edited.get("parts") or None)
    except Exception as exc:  # noqa: BLE001 — no compiler is not a pass
        return {"applied": False, "said": "", "touched": [],
                "finding": f"`{rel}` was not changed: it could not be type-checked ({type(exc).__name__}: {exc})."}
    if errors:
        return {"applied": False, "said": "", "touched": [],
                "finding": f"`{rel}` was not changed — it would not compile:\n" + "\n".join(errors[:8])}
    before = svc.snapshot()
    row.clear()
    row.update(edited)
    try:
        svc.commit(user_request=why or f"Edit {rel}", smith_interpretation=f"Edited {rel}", before=before,
                   affected=[kind["page"]] if re.match(r"^PAGE-\d{3,}$", kind["page"]) else [])
    except Exception as exc:  # noqa: BLE001 — the document refused it; nothing is written
        svc.doc = before
        return {"applied": False, "said": "", "touched": [], "finding": f"`{rel}` was not changed: {exc}"}
    touched = []
    for path, content in code_page_files(svc.doc, row).items():
        dest = app_root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists() or dest.read_text("utf-8") != content:
            dest.write_text(content, "utf-8")
            touched.append(f"app/{path}")
    return {"applied": True, "said": f"Changed `{rel}`" + (f": {why}" if why else "") + ".",
            "finding": "", "touched": touched or [f"app/{rel}"], "kind": "page"}


def _locate(doc: dict, name: str) -> tuple[Any, Any, Any]:
    """(parent, key, node) for a dotted section name, as `read_section` reads it."""
    from services.smith.reads import _item
    parent, key, node = None, None, doc
    for part in [p for p in (name or "").split(".") if p]:
        if isinstance(node, dict) and part in node:
            parent, key, node = node, part, node[part]
        elif isinstance(node, list) and _item(node, part) is not None:
            item = _item(node, part)
            parent, key, node = node, node.index(item), item
        else:
            return None, None, None
    return parent, key, node


#: The contract's own checks, by the section an edit reaches.
def _check(section_root: str, doc: dict, body: Any, natural_key: str) -> None:
    from services.blueprint import agent_contract as ac
    sec = {"data": "data.entities"}.get(section_root, section_root)
    result = ac.AgentResult(task_id="smith-edit", agent="smith", proposals=[
        ac.ArtifactProposal(section=sec, natural_key=natural_key or sec, body=body)])
    for check in (ac.check_workflow_steps, ac.check_business_rules, ac.check_entity_fields,
                  ac.check_page_content, ac.check_page_access, ac.check_role_doors, ac.check_navigation,
                  ac.check_analytics, ac.check_security):
        check(result, doc)


def edit_definition(output_dir: str, section: str, find: str, replace: str, why: str = "") -> dict:
    """Change `find` to `replace` in one part of the definition — the text
    `read_section(section)` shows — check it as the build would, record it,
    and write the app out again from it."""
    from services.blueprint.service import BlueprintService
    from services.smith.sync_app import sync

    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return {"applied": False, "said": "", "touched": [], "finding": "This project has no definition yet."}
    if section.split(".", 1)[0] == "expectations":
        # WHAT MUST HAPPEN IS NOT WHAT GETS FIXED. A statement the app fails
        # is the fault's description; editing it until it passes would be
        # the fixer grading its own work. A new one is `add_expectation`.
        return {"applied": False, "said": "", "touched": [],
                "finding": ("The statements of what must happen are not edited to fit the app — fix the app "
                            "until they hold. Changing what must happen is a change to the requirements: say "
                            "so to the person. A new statement, from what they said or reported, is "
                            "`add_expectation`.")}
    parent, key, node = _locate(svc.doc, section)
    if node is None or parent is None:
        return {"applied": False, "said": "", "touched": [],
                "finding": f"The definition has no `{section}`. `read_section` with a top-level name lists what is there."}
    text = json.dumps(node, indent=1, ensure_ascii=False)
    new, why_not = _replace_once(text, find, replace, f"`{section}`")
    if new is None:
        return {"applied": False, "said": "", "touched": [], "finding": why_not}
    try:
        value = json.loads(new)
    except ValueError as exc:
        return {"applied": False, "said": "", "touched": [],
                "finding": f"`{section}` would no longer be valid JSON after that edit: {exc}."}
    before = svc.snapshot()
    parent[key] = value
    root = section.split(".")[0]
    natural = str((value.get("name") or value.get("id")) if isinstance(value, dict) else "")
    try:
        svc.validate()
        _check(root, svc.doc, value if isinstance(value, dict) else {root: value}, natural)
        if root == "workflows":
            # WRITTEN OUT BEFORE IT IS KEPT. A workflow the projection cannot
            # write stops EVERY workflow of the app being written (a guard
            # node twice did, 2026-10-07): tried in a scratch folder first.
            import tempfile
            from services.blueprint.projection import project_workflows
            with tempfile.TemporaryDirectory() as scratch:
                project_workflows(svc.doc, scratch)
        affected = [str(value.get("id"))] if isinstance(value, dict) and re.match(
            r"^[A-Z]+-\d{3,}$", str(value.get("id") or "")) else []
        svc.commit(user_request=why or f"Edit {section}", smith_interpretation=f"Edited {section}",
                   before=before, affected=affected)
    except Exception as exc:  # noqa: BLE001 — the contract's words go back to the loop
        svc.doc = before
        return {"applied": False, "said": "", "touched": [],
                "finding": f"`{section}` was not changed — the definition refuses it: {exc}"}
    out = sync(svc, str(Path(output_dir) / "app"))
    moved = out["changed"] + out["added"] + out["removed"]
    return {"applied": True, "said": f"Changed {section}" + (f": {' '.join(str(why).split())}" if why else "") + ".",
            "finding": "", "touched": [f"app/{m}" for m in moved] or [f"definition:{section}"]}


__all__ = ["classify", "edit_definition", "edit_file", "load_patches", "open_patches", "platform_text",
           "reapply", "settle"]
