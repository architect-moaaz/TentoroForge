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

    def _px(node: dict) -> float:
        cls = str((node.get("props") or {}).get("className") or "")
        m = re.search(r"\b(?:size|w|h)-\[(\d+(?:\.\d+)?)px\]", cls)
        return float(m.group(1)) if m else 0.0

    def _icon_size(node: dict, inherited: float = 0.0) -> float:
        # A logo is often a sized box holding a `size-full` image (a flag
        # emblem drawn as vectors); the box's size is the icon's size.
        for child in node.get("children") or []:
            if not isinstance(child, dict):
                continue
            if child.get("type") in ("Image", "Icon"):
                return _px(child) or inherited
            if child.get("type") not in ("Button", "Text", "Heading"):
                found = _icon_size(child, _px(child) or inherited)
                if found:
                    return found
        return 0.0

    def _has_icon(node: dict) -> bool:
        for child in node.get("children") or []:
            if not isinstance(child, dict):
                continue
            if child.get("type") in ("Image", "Icon"):
                return True
            if child.get("type") not in ("Button", "Text", "Heading") and _has_icon(child):
                return True
        return False

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        props = node.get("props") or {}
        # AN ICON BESIDE A LABEL IS A DESTINATION. A rail item drawn as icon +
        # label + caption (+ badge) is one item, not three labels: its first
        # words are the destination and the rest describe it. Read as three,
        # the caption of one item became the heading of the next.
        labels = _labels(node, [])
        cls = str(props.get("className") or "")
        filled = any(t.startswith("bg-") and t not in ("bg-transparent", "bg-none") for t in cls.split())
        # A FILLED BLOCK OF SEVERAL LABELS IS A STATUS CARD, NOT NAVIGATION —
        # "session in progress / 2026/15 / Sunday 31 August" drawn in the rail.
        # Read as labels, its last line became the heading of the items below.
        if node.get("type") not in ("Button",) and filled and not _has_icon(node) and len(labels) >= 2:
            return
        if node.get("type") != "Button" and labels and len(labels) <= 3 and _has_icon(node):
            # THE BRAND IS THE BIG ICON. A logo beside a name reads as icon +
            # label like any destination; what sets it apart is size — a
            # destination's glyph is 16-24px, a logo 32px and up — and place,
            # before any destination has been read.
            if not entries and _icon_size(node) >= 32:
                entries.append((labels[0], {**props, "_brand": True}))
                return
            entries.append((labels[0], {**props, "_item": True}))
            return
        text = props.get("label") or props.get("content") or props.get("text")
        if isinstance(text, str) and text.strip():
            entries.append((text.strip(), {**props, "_item": node.get("type") == "Button"}))
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
            any(props.get(k) for k in _ACTIONS) or bool(_GLYPH.match(raw)) or bool(props.get("_item")))

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
        if props.get("_brand"):
            brand.append(label)
            continue
        if _is_item(i):
            action = {k: props[k] for k in _ACTIONS if props.get(k) and k != "_item"}
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
    # A LONE ITEM AHEAD OF THE REST IS THE BRAND: a logo beside a name reads
    # as icon + label, exactly like a destination, but a destination comes
    # in a run and the brand stands alone at the top.
    if len(groups) >= 2 and not groups[0]["label"] and len(groups[0]["items"]) == 1:
        brand.insert(0, groups[0]["items"][0]["label"])
        groups = groups[1:]
    return {"brand": brand, "groups": groups}


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
