"""What a design's screens share is the application's chrome, not a page's.

THE DEFINITION THIS RESTS ON. A designer draws every screen whole: sidebar,
brand, page. The sidebar is the same drawing on every frame — on a real
15-screen file its subtree had exactly one fingerprint across all 15 pages,
while the top bar (a breadcrumb) had eleven. So chrome is not a guess about
widths or colours or the word "nav" in a layer name (this file had no layer
names at all). Chrome is the part of every screen that is identical on every
screen. That is a definition, and a definition can be tested.

WHY IT MUST BE SPLIT. Composing a frame whole made every page carry its own
sidebar, so the application rendered two: the scaffold's generic one from
`navigation.tree`, and the design's, inside the content area. Navigating to
`/cases/new` — a route the scaffold opens as a modal — put a third copy of the
rail inside a dialog. The design's sidebar was there on every page and was
never once the application's.

WHAT COMES OUT. Two things, from the same subtree:

  * the page WITHOUT its chrome — `split` — so the shell can wrap content that
    is only content; and
  * what the chrome SAYS — `navigation_from` — the groups and destinations the
    designer drew, recorded on the design source as evidence for the one agent
    that authors `navigation.tree` (§48: the design decides what exists, the
    application decides how it is reached).

A design with one screen has nothing to compare and therefore no chrome; it
composes exactly as before. So does one whose screens share nothing.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Iterable

#: How many screens a subtree must appear on, as a fraction, to be chrome. A
#: majority and not all: a design usually has one or two screens drawn without
#: the rail — a sign-in, a printable report — and they must not veto it.
SHARE = 0.6

#: A shared subtree with fewer labelled descendants than this is a logo or a
#: divider, not chrome. Chrome carries destinations.
MIN_LABELS = 3

#: How deep below the root a chrome subtree may sit. Dev Mode wraps a frame in
#: a stack or two before the row that holds [rail, page]; deeper than this and
#: a shared subtree is a shared widget inside the page, not the frame's rail.
MAX_DEPTH = 4

_ACTIONS = ("navigate", "workflow", "submit", "opensDialog", "onClick")

#: Leading icon glyphs Dev Mode bakes into a label — `⬡Dashboard`, `+New Case`.
_GLYPH = re.compile(r"^[^\w(]+", re.UNICODE)


# --------------------------------------------------------------------------
# fingerprints
# --------------------------------------------------------------------------

def _labels(node: Any, out: list[str]) -> list[str]:
    if isinstance(node, dict):
        props = node.get("props") or {}
        text = props.get("label") or props.get("content") or props.get("text")
        if isinstance(text, str) and text.strip():
            out.append(text.strip())
        for child in node.get("children") or []:
            _labels(child, out)
    return out


def fingerprint(node: dict) -> str:
    """What a subtree IS, independent of the ids the transform stamps on it.

    Type plus the ordered text it carries. Class names are excluded on
    purpose: two exports of the same rail differ in a `w-[239.5px]` here and
    there, and the words on it are what make it the same rail.
    """
    return hashlib.sha1(
        json.dumps([node.get("type"), _labels(node, [])]).encode("utf-8")
    ).hexdigest()[:12]


def _candidates(root: dict) -> list[tuple[str, dict]]:
    """Every subtree within MAX_DEPTH of the root, excluding the root itself.

    The root is a whole screen and a whole screen is never chrome.
    """
    out: list[tuple[str, dict]] = []

    def walk(node: dict, depth: int) -> None:
        for child in node.get("children") or []:
            if not isinstance(child, dict):
                continue
            out.append((fingerprint(child), child))
            if depth + 1 < MAX_DEPTH:
                walk(child, depth + 1)

    walk(root, 0)
    return out


def shared_chrome(roots: Iterable[dict]) -> set[str]:
    """Fingerprints of the subtrees that most screens share.

    Counted once per screen — a rail that appears twice on one frame (an
    export artefact) still counts as one screen — and kept only when it is
    labelled enough to be carrying destinations rather than decoration.
    """
    roots = [r for r in roots if isinstance(r, dict)]
    if len(roots) < 2:
        return set()
    needed = max(2, math.ceil(len(roots) * SHARE))

    seen_on: dict[str, int] = {}
    labelled: dict[str, int] = {}
    for root in roots:
        this_screen: set[str] = set()
        for fp, node in _candidates(root):
            if fp in this_screen:
                continue
            this_screen.add(fp)
            seen_on[fp] = seen_on.get(fp, 0) + 1
            labelled.setdefault(fp, len(_labels(node, [])))

    return {fp for fp, n in seen_on.items()
            if n >= needed and labelled.get(fp, 0) >= MIN_LABELS}


def lone_chrome(root: dict) -> set[str]:
    """The rail of a design that has only one screen.

    `shared_chrome` reads a rail as what MOST screens share; a single frame
    shares nothing with itself, so its rail composed as page content and the
    application rendered two navigations — the shell's beside the drawing's.
    On one screen the rail is the column of the first row that carries the
    most labels while being narrower than the content beside it: a design
    draws its destinations down the side, its content across the rest.
    """
    if not isinstance(root, dict):
        return set()
    first = next((c for c in root.get("children") or [] if isinstance(c, dict)), None)
    columns = [c for c in (first or {}).get("children") or [] if isinstance(c, dict)]
    if len(columns) < 2:
        return set()

    def width(node: dict) -> float:
        cls = str((node.get("props") or {}).get("className") or "")
        for pat in (r"flex-\[(\d+(?:\.\d+)?)_0_0\]", r"max-w-\[(\d+(?:\.\d+)?)px\]", r"\bw-\[(\d+(?:\.\d+)?)px\]"):
            m = re.search(pat, cls)
            if m:
                return float(m.group(1))
        return 0.0

    widest = max(columns, key=width)
    rails = [c for c in columns if c is not widest and len(_labels(c, [])) >= MIN_LABELS
             and (width(c) == 0.0 or width(c) < width(widest))]
    if not rails:
        return set()
    rail = max(rails, key=lambda c: len(_labels(c, [])))
    return {fingerprint(rail)}


def chrome_for(roots: Iterable[dict]) -> set[str]:
    """What the screens share when there are several; the lone rail when
    there is one."""
    roots = [r for r in roots if isinstance(r, dict)]
    if len(roots) >= 2:
        return shared_chrome(roots)
    return lone_chrome(roots[0]) if roots else set()


# --------------------------------------------------------------------------
# splitting
# --------------------------------------------------------------------------

def split(root: dict, chrome: set[str]) -> tuple[dict, list[dict]]:
    """The page without its chrome, and the chrome that was removed.

    Removes every subtree whose fingerprint is chrome, then unwraps the
    single-child wrappers Dev Mode leaves behind — a frame is `Stack > Stack >
    Row > [rail, page]`, and with the rail gone that is three boxes around one
    page. The shell has its own box; the page should not arrive in three.

    A CHROME SUBTREE CONTAINING THE WHOLE PAGE IS NOT REMOVED. If the shared
    fingerprint somehow matched a wrapper that also holds the content, removing
    it would remove the page. The outermost match wins only when something is
    left afterwards; otherwise the tree is returned untouched, which is the
    page as it rendered before this existed.
    """
    if not chrome or not isinstance(root, dict):
        return root, []

    removed: list[dict] = []

    def prune(node: dict) -> dict:
        kept = []
        for child in node.get("children") or []:
            if isinstance(child, dict) and fingerprint(child) in chrome:
                removed.append(child)
                continue
            kept.append(prune(child) if isinstance(child, dict) else child)
        node = dict(node)
        node["children"] = kept
        return node

    pruned = prune(root)
    if not _labels(pruned, []) and _labels(root, []):
        # Everything that said anything was inside what we removed.
        return root, []

    return _unwrap(pruned), removed


def _unwrap(node: dict) -> dict:
    """Collapse `Stack > Stack > Row > X` to `X` while each level has one child.

    The frame's own background colour is kept: it is copied onto the first
    node that has more than one child (or the leaf), so a page drawn on cream
    still renders on cream inside a white shell.
    """
    background = ""
    cur = node
    while isinstance(cur, dict):
        kids = [c for c in (cur.get("children") or []) if isinstance(c, dict)]
        cn = str((cur.get("props") or {}).get("className") or "")
        bg = next((t for t in cn.split() if t.startswith("bg-")), "")
        if bg and not background:
            background = bg
        if len(kids) != 1 or cur.get("type") not in ("Stack", "Row", "Container"):
            break
        cur = kids[0]
    if cur is node or not isinstance(cur, dict):
        return node
    cur = dict(cur)
    props = dict(cur.get("props") or {})
    cn = str(props.get("className") or "")
    if background and not any(t.startswith("bg-") for t in cn.split()):
        props["className"] = (background + " " + cn).strip()
    # The content region fills the shell's content area; a fixed width or
    # height from the frame would leave a strip of nothing beside it.
    props["className"] = " ".join(
        t for t in str(props.get("className") or "").split()
        if not re.match(r"^(w|h|min-h|max-h|max-w)-\[\d", t) and t not in ("shrink-0", "w-full")
    ) or None
    if props.get("className") is None:
        props.pop("className", None)
    cur["props"] = props
    return cur


# --------------------------------------------------------------------------
# what the chrome says
# --------------------------------------------------------------------------

def _clean(label: str) -> str:
    return _GLYPH.sub("", label).strip()


def navigation_from(chrome_nodes: Iterable[dict]) -> dict:
    """The groups and destinations a rail draws, in the order it draws them.

    Read in document order, which is the order the designer chose. A short
    label with no action that precedes items is a group heading — OVERVIEW,
    CASES, APPROVALS. A label with an action is a destination; so is one that
    LOOKS like a destination (an item under a heading, carrying a glyph) but
    whose action could not be bound, because the binding is the application's
    problem and the drawing's intent is not in doubt.

    The first one or two unactioned labels before any heading are the brand,
    which is not navigation and is returned separately.
    """
    entries: list[tuple[str, dict]] = []   # (label, props) in document order

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        props = node.get("props") or {}
        text = props.get("label") or props.get("content") or props.get("text")
        if isinstance(text, str) and text.strip():
            entries.append((text.strip(), props))
        for child in node.get("children") or []:
            walk(child)

    for node in chrome_nodes:
        walk(node)

    # A HEADING IS A LABEL THAT INTRODUCES ITEMS; THE BRAND IS WHAT COMES
    # BEFORE THE FIRST HEADING. Decided by what follows, not by counting: the
    # first rule here took "up to two unactioned labels" as brand, which was
    # right for a two-line brand (Criterion / Case Management) and wrong for a
    # one-line one, where it swallowed the first heading and left its group
    # unlabelled.
    def _is_item(idx: int) -> bool:
        raw, props = entries[idx]
        return bool(_clean(raw)) and (
            any(props.get(k) for k in _ACTIONS) or bool(_GLYPH.match(raw)))

    heading_at = {i for i, (raw, props) in enumerate(entries)
                  if _clean(raw) and not _is_item(i)
                  and i + 1 < len(entries) and _is_item(i + 1)}

    brand: list[str] = []
    groups: list[dict] = []
    current: dict | None = None

    for i, (raw, props) in enumerate(entries):
        label = _clean(raw)
        if not label:
            continue
        if _is_item(i):
            action = {k: props[k] for k in _ACTIONS if props.get(k)}
            if current is None:
                current = {"label": "", "items": []}
                groups.append(current)
            current["items"].append({"label": label, **action})
        elif i in heading_at:
            current = {"label": label, "items": []}
            groups.append(current)
        elif current is None and not groups and len(label) < 40:
            brand.append(label)
        # Any other unactioned label — a footer, a version string — is noise.

    groups = [g for g in groups if g["items"]]
    return {"brand": brand, "groups": groups}


def _icon_px(node: dict, inherited: float = 0.0) -> float:
    """The size of the first image in a subtree; a `size-full` image takes
    the size of the box that holds it (a flag emblem drawn as vectors)."""
    def px(n: dict) -> float:
        cls = str((n.get("props") or {}).get("className") or "")
        m = re.search(r"\b(?:size|w|h)-\[(\d+(?:\.\d+)?)px\]", cls)
        return float(m.group(1)) if m else 0.0
    for child in node.get("children") or []:
        if not isinstance(child, dict):
            continue
        if child.get("type") in ("Image", "Icon"):
            return px(child) or inherited
        found = _icon_px(child, px(child) or inherited)
        if found:
            return found
    return 0.0


def _carries_text(node: Any) -> bool:
    return isinstance(node, dict) and bool(_labels(node, []))


def rail_as_drawn(chrome_nodes: Iterable[dict]) -> list[dict]:
    """The rail entry by entry, in document order, as the designer drew it.

    NO DECISIONS HERE. An entry is a structural unit — a child of any
    container whose children each carry text (a list), or the container
    itself when nothing under it forms a list — and it records what it
    carries: its labels together, the size of its icon, whether it is filled,
    and any action the transform bound. Which entry is the brand, which the
    status card, which a heading and which a destination is the architect's
    reading, made from this. The first version of this module decided those
    with numbers — a brand's icon is 32px or more, a status card is a filled
    block of two labels, an item has at most three — each tuned on one file,
    which is how an exception list begins.
    """
    def entry(node: dict) -> dict:
        props = node.get("props") or {}
        cls = str(props.get("className") or "")
        out: dict = {"labels": _labels(node, [])}
        icon = _icon_px(node)
        if icon:
            out["icon"] = icon
        if any(t.startswith("bg-") and t not in ("bg-transparent", "bg-none") for t in cls.split()):
            out["filled"] = True
        for k in _ACTIONS:
            if props.get(k):
                out[k] = props[k]
        # An action bound on a descendant is the entry's action.
        if not any(k in out for k in _ACTIONS):
            def find(n):
                if isinstance(n, dict):
                    p = n.get("props") or {}
                    for k in _ACTIONS:
                        if p.get(k):
                            return {k: p[k]}
                    for c in n.get("children") or []:
                        r = find(c)
                        if r:
                            return r
                return None
            bound = find(node)
            if bound:
                out.update(bound)
        nested = lists_in(node)
        # Only a list of BLOCKS nests — members that carry an icon, a fill or
        # an action of their own. A list of plain text lines is the entry's
        # own lines, already in `labels`.
        if nested and any(e.get("icon") or e.get("filled") or any(k in e for k in _ACTIONS) for e in nested):
            out["children"] = nested
        return out

    def _leaf(n: dict) -> bool:
        return n.get("type") in ("Text", "Heading") and not n.get("children")

    def lists_in(node: dict) -> list[dict]:
        """Entries of the lists inside a node, in document order. A run of
        leaf texts is not a list: those are one entry's own lines."""
        kids = [c for c in node.get("children") or [] if isinstance(c, dict)]
        texty = [c for c in kids if _carries_text(c)]
        if len(texty) >= 2 and not all(_leaf(c) for c in texty):
            return [entry(c) for c in texty]
        out: list[dict] = []
        for c in kids:
            if not _leaf(c):
                out.extend(lists_in(c))
        return out

    entries: list[dict] = []
    for node in chrome_nodes:
        if not isinstance(node, dict):
            continue
        found = lists_in(node)
        entries.extend(found if found else ([entry(node)] if _carries_text(node) else []))
    return entries


def describe_drawn(entries: Iterable[dict], depth: int = 0) -> str:
    """The rail as a person would read it, one line per entry."""
    lines = []
    for e in entries:
        marks = []
        if e.get("icon"):
            marks.append(f"icon {int(e['icon'])}px")
        if e.get("filled"):
            marks.append("filled block")
        if e.get("navigate"):
            marks.append(f"→ {e['navigate']}")
        if e.get("workflow"):
            marks.append(f"runs {e['workflow']}")
        # THE FIRST LINE IS THE ENTRY; THE REST IS WHAT IT SAYS UNDERNEATH.
        # Rendered as "a / b / c" the caption of one entry read as the heading
        # of the next; the architect took "file management" — the caption of
        # the documents item — for a group over the footer.
        labels = list(e.get("labels") or [])
        head = ("  " * depth) + "- " + (labels[0] if labels else "")
        nested = e.get("children") if depth == 0 else None
        # An entry that holds a list is shown by that list, not by a flattened
        # run of every line inside it; an entry with no list shows what is
        # written underneath its first line. Two levels: a rail's lists and
        # their members. Deeper structure — a badge inside an item — is the
        # member's own "underneath".
        if len(labels) > 1 and not nested:
            marks.insert(0, "underneath: " + " · ".join(labels[1:]))
        lines.append(head + (f"  [{'; '.join(marks)}]" if marks else ""))
        if nested:
            lines.append(describe_drawn(nested, depth + 1))
    return "\n".join(lines)


def describe(chrome: dict) -> str:
    """The rail as a person would read it, for an agent's prompt."""
    lines = []
    if chrome.get("brand"):
        lines.append("Brand: " + " / ".join(chrome["brand"]))
    for group in chrome.get("groups") or []:
        head = group.get("label") or "(ungrouped)"
        items = ", ".join(
            it["label"] + (f" → {it['navigate']}" if it.get("navigate") else "")
            for it in group.get("items") or []
        )
        lines.append(f"{head}: {items}")
    return "\n".join(lines)
