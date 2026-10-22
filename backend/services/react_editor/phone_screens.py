"""A phone screen opened, changed and restored in the Editor.

A phone screen is React Native code kept in the Blueprint (`nativeCode`, one row per page) and copied to
`native/src/screens/<PAGE>.tsx`. It is the same kind of file as a web page's view, so it is read, changed and kept by the same
engine: the source adapter (a real parser, so an edit lands at the element it names and nothing else moves), a revision that is
the hash of the content (a change made against an older one is refused, never merged), a history with the sources so any
version can be brought back, and a check before anything is saved.

The check is the phone's own compiler. A change of words cannot break a type, so it is not asked. Any other change is, and
when the compiler is not installed on this machine the change is refused and said so, never saved unchecked."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from services.blueprint.agent_contract import AgentResult, ArtifactProposal, apply_agent_result
from services.react_editor import adapter, diagnostics, phone
from services.react_editor import files as screen_files
from services.react_editor.adapter import AdapterError, revision_of
from services.react_editor.service import (EditorError, Project, _lock, _record, _ensure_baseline, _page, history,
                                           load_blueprint)

logger = logging.getLogger(__name__)

#: A prop that holds words a person reads. Changing one cannot break a type; every other prop is a choice the kit makes
#: (`variant`, `size`, ...) and is for the next step.
WORDS_PROPS = frozenset({"title", "label", "placeholder", "message", "subtitle", "description", "heading", "caption", "text",
                         "hint", "helper"})


def _native(project: Project) -> Path:
    from services.blueprint.native_projection import native_root
    return native_root(project.root)


def _hist(page_id: str) -> str:
    """The history's name for a phone screen: a page that is both a web page and a phone screen keeps two histories."""
    return f"phone-{page_id}"


def _row(doc: dict, page_id: str) -> dict | None:
    return next((r for r in doc.get("nativeCode") or []
                 if isinstance(r, dict) and r.get("status") != "DEPRECATED" and str(r.get("page")) == page_id), None)


def _state(svc: Any, page_id: str) -> tuple[dict, dict, str, dict[str, str], str]:
    page = _page(svc.doc, page_id)
    row = _row(svc.doc, page_id)
    if row is None or not row.get("screen"):
        raise EditorError(409, "not-coded", "This page has no phone screen to edit yet.")
    screen = str(row.get("screen") or "")
    parts = screen_files.parts_of(row)
    return page, row, screen, parts, revision_of(screen, "", parts)


#: What the picture needs of each part of the screen: not the character positions, which are the engine's business.
_KEEP = ("id", "parent", "children", "index", "type", "kind", "line", "endLine", "text", "textEditable", "selfClosing",
         "repeat", "condition", "file", "slot")


def _public(model: dict[str, Any]) -> dict[str, Any]:
    nodes = {}
    for nid, n in (model.get("nodes") or {}).items():
        slim = {k: n.get(k) for k in _KEEP if k in n}
        slim["props"] = [{"name": p.get("name"), "kind": p.get("kind"), "value": p.get("value")}
                         for p in n.get("props") or [] if p.get("kind") != "spread"]
        nodes[nid] = slim
    return {"roots": model.get("roots") or [], "nodes": nodes}


def open_screen(project: Project, page_id: str) -> dict[str, Any]:
    svc = load_blueprint(project)
    if not phone.enabled(svc.doc):
        raise EditorError(404, "no-phone", "This application has no phone app.")
    page, row, screen, parts, revision = _state(svc, page_id)
    try:
        model = screen_files.merged_model(screen, "", parts, app_root=_native(project), slots=True)
    except AdapterError as exc:
        raise EditorError(422, exc.code, str(exc), line=exc.line)
    _ensure_baseline(project, _hist(page_id), screen, "", svc.doc.get("version"), parts or None)
    return {"page": {"id": page_id, "name": page.get("name"), "route": page.get("route")},
            "revision": revision, "model": _public(model), "words": sorted(WORDS_PROPS),
            "history": history(project, _hist(page_id))}


def _safe_without_compiler(op: dict[str, Any]) -> bool:
    """A change that cannot break a type: words, or taking a part away or copying one."""
    if op.get("file") == "load":
        return False
    kind = op.get("op")
    if kind in ("setText", "remove", "duplicate"):
        return True
    value = op.get("value") or {}
    return kind == "setProp" and op.get("name") in WORDS_PROPS and value.get("kind") == "string"


def _compile(doc: dict, project: Project, page_id: str, screen: str) -> list[dict]:
    """The phone's compiler's findings on a screen. Raises when there is no compiler, which is never installed from here."""
    from services.blueprint import native_engineer
    tool = native_engineer.toolchain_dir()
    if not (tool / "node_modules" / "typescript" / "bin" / "tsc").is_file():
        raise EditorError(503, "no-compiler", "The phone's checker is not installed on this machine yet, so this kind of "
                                              "change cannot be checked before it is saved. Changing words works without it.")
    errors = native_engineer.typecheck(doc, _native(project), page_id, screen, toolchain=tool)
    if errors is None:
        raise EditorError(503, "no-compiler", "The phone's checker could not run, so this change was not saved.")
    return diagnostics.findings(errors)


def _write(svc: Any, project: Project, row: dict, page_id: str, screen: str, parts: dict[str, str], label: str) -> int | None:
    body = {"page": page_id, "screen": screen, "parts": parts,
            "rationale": str(row.get("rationale") or ""), "requirements": list(row.get("requirements") or [])}
    with svc.lock:
        apply_agent_result(svc, AgentResult(task_id=f"TASK-editor-phone-{page_id}-{revision_of(screen, '', parts)}",
                                            agent="native_engineer", confidence=1.0,
                                            proposals=[ArtifactProposal(section="nativeCode", natural_key=page_id, body=body)]),
                           commit=True, user_request=label)
        phone.reproject(svc.doc, project.root)
    return svc.doc.get("version")


def apply(project: Project, page_id: str, *, base_revision: str, ops: list[dict[str, Any]],
          label: str = "Edit", kind: str = "edit", source: dict[str, Any] | None = None,
          check: bool | None = None) -> dict[str, Any]:
    """One transaction against `base_revision`: the ops are applied, the result checked, and only then saved.

    Raises EditorError 409 when the screen moved on, 422 when the result does not parse or compile, 503 when a change
    that needs the compiler has none."""
    if not ops and source is None:
        raise EditorError(400, "empty", "Nothing to change.")
    svc = load_blueprint(project)
    with _lock(project.root):
        page, row, screen, parts, revision = _state(svc, page_id)
        if base_revision != revision:
            raise EditorError(409, "stale", "The screen changed since you last loaded it — your change was not applied. "
                                            "Reload to see the latest version and try again.", current=revision)
        native = _native(project)
        try:
            if source is not None:
                new_screen = str(source.get("screen", screen))
                new_parts = {**parts, **{str(k): str(v) for k, v in (source.get("parts") or {}).items()}}
            else:
                new_screen, _, new_parts = screen_files.patch_all(screen, "", parts, list(ops), app_root=native, slots=True)
            model = screen_files.merged_model(new_screen, "", new_parts, app_root=native, slots=True)     # it must still parse
        except AdapterError as exc:
            raise EditorError(422, exc.code, str(exc), line=exc.line)
        if new_screen == screen and new_parts == parts:
            return {"revision": revision, "model": _public(model), "checked": False, "unchanged": True,
                    "version": svc.doc.get("version")}
        must_check = check if check is not None else not (source is None and all(_safe_without_compiler(o) for o in ops))
        if must_check:
            found = _compile(svc.doc, project, page_id, new_screen)
            if found:
                raise EditorError(422, "does-not-compile", "That change would break the screen, so it was not saved.",
                                  findings=found)
        version = _write(svc, project, row, page_id, new_screen, new_parts, label)
        new_rev = revision_of(new_screen, "", new_parts)
        entry = _record(project, _hist(page_id), revision=new_rev, parent=revision, label=label, kind=kind,
                        view=new_screen, load="", version=version, parts=new_parts or None)
        return {"revision": new_rev, "model": _public(model), "checked": must_check, "unchanged": False,
                "version": version, "history": entry}


def restore(project: Project, page_id: str, *, revision: str, expected: str) -> dict[str, Any]:
    """Bring a revision back from the screen's history. It was valid when it was kept, so it is not checked again."""
    entries = [e for e in history(project, _hist(page_id), with_sources=True) if e.get("revision") == revision]
    if not entries:
        raise EditorError(404, "no-revision", "That version is not in this screen's history.")
    entry = entries[-1]
    return apply(project, page_id, base_revision=expected, ops=[],
                 source={"screen": entry["view"], **({"parts": entry["parts"]} if entry.get("parts") else {})},
                 label=f"Restored “{entry.get('label') or revision}”", kind="restore", check=False)
