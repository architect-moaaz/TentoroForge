"""A coded page as the files it is made of — `view.tsx`, `load.ts` and, for a
large screen, its parts (`parts/<key>.tsx`, `pageCode.parts`).

The editor's model, its ops and its canvas ids were made for one view file:
an id is a path inside it (`r0.2.1`), so two files would collide. A part's
model is read on its own and its ids prefixed with the part's key
(`coupons:r0.2.1`), its tree hung under the frame element that renders it, so
the screen is one tree to select in; an op's ids say which file it edits, and
it is patched there. Its copy in the running app carries the same prefixed
ids, so a click on the canvas lands on the right file's element.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from services.react_editor import adapter
from services.react_editor.adapter import AdapterError

#: Between a part's key and an id inside it: `coupons:r0.2`.
SEP = ":"
#: Op fields that name elements.
_ID_FIELDS = ("id", "parentId", "afterId", "beforeId")


def parts_of(row: dict | None) -> dict[str, str]:
    return {str(k): str(v or "") for k, v in ((row or {}).get("parts") or {}).items() if v}


def _file_of_id(node_id: Any) -> str:
    text = str(node_id or "")
    return f"part:{text.split(SEP, 1)[0]}" if SEP in text else "view"


def _strip(node_id: Any) -> Any:
    return str(node_id).split(SEP, 1)[1] if SEP in str(node_id or "") else node_id


def split_ops(ops: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """`{"view" | "load" | "part:<key>": [ops]}` — each op with its ids made
    local to its file. An op with no id (an import) goes to the file the rest
    of the batch edits; `load` ops stay `load`. An op whose ids span two files
    is refused: an element cannot move between a screen's parts."""
    def file_of(op: dict) -> str | None:
        ids = [op.get(f) for f in _ID_FIELDS if op.get(f)] + list(op.get("ids") or [])
        files = {_file_of_id(i) for i in ids}
        if len(files) > 1:
            raise AdapterError("across-files", "That change spans two parts of the screen — move or copy "
                                               "elements within one part at a time.")
        return files.pop() if files else None

    batch = {f for f in (file_of(o) for o in ops if o.get("file") != "load") if f}
    if len(batch) > 1 and any(not file_of(o) and o.get("file") != "load" for o in ops):
        raise AdapterError("across-files", "That change spans two parts of the screen — make it one part at a time.")
    default = batch.pop() if len(batch) == 1 else "view"
    out: dict[str, list[dict[str, Any]]] = {}
    for op in ops:
        if op.get("file") == "load":
            out.setdefault("load", []).append({k: v for k, v in op.items() if k != "file"})
            continue
        target = file_of(op) or default
        local = {k: (_strip(v) if k in _ID_FIELDS else v) for k, v in op.items()}
        if op.get("ids"):
            local["ids"] = [_strip(i) for i in op["ids"]]
        out.setdefault(target, []).append(local)
    return out


def patch_all(view: str, load: str, parts: dict[str, str], ops: list[dict[str, Any]], *,
              app_root: Path | None = None) -> tuple[str, str, dict[str, str]]:
    """Every op applied to the file it edits."""
    parts = dict(parts)
    for target, file_ops in split_ops(ops).items():
        if target == "load":
            load = adapter.patch_load(load, file_ops, app_root=app_root)
        elif target == "view":
            view = adapter.patch(view, file_ops, app_root=app_root)
        else:
            key = target[5:]
            if key not in parts:
                raise AdapterError("missing-target", f"This screen has no part {key} any more.")
            parts[key] = adapter.patch(parts[key], file_ops, app_root=app_root)
    return view, load, parts


_PART_IMPORT = re.compile(r'import\s+(\w+)\s+from\s+["\']\./parts/([\w-]+)["\']')


def merged_model(view: str, load: str, parts: dict[str, str], *, app_root: Path | None = None) -> dict[str, Any]:
    """The screen's model: the frame's, with each part's tree under the frame
    element that renders it (or among the roots, when none does)."""
    model = adapter.model(view, load, app_root=app_root)
    for node in model["nodes"].values():
        node["file"] = "view"
    if not parts:
        return model
    host = {key: name for name, key in _PART_IMPORT.findall(view)}
    for key, code in parts.items():
        sub = adapter.model(code, "", app_root=app_root)
        prefix = f"{key}{SEP}"
        at = next((nid for nid, n in model["nodes"].items() if n.get("type") == host.get(key)), None)
        for nid, node in sub["nodes"].items():
            node = dict(node)
            node["id"] = prefix + nid
            node["parent"] = prefix + node["parent"] if node.get("parent") else at
            node["children"] = [prefix + c for c in node.get("children") or []]
            node["file"] = f"part:{key}"
            model["nodes"][prefix + nid] = node
        roots = [prefix + r["id"] for r in sub.get("roots") or []]
        if at is not None:
            model["nodes"][at]["children"] = list(model["nodes"][at].get("children") or []) + roots
        else:
            model["roots"] = list(model.get("roots") or []) + [{"id": r, "owner": None} for r in roots]
    return model


def annotate_part(key: str, code: str, *, app_root: Path | None = None) -> str:
    """A part's code with `data-fid` on every element, prefixed with its key."""
    annotated = adapter.annotate(code, app_root=app_root)
    return annotated.replace(' data-fid="', f' data-fid="{key}{SEP}')
