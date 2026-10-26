"""A section drawn twice on a screen written in parts, drawn once.

A large screen is written as a frame (`view.tsx`) and one file per part (`parts/<key>.tsx`), cut along the planner's sections
(`screen_parts`). Every section belongs to ONE of them: a panel or a dialog to the part it opens from. The writers do not see each
other's files, so the frame drew "Quick Actions" in its side column while the Members summary part drew the same panel, and the
dashboard showed it twice (FitTrackr, 2026-10-26).

This finds a section's heading in a file that does not own that section and takes away the box around it. No model call: the owner is
decided by the cut, the box is the heading's own parent element, and the change is made with the editor's own adapter, which reads
and writes the code as a tree, so a bad cut cannot leave broken code. Anything this is not sure of it leaves alone:

  * only headings (h2 to h6) are read, never the page's own title (h1), and only a heading whose words are exactly a section's label;
  * the box must start with the heading and hold more than it, and must not hold another section's heading or place a part;
  * a label two parts both own is no one's trespass;
  * a screen that is not written in parts is not touched.

A button, a link or any other repeated word is never looked at: "Add Member" in the header and in a panel is on purpose."""
from __future__ import annotations

import logging
from pathlib import Path


logger = logging.getLogger(__name__)

_HEADINGS = ("h2", "h3", "h4", "h5", "h6")


def _owners(doc: dict, page: dict) -> dict[str, str]:
    """`{section label as words: the key of the part that draws it}`, for every label one part alone owns."""
    from services.blueprint.screen_parts import _norm, screen_parts

    owner: dict[str, str] = {}
    shared: set[str] = set()
    for part in screen_parts(doc, page):
        for section in part["sections"]:
            label = _norm(section.get("label") or section.get("key"))
            if not label:
                continue
            if label in owner and owner[label] != part["key"]:
                shared.add(label)
            owner[label] = part["key"]
    return {label: key for label, key in owner.items() if label not in shared}


def _descendants(nodes: dict[str, dict], node_id: str) -> list[dict]:
    out: list[dict] = []
    stack = list(nodes[node_id].get("children") or [])
    while stack:
        child = nodes.get(stack.pop())
        if child is None:
            continue
        out.append(child)
        stack.extend(child.get("children") or [])
    return out


def _boxes_to_drop(code: str, here: str, owner: dict[str, str], *, app_root: Path | None) -> tuple[list[str], list[str]]:
    """The element ids to take out of one file, and the section labels they drew."""
    from services.blueprint.screen_parts import _norm
    from services.react_editor import adapter

    try:
        nodes = adapter.model(code, app_root=app_root)["nodes"]
    except adapter.AdapterError:
        return [], []
    labels_here = {n["id"]: _norm(n.get("text")) for n in nodes.values() if n.get("type") in _HEADINGS and n.get("text")}
    ids: list[str] = []
    said: list[str] = []
    for node_id, label in labels_here.items():
        if label not in owner or owner[label] == here:
            continue
        box = nodes.get(nodes[node_id].get("parent") or "")
        if box is None or not box.get("parent") or (box.get("children") or [None])[0] != node_id or len(box["children"]) < 2:
            continue
        inside = _descendants(nodes, box["id"])
        if any(n.get("id") != node_id and labels_here.get(n.get("id")) in owner for n in inside):
            continue                                        # it holds another section too: not one section's box
        if any(str(n.get("type") or "").endswith("Part") for n in inside):
            continue                                        # it places parts: it is the frame's own layout
        ids.append(box["id"])
        said.append(label)
    # A box inside another box that goes is already gone with it.
    gone = set(ids)
    keep = [i for i in ids if not any(i != j and i.startswith(j + ".") for j in gone)]
    return keep, [said[ids.index(i)] for i in keep]


def drop_repeated_sections(doc: dict, page: dict, view: str, parts: dict[str, str], *,
                           app_root: Path | None = None) -> tuple[str, dict[str, str], list[str]]:
    """The frame and the parts with each section drawn only by its owner, and a line for every box taken out."""
    from services.react_editor import adapter

    owner = _owners(doc, page)
    if not owner:
        return view, parts, []
    files = {"frame": view, **parts}
    notes: list[str] = []
    for name, code in list(files.items()):
        ids, labels = _boxes_to_drop(code, name, owner, app_root=app_root)
        if not ids:
            continue
        try:
            changed = adapter.patch(code, [{"op": "remove", "ids": ids}], app_root=app_root)
            adapter.model(changed, app_root=app_root)       # it must still be read as code
        except adapter.AdapterError as exc:
            logger.warning("[repeated_sections] %s: a repeated box could not be taken out (%s)", name, exc)
            continue
        files[name] = changed
        where = "view.tsx" if name == "frame" else f"parts/{name}.tsx"
        for label in labels:
            notes.append(f"{where} drew the \"{label}\" section, which parts/{owner[label]}.tsx draws: the copy was taken out.")
    return files.pop("frame"), files, notes


__all__ = ["drop_repeated_sections"]

