"""Open, edit and restore a coded page — the document engine of the editor.

A page is opened at a revision (the hash of its two sources). A transaction
names the revision it was made against; one made against an older revision is
refused with the current one, never merged silently (SYS-001). The change is
applied by the source adapter, checked by the compiler unless it is a kind of
change that cannot break a type (text, classes), and only then written — as a
new `pageCode` row through the Blueprint, which versions it, and as the page's
files under the app, which the dev server picks up. Every accepted revision is
kept in the page's own history with its sources, so "restore the last working
version" is a lookup, not a rebuild.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.blueprint.agent_contract import AgentResult, ArtifactProposal, apply_agent_result
from services.blueprint.app_sdk import code_page_dir, page_keys, project_code_pages, workflow_keys
from services.blueprint.service import BlueprintService
from services.react_editor import adapter, diagnostics
from services.react_editor.adapter import AdapterError, revision_of
from services.react_editor.registry import registry

logger = logging.getLogger(__name__)

#: Operations that cannot change a type: the compiler is not asked.
_TYPE_SAFE_OPS = frozenset({"setText", "setClasses"})

#: One lock per project directory — two applies to the same page serialise
#: here, so the revision check is decisive rather than racy.
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock(root: Path) -> threading.RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(root), threading.RLock())


class EditorError(Exception):
    """A refusal the router turns into an HTTP status; ``detail`` is for the person."""

    def __init__(self, status: int, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.status = status
        self.code = code
        self.extra = extra

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), **self.extra}


@dataclass(frozen=True)
class Project:
    root: Path
    app_root: Path

    @property
    def editor_dir(self) -> Path:
        return self.root / ".forge" / "editor"


def locate(output_dir: str | Path) -> Project:
    root = Path(output_dir)
    for candidate in (root / "app", root):
        if (candidate / "package.json").is_file():
            return Project(root=root, app_root=candidate)
    return Project(root=root, app_root=root / "app")


def load_blueprint(project: Project) -> BlueprintService:
    try:
        return BlueprintService.load(output_dir=project.root)
    except FileNotFoundError as exc:
        raise EditorError(404, "no-blueprint", "This project has no application to edit yet — build it first.") from exc


def _live(rows: Any) -> list[dict]:
    return [r for r in (rows or []) if isinstance(r, dict) and r.get("status") != "DEPRECATED"]


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def pages(doc: dict) -> dict[str, Any]:
    coded = {str(r.get("page")) for r in _live(doc.get("pageCode"))}
    nav = doc.get("navigation") or {}
    entry = str(nav.get("initialPage") or nav.get("entryPage") or "")
    out = []
    for p in _live(doc.get("pages")):
        pid = str(p.get("id"))
        out.append({
            "id": pid, "name": p.get("name"), "route": p.get("route"),
            "purpose": p.get("purpose") or "", "pattern": p.get("pattern"),
            "access": p.get("access") or "authenticated",
            "coded": pid in coded,
            "module": p.get("module"),
            "navigatesTo": [str(x) for x in (p.get("navigatesTo") or [])],
        })
    if not entry:
        initial = nav.get("initialRoute")
        route = initial.get("default") if isinstance(initial, dict) else initial
        entry = next((p["id"] for p in out if route and p["route"] == route), "")
    if not entry:
        entry = next((p["id"] for p in out if p["route"] == "/"), out[0]["id"] if out else "")
    from services.react_editor.pages import navigation
    return {"entryPage": entry, "pages": out, "navigation": navigation(doc)}


def _page(doc: dict, page_id: str) -> dict:
    for p in _live(doc.get("pages")):
        if str(p.get("id")) == page_id:
            return p
    raise EditorError(404, "no-page", "That page is not part of this application any more.")


def _row(doc: dict, page_id: str) -> dict | None:
    return next((r for r in _live(doc.get("pageCode")) if str(r.get("page")) == page_id), None)


def _page_refs(doc: dict) -> list[dict]:
    keys = page_keys(doc)
    return [{"id": str(p.get("id")), "key": keys.get(str(p.get("id"))), "name": p.get("name"),
             "route": p.get("route"), "params": _route_params(str(p.get("route") or ""))}
            for p in _live(doc.get("pages"))]


def _route_params(route: str) -> list[str]:
    import re
    return re.findall(r"\[([^\]]+)\]", route)


def _workflow_refs(doc: dict) -> list[dict]:
    keys = workflow_keys(doc)
    ents = {str(e.get("id")): e for e in _live((doc.get("data") or {}).get("entities"))}
    out = []
    for w in _live(doc.get("workflows")):
        inputs = []
        for inp in w.get("inputs") or []:
            if not isinstance(inp, dict) or not inp.get("name"):
                continue
            ent = ents.get(str(inp.get("entity") or ""))
            inputs.append({"name": inp.get("name"), "kind": inp.get("kind") or "field",
                           "type": inp.get("type") or ("string" if inp.get("kind") == "record" else "string"),
                           "required": bool(inp.get("required", True)),
                           "description": inp.get("description") or "",
                           "entity": ent.get("name") if ent else None,
                           "options": list(inp.get("enumValues") or inp.get("options") or [])})
        out.append({"id": str(w.get("id")), "key": keys.get(str(w.get("id"))), "name": w.get("name"),
                    "description": w.get("description") or "", "inputs": inputs,
                    "launchedFrom": [str(x) for x in (w.get("launchedFrom") or [])]})
    return out


def _entity_refs(doc: dict) -> list[dict]:
    from services.blueprint.app_sdk import pascal
    out = []
    for e in _live((doc.get("data") or {}).get("entities")):
        fields = [{"name": f.get("name"), "type": f.get("type") or "string", "required": bool(f.get("required")),
                   "label": f.get("label") or _humanise(str(f.get("name") or "")),
                   "options": list(f.get("enumValues") or [])}
                  for f in (e.get("fields") or []) if isinstance(f, dict) and f.get("name")]
        out.append({"id": str(e.get("id")), "name": e.get("name"), "typeName": pascal(str(e.get("name") or e.get("id"))),
                    "table": e.get("table"), "fields": fields})
    return out


def _entities_for_samples(doc: dict) -> list[dict]:
    return [{"name": e["name"], "fields": [{"name": f["name"], "type": f["type"], "enumValues": f["options"]} for f in e["fields"]]}
            for e in _entity_refs(doc)]


def _widget_refs(doc: dict) -> list[dict]:
    from services.react_editor.widgets import refs
    return refs(doc)


def _humanise(name: str) -> str:
    import re
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", name.strip())
    spaced = re.sub(r"[_\-]+", " ", spaced)
    return " ".join(w[:1].upper() + w[1:] for w in spaced.split())


def _theme(doc: dict) -> dict:
    ds = doc.get("designSystem") or {}
    return {k: ds.get(k) for k in ("palette", "typography", "radius", "density", "register") if ds.get(k)}


# ---------------------------------------------------------------------------
# History — every accepted revision, with its sources
# ---------------------------------------------------------------------------

def _history_path(project: Project, page_id: str) -> Path:
    return project.editor_dir / "pages" / f"{page_id}.jsonl"


def history(project: Project, page_id: str, *, with_sources: bool = False) -> list[dict]:
    path = _history_path(project, page_id)
    if not path.exists():
        return []
    out = []
    for line in path.read_text("utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not with_sources:
            entry = {k: v for k, v in entry.items() if k not in ("view", "load")}
        out.append(entry)
    return out


def _record(project: Project, page_id: str, *, revision: str, parent: str | None, label: str,
            kind: str, view: str, load: str, version: int | None) -> dict:
    path = _history_path(project, page_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"revision": revision, "parent": parent, "label": label, "kind": kind,
             "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "version": version,
             "view": view, "load": load}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return {k: v for k, v in entry.items() if k not in ("view", "load")}


def _ensure_baseline(project: Project, page_id: str, view: str, load: str, version: int | None) -> None:
    rev = revision_of(view, load)
    if any(e.get("revision") == rev for e in history(project, page_id)):
        return
    _record(project, page_id, revision=rev, parent=None, label="Built by Forge", kind="baseline",
            view=view, load=load, version=version)


# ---------------------------------------------------------------------------
# Open
# ---------------------------------------------------------------------------

def _annotate_app_copy(project: Project, doc: dict, page: dict, view: str) -> None:
    """The running app's copy of view.tsx carries data-fid; the Blueprint's never does."""
    try:
        annotated = adapter.annotate(view, app_root=project.app_root)
    except AdapterError as exc:
        logger.warning("[react_editor] could not annotate %s: %s", page.get("id"), exc)
        return
    target = project.app_root / code_page_dir(page) / "view.tsx"
    if target.parent.is_dir() and (not target.exists() or target.read_text() != annotated):
        target.write_text(annotated)


def _state(svc: BlueprintService, project: Project, page_id: str) -> tuple[dict, dict | None, str, str, str]:
    doc = svc.doc
    page = _page(doc, page_id)
    row = _row(doc, page_id)
    view = str(row.get("view") or "") if row else ""
    load = str(row.get("load") or "") if row else ""
    return page, row, view, load, revision_of(view, load)


def open_page(project: Project, page_id: str, *, annotate: bool = True) -> dict[str, Any]:
    svc = load_blueprint(project)
    with _lock(project.root):
        page, row, view, load, revision = _state(svc, project, page_id)
        doc = svc.doc
        if row is None:
            return {"page": {"id": page_id, "name": page.get("name"), "route": page.get("route"),
                             "purpose": page.get("purpose") or ""},
                    "coded": False, "revision": revision, "model": None, "source": None,
                    "reason": "This page was laid out automatically and has no designed code yet. "
                              "Ask Smith to design it, then it can be edited here.",
                    "registry": registry(), "pages": _page_refs(doc), "workflows": _workflow_refs(doc),
                    "entities": _entity_refs(doc), "theme": _theme(doc), "history": []}
        _ensure_baseline(project, page_id, view, load, doc.get("version"))
        try:
            model = adapter.model(view, load, app_root=project.app_root)
        except AdapterError as exc:
            raise EditorError(422, exc.code, str(exc), line=exc.line)
        if annotate:
            _annotate_app_copy(project, doc, page, view)
        return {
            "page": {"id": page_id, "name": page.get("name"), "route": page.get("route"),
                     "purpose": page.get("purpose") or "", "access": page.get("access") or "authenticated",
                     "file": f"{code_page_dir(page)}/view.tsx"},
            "coded": True,
            "revision": revision,
            "model": model,
            "source": {"view": view, "load": load},
            "registry": registry(),
            "pages": _page_refs(doc),
            "workflows": _workflow_refs(doc),
            "entities": _entity_refs(doc),
            "widgets": _widget_refs(doc),
            "samples": adapter.samples(_entities_for_samples(doc), app_root=project.app_root),
            "theme": _theme(doc),
            "history": history(project, page_id)[-30:],
            "toolchain": {"typecheck": (project.app_root / "node_modules/.bin/tsc").exists()},
        }


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def _check(doc: dict, project: Project, page_id: str, view: str, load: str) -> list[dict]:
    """The compiler and the page rules, as findings. Raises when there is no compiler."""
    from services.blueprint.ui_engineer import _static_findings, typecheck
    raw = [f"view.tsx(1,1): error RULE: {m}" if not m.startswith(("view.tsx", "load.ts")) else m
           for m in _static_findings(load, view)]
    try:
        raw += typecheck(doc, project.app_root, page_id, load, view)
    except RuntimeError as exc:
        raise EditorError(503, "no-compiler",
                          "The application is not installed on this machine yet, so changes cannot be "
                          "checked before they are saved. Run the build once, then edit.") from exc
    return diagnostics.findings(raw)


def _write(svc: BlueprintService, project: Project, page: dict, row: dict, view: str, load: str,
           *, label: str) -> int | None:
    page_id = str(page.get("id"))
    body = {"page": page_id, "load": load, "view": view,
            "rationale": str(row.get("rationale") or ""),
            "requirements": list(row.get("requirements") or page.get("requirements") or [])}
    with svc.lock:
        apply_agent_result(svc, AgentResult(task_id=f"TASK-editor-{page_id}-{revision_of(view, load)}",
                                            agent="ui_engineer", confidence=1.0,
                                            proposals=[ArtifactProposal(section="pageCode", natural_key=page_id, body=body)]),
                           commit=True, user_request=label)
        project_code_pages(svc.doc, project.app_root)
    _annotate_app_copy(project, svc.doc, page, view)
    return svc.doc.get("version")


def apply(project: Project, page_id: str, *, base_revision: str, ops: list[dict[str, Any]],
          label: str = "Edit", kind: str = "edit", source: dict[str, str] | None = None,
          check: bool | None = None) -> dict[str, Any]:
    """One transaction: ops against `base_revision` (or a whole `source`), checked, written.

    Returns the new revision and model. Raises EditorError 409 when the page
    has moved on, 422 with findings when the result does not compile.
    """
    if not ops and source is None:
        raise EditorError(400, "empty", "Nothing to change.")
    svc = load_blueprint(project)
    with _lock(project.root):
        page, row, view, load, revision = _state(svc, project, page_id)
        if row is None:
            raise EditorError(409, "not-coded", "This page has no designed code to edit yet.")
        if base_revision != revision:
            raise EditorError(409, "stale", "The page changed since you last loaded it — your change was not "
                                            "applied. Reload to see the latest version and try again.",
                              current=revision)
        if source is not None:
            new_view, new_load = str(source.get("view", view)), str(source.get("load", load))
        else:
            # An op names its file; `load` ops extend what the page reads.
            view_ops = [o for o in ops if o.get("file") != "load"]
            load_ops = [{k: v for k, v in o.items() if k != "file"} for o in ops if o.get("file") == "load"]
            try:
                new_view = adapter.patch(view, view_ops, app_root=project.app_root) if view_ops else view
                new_load = adapter.patch_load(load, load_ops, app_root=project.app_root) if load_ops else load
            except AdapterError as exc:
                raise EditorError(422, exc.code, str(exc), line=exc.line)
        if new_view == view and new_load == load:
            model = adapter.model(view, load, app_root=project.app_root)
            return {"revision": revision, "model": model, "source": {"view": view, "load": load},
                    "checked": False, "unchanged": True, "version": svc.doc.get("version")}
        must_check = check if check is not None else not (
            source is None and all(op.get("op") in _TYPE_SAFE_OPS and op.get("file") != "load" for op in ops))
        found: list[dict] = []
        if must_check:
            found = _check(svc.doc, project, page_id, new_view, new_load)
            if found:
                raise EditorError(422, "does-not-compile",
                                  "That change would break the page, so it was not saved.", findings=found)
        version = _write(svc, project, page, row, new_view, new_load, label=label)
        new_rev = revision_of(new_view, new_load)
        entry = _record(project, page_id, revision=new_rev, parent=revision, label=label, kind=kind,
                        view=new_view, load=new_load, version=version)
        model = adapter.model(new_view, new_load, app_root=project.app_root)
        return {"revision": new_rev, "model": model, "source": {"view": new_view, "load": new_load},
                "checked": must_check, "unchanged": False, "version": version, "history": entry}


def restore(project: Project, page_id: str, *, revision: str, expected: str) -> dict[str, Any]:
    """Bring back a revision from the page's history — it compiled when it was
    recorded, so it is written without asking the compiler again."""
    entries = [e for e in history(project, page_id, with_sources=True) if e.get("revision") == revision]
    if not entries:
        raise EditorError(404, "no-revision", "That version is not in this page's history.")
    entry = entries[-1]
    return apply(project, page_id, base_revision=expected, ops=[],
                 source={"view": entry["view"], "load": entry["load"]},
                 label=f"Restored “{entry.get('label') or revision}”", kind="restore", check=False)


def check_page(project: Project, page_id: str) -> dict[str, Any]:
    """The compiler's view of the page as it is — for the readiness check."""
    svc = load_blueprint(project)
    page, row, view, load, revision = _state(svc, project, page_id)
    if row is None:
        return {"revision": revision, "findings": [], "checked": False}
    try:
        found = _check(svc.doc, project, page_id, view, load)
    except EditorError as exc:
        return {"revision": revision, "findings": [], "checked": False, "reason": str(exc)}
    return {"revision": revision, "findings": found, "checked": True}
