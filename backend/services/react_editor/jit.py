"""The JIT renderer — a page bundled on demand, so the canvas needs no dev server.

`static/react-jit.mjs` bundles with the app's own esbuild against the app's
own node_modules, compiles the app's Tailwind, and runs the page's `load()`
against a sample-data stand-in for `@/sdk/server` built from the Blueprint's
entities (PREVIEW-004, PREVIEW-008). Two artifacts, both cached under
`.forge/editor/jit/`:

* the VENDOR script — everything the app's pages import from node_modules,
  built once per app (`vendor()`), minified, keyed by its contents; the
  editor fetches it once and reuses it for every page;
* the PAGE script + stylesheet — the page's own code with vendor imports
  resolved to the shared script, and Tailwind over the page's files plus the
  vendor's pre-extracted class candidates, cached per page revision.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from services.blueprint.app_sdk import code_page_dir
from services.react_editor import adapter
from services.react_editor.service import EditorError, Project, _entity_refs, _live, _page, _row, load_blueprint

logger = logging.getLogger(__name__)

SCRIPT = Path(__file__).resolve().parents[2] / "static" / "react-jit.mjs"
SHIMS = Path(__file__).resolve().parents[2] / "static" / "jit-shims"


def _tooling_hash() -> str:
    """The shims and the script are part of what is rendered; a change to them is a new build."""
    h = hashlib.sha1()
    for f in sorted(SHIMS.glob("*")):
        h.update(f.read_bytes())
    h.update(SCRIPT.read_bytes())
    return h.hexdigest()[:12]


def _cache_key(page_id: str, revision: str, params: dict, search: dict, vendor_key: str, widgets: Any = None) -> str:
    h = hashlib.sha1()
    h.update(revision.encode())
    # A chart's definition is in the Blueprint, not the page's files.
    h.update(json.dumps(widgets or [], sort_keys=True, default=str).encode())
    h.update(vendor_key.encode())
    h.update(json.dumps([params, search], sort_keys=True).encode())
    h.update(_tooling_hash().encode())
    return f"{page_id}-{h.hexdigest()[:16]}"


def _run(project: Project, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    env = {**os.environ, "NODE_PATH": str(project.app_root / "node_modules")}
    try:
        proc = subprocess.run(["node", str(SCRIPT)], input=json.dumps(payload), capture_output=True, text=True,
                              timeout=timeout, cwd=str(project.app_root), env=env)
    except subprocess.TimeoutExpired as exc:
        raise EditorError(504, "jit-timeout", "Rendering the page took too long.") from exc
    try:
        result = json.loads((proc.stdout or "").strip() or "{}")
    except json.JSONDecodeError as exc:
        raise EditorError(500, "jit", "The page could not be rendered: " + (proc.stderr or "").strip()[-600:]) from exc
    if not result.get("ok"):
        err = result.get("error") or {}
        raise EditorError(422, "jit-build", _plain_build_error(str(err.get("message") or "")), detail=str(err.get("detail") or "")[:1500])
    return result


def _require_toolchain(project: Project) -> None:
    if not (project.app_root / "node_modules" / "esbuild").exists():
        raise EditorError(503, "no-toolchain", "The application is not installed on this machine yet, so its pages "
                                               "cannot be rendered here. Run the build once, then open the editor.")


def vendor(project: Project, *, fresh: bool = False, timeout: float = 180.0) -> dict[str, Any]:
    """The shared script every page of this app runs on — React, the library,
    the icons — built once and cached by what it contains. ``{key, js, specifiers,
    candidates, ms, cached}``; the page build reads the key and candidates."""
    svc = load_blueprint(project)
    doc = svc.doc
    # The coded pages whose files are in the tree — a page not projected yet
    # is discovered when it is first built, and bundles what it alone needs.
    pages = [{"pageDir": code_page_dir(p)} for p in _live(doc.get("pages"))
             if any(str(r.get("page")) == str(p.get("id")) for r in _live(doc.get("pageCode")))
             and (project.app_root / code_page_dir(p) / "view.tsx").is_file()
             and (project.app_root / code_page_dir(p) / "load.ts").is_file()]
    cache_dir = project.editor_dir / "jit"
    # The current vendor is named by a pointer file, so a page build finds it
    # without rebuilding; the pointer carries what it was built from.
    pointer = cache_dir / "vendor-current.json"
    if pointer.exists() and not fresh:
        try:
            current = json.loads(pointer.read_text("utf-8"))
            same_pages = current.get("pages") == pages and current.get("tooling") == _tooling_hash()
            path = cache_dir / f"vendor-{current.get('key')}.json"
            if same_pages and path.exists():
                out = json.loads(path.read_text("utf-8"))
                out["cached"] = True
                return out
        except (json.JSONDecodeError, OSError):
            pass
    _require_toolchain(project)
    t0 = time.monotonic()
    result = _run(project, {"command": "vendor", "appRoot": str(project.app_root), "pages": pages, "shimsDir": str(SHIMS),
                            "entities": _entities_for_samples(doc),
                            "roles": [r.get("name") for r in _live(doc.get("roles")) if r.get("name")]}, timeout=timeout)
    out = {"key": result["key"], "js": result["js"], "specifiers": result["specifiers"], "candidates": result["candidates"],
           "ms": int((time.monotonic() - t0) * 1000), "timings": result.get("timings"), "cached": False}
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"vendor-{out['key']}.json").write_text(json.dumps(out), "utf-8")
    pointer.write_text(json.dumps({"key": out["key"], "pages": pages, "tooling": _tooling_hash()}), "utf-8")
    for old in cache_dir.glob("vendor-*.json"):
        if old.name not in (f"vendor-{out['key']}.json", "vendor-current.json"):
            old.unlink(missing_ok=True)
    return out


def build(project: Project, page_id: str, *, params: dict[str, str] | None = None,
          search: dict[str, str] | None = None, fresh: bool = False, timeout: float = 120.0) -> dict[str, Any]:
    """The page's bundle at its current revision: ``{js, css, revision, ms, cached}``."""
    svc = load_blueprint(project)
    doc = svc.doc
    page = _page(doc, page_id)
    row = _row(doc, page_id)
    if row is None:
        raise EditorError(409, "not-coded", "This page has no designed code to render yet.")
    view, load = str(row.get("view") or ""), str(row.get("load") or "")
    revision = adapter.revision_of(view, load)
    params, search = dict(params or {}), dict(search or {})
    shared = vendor(project, fresh=fresh)
    key = _cache_key(page_id, revision, params, search, shared["key"], _live(doc.get("widgets")))
    cache = project.editor_dir / "jit" / f"{key}.json"
    if cache.exists() and not fresh:
        try:
            out = json.loads(cache.read_text("utf-8"))
            out["cached"] = True
            return out
        except json.JSONDecodeError:
            pass
    _require_toolchain(project)
    # The app's copy of the page carries the ids the canvas selects by; make
    # sure it is current before bundling it.
    page_dir = code_page_dir(page)
    target = project.app_root / page_dir / "view.tsx"
    try:
        annotated = adapter.annotate(view, app_root=project.app_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.read_text() != annotated:
            target.write_text(annotated)
        load_path = project.app_root / page_dir / "load.ts"
        if not load_path.exists() or load_path.read_text() != load:
            load_path.write_text(load)
    except adapter.AdapterError as exc:
        raise EditorError(422, exc.code, str(exc))

    payload = {
        "command": "page",
        "appRoot": str(project.app_root), "pageId": page_id, "pageDir": page_dir,
        "route": page.get("route"), "access": page.get("access") or "authenticated",
        "entities": _entities_for_samples(doc), "roles": [r.get("name") for r in _live(doc.get("roles")) if r.get("name")],
        "params": params, "searchParams": search, "shimsDir": str(SHIMS),
        "vendor": {"specifiers": shared["specifiers"], "candidates": shared["candidates"]},
    }
    t0 = time.monotonic()
    result = _run(project, payload, timeout=timeout)
    out = {"js": result["js"], "css": result["css"], "revision": revision, "vendorKey": shared["key"],
           "ms": int((time.monotonic() - t0) * 1000), "timings": result.get("timings"),
           "warnings": result.get("warnings") or [], "inputs": result.get("inputs"), "cached": False, "data": "sample"}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out), "utf-8")
    # Keep the cache small: the newest few builds per page.
    builds = sorted(cache.parent.glob(f"{page_id}-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in builds[5:]:
        old.unlink(missing_ok=True)
    return out


def _entities_for_samples(doc: dict) -> list[dict]:
    from services.react_editor.service import _entities_for_samples as shared
    return shared(doc)


def _plain_build_error(message: str) -> str:
    if "Could not resolve" in message:
        return "The page refers to something the application does not include: " + message.split("Could not resolve", 1)[1].strip()[:200]
    if "Unexpected" in message or "Expected" in message:
        return "The page's code could not be read: " + message[:200]
    return "The page could not be rendered: " + message[:300]
