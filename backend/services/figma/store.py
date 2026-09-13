"""Where the extracted design lives (PRD §14, §41, §91, §92).

Beside the Blueprint, not inside it — ``.forge/figma/FIGMA-001.json`` — for the
same reason ``services.smith.conversation`` keeps the transcript out.

§91 snapshots the entire Blueprint on every accepted change. One Figma
extraction carries generated TSX per screen and a base64 PNG per frame; a
fourteen-screen file is megabytes. Inside the document, that is copied into
every version and every ``blueprintDiff`` (§92) is buried under design payload
that changed no artifact.

What *does* go in the Blueprint is the ``designSources`` record: which file,
which frames, what was missing. Small, stable, and exactly what makes the rest
of the document coherent — §14 evidence cites ``source: FIGMA-001`` and
``pages[].figmaFrame`` names a node id, and neither resolves without knowing
what FIGMA-001 is.

On FIGMA ids
------------
They come from this store's own sequence, not :class:`IdAllocator`. Adding
``FIGMA`` to ``ID_PREFIXES`` would make ``is_valid_id("FIGMA-001")`` true while
``BlueprintService.find`` has no section to resolve it in — a claim the rest of
the system would then act on. A design source is not a Blueprint artifact; it
is the evidence some artifacts came from.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.figma.reference import (
    ComponentRef, DesignReference, DesignTokens, InteractionRef, ScreenRef,
)
from services.figma.url import FigmaTarget

STORE_DIR = ".forge/figma"
_ID = re.compile(r"^(FIGMA|UXPILOT)-(\d{3,})$")
#: Id prefix per provider. UX Pilot sources share the store and the sequence
#: rule; only the prefix says which tool a citation resolves into.
PREFIX_BY_PROVIDER = {"figma": "FIGMA", "uxpilot": "UXPILOT"}


def store_dir(output_dir: str | Path) -> Path:
    return Path(output_dir) / STORE_DIR


def next_source_id(doc: dict, provider: str = "figma") -> str:
    """The next ``FIGMA-nnn`` (or ``UXPILOT-nnn``), from what the document
    already records.

    Derived from the document rather than a counter file: the document is what
    survives a restore (§93), and a counter that disagreed with it would hand
    out an id already in use. Each provider counts its own sequence.
    """
    prefix = PREFIX_BY_PROVIDER.get(provider, "FIGMA")
    used = [
        int(m.group(2))
        for s in (doc.get("designSources") or [])
        if (m := _ID.match(str(s.get("id") or ""))) and m.group(1) == prefix
    ]
    return f"{prefix}-{max(used, default=0) + 1:03d}"


def source_record(ref: DesignReference, *, name: str = "",
                  treat_as: str = "evidence") -> dict[str, Any]:
    """The Blueprint's ``designSources`` entry for this reference.

    ``treat_as`` is `evidence` or `specification` — whether the page set is
    derived from the data model with this design informing it, or IS these
    frames. Defaults to evidence (§48), so a caller that does not care gets the
    behaviour every existing project already has.
    """
    return {
        "id": ref.source_id,
        "type": ref.provider or "figma",
        "fileKey": ref.target.file_key,
        **({"nodeId": ref.target.node_id} if ref.target.node_id else {}),
        "url": ref.target.source_url,
        "name": name,
        "extractedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "treatAs": treat_as if treat_as in ("evidence", "specification") else "evidence",
        "frames": [
            {
                "nodeId": s.node_id,
                "name": s.name,
                "looksLikeScreen": s.looks_like_screen,
            }
            for s in ref.screens
        ],
        "gaps": list(ref.gaps),
    }


def save(ref: DesignReference, output_dir: str | Path) -> Path:
    """Write the full reference. Returns the path written."""
    directory = store_dir(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{ref.source_id}.json"
    path.write_text(json.dumps(_as_dict(ref), indent=2), "utf-8")
    return path


def load(source_id: str, output_dir: str | Path) -> DesignReference | None:
    """Read a stored reference back, or ``None`` if it is not there.

    ``None`` rather than raising: a Blueprint restored from a version snapshot
    (§93) legitimately names a source whose payload was never copied, and the
    caller's job is to say so rather than crash.
    """
    path = store_dir(output_dir) / f"{source_id}.json"
    if not path.exists():
        return None
    return _from_dict(json.loads(path.read_text("utf-8")))


def connect(svc: Any, ref: DesignReference, *, name: str = "",
            treat_as: str = "evidence") -> dict[str, Any]:
    """Record a reference against a Blueprint: payload out, citation in.

    Idempotent by ``source_id`` — re-extracting the same file updates its
    record rather than adding a second one, which is what makes a re-connect
    safe to retry (§103).
    """
    save(ref, svc.output_dir)
    record = source_record(ref, name=name, treat_as=treat_as)
    # WHAT THE SCREENS SHARE, RECORDED AS EVIDENCE (§48). The rail every
    # frame carries says which groups and destinations the designer drew, and
    # the agent that authors `navigation.tree` reads it from here. Best-effort:
    # a design with one frame, or frames that share nothing, records none.
    chrome = _chrome_evidence(ref)
    if chrome:
        record["chrome"] = chrome
    # WHAT EACH FRAME SHOWS, so the planner can route it by its identity rather
    # than its position. Read with the shared chrome removed, or every frame's
    # first heading would be the brand.
    shows = _frame_headings(ref)
    for frame in record.get("frames") or []:
        heading = shows.get(str(frame.get("nodeId") or ""))
        if heading:
            frame["shows"] = heading
    sources = svc.doc.setdefault("designSources", [])
    for index, existing in enumerate(sources):
        if existing.get("id") == record["id"]:
            sources[index] = record
            break
    else:
        sources.append(record)
    svc.save()
    return record


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _as_dict(ref: DesignReference) -> dict[str, Any]:
    return asdict(ref)


def _from_dict(raw: dict[str, Any]) -> DesignReference:
    target = FigmaTarget(**(raw.get("target") or {}))
    tokens = DesignTokens(**(raw.get("tokens") or {}))
    out = DesignReference(
        target=target,
        source_id=raw.get("source_id") or "FIGMA-001",
        provider=str(raw.get("provider") or "figma"),
        tokens=tokens,
        gaps=list(raw.get("gaps") or []),
    )
    out.screens = [ScreenRef(**s) for s in raw.get("screens") or []]
    out.components = [
        ComponentRef(**{**c, "variants": tuple(c.get("variants") or ())})
        for c in raw.get("components") or []
    ]
    out.interactions = [InteractionRef(**i) for i in raw.get("interactions") or []]
    return out


def _screen_tree(screen: ScreenRef) -> dict | None:
    """The screen as the element tree the chrome and heading readers walk.

    ONE SEAM FOR BOTH CAPTURES. From the hosted MCP's design-context code
    when the extraction holds it; from the REST node document otherwise —
    which is every production extraction, the MCP's code being gated to
    partners. `_frame_headings` and `_chrome_evidence` read only
    `structure.code`, so a file captured over the REST API recorded no
    `shows` at all and the planner routed fifteen identically named frames by
    position again — the exact failure `shows` exists to end. Both captures
    already compose through `figma_layout`; reading them here through the
    same two transforms is what makes a frame's identity independent of how
    it was fetched.
    """
    structure = screen.structure or {}
    try:
        w, h = float(screen.width or 0), float(screen.height or 0)
    except (TypeError, ValueError):
        w = h = 0.0
    canvas = (w, h) if w > 0 and h > 0 else None
    code = str(structure.get("code") or "")
    if code:
        from services.jsx_to_schema import transform_jsx_to_schema
        return transform_jsx_to_schema(code, {}, canvas=canvas)["children"][0]
    document = (structure.get("document")
                if structure.get("source") == "rest_node_document" else None)
    if isinstance(document, dict):
        from services.figma_to_schema import build_page_schema
        page = build_page_schema(document, asset_paths={}).page
        kids = [c for c in (page.get("children") or []) if isinstance(c, dict)]
        if not kids:
            return None
        return kids[0] if len(kids) == 1 else {"type": "Stack", "props": {}, "children": kids}
    return None


def _screen_trees(ref: DesignReference) -> dict[str, dict]:
    """node id -> tree, for every screen that can be read; the rest are skipped.

    Neutral context on purpose: the JSX transform binds actions against a
    process-wide vocabulary, and a vocabulary left set by an earlier turn
    would turn every button here into a classifier call. Cleared for the
    read and restored after, so reading a design never leaves another
    project's routes behind.
    """
    from services.figma_llm_ctx import (
        get_routes, get_workflows, reset_figma_llm_context, set_figma_llm_context,
    )
    saved = (list(get_routes()), list(get_workflows()))
    reset_figma_llm_context()
    trees: dict[str, dict] = {}
    try:
        for screen in ref.screens:
            try:
                tree = _screen_tree(screen)
            except Exception:  # noqa: BLE001 — one unreadable screen, never the record
                continue
            if tree is not None:
                trees[screen.node_id] = tree
    finally:
        set_figma_llm_context(routes=saved[0] or None, workflows=saved[1] or None)
    return trees


def _chrome_evidence(ref: DesignReference) -> dict[str, Any]:
    """The rail the screens share, read as brand, groups and destinations."""
    try:
        from services.figma import chrome as _chrome
    except Exception:  # noqa: BLE001
        return {}
    roots: list[dict] = list(_screen_trees(ref).values())
    shared = _chrome.chrome_for(roots)
    if not shared or not roots:
        return {}
    _content, removed = _chrome.split(roots[0], shared)
    if not removed:
        return {}
    nav = _chrome.navigation_from(removed)
    drawn = _chrome.rail_as_drawn(removed)
    if not drawn and not nav.get("groups"):
        return {}
    return {"sidebar": {**nav, "drawn": drawn}, "sharedBy": len(roots)}


def _frame_headings(ref: DesignReference) -> dict[str, str]:
    """node id -> the first heading the frame shows once its chrome is gone."""
    try:
        from services.figma import chrome as _chrome
    except Exception:  # noqa: BLE001
        return {}
    trees: dict[str, dict] = _screen_trees(ref)
    shared = _chrome.chrome_for(list(trees.values()))

    def _words(text) -> bool:
        return isinstance(text, str) and len(text.strip()) >= 3 and any(ch.isalpha() for ch in text)

    def first_text(node, kinds):
        if isinstance(node, dict):
            props = node.get("props") or {}
            text = props.get("content") if node.get("type") in kinds else None
            if _words(text):
                return text.strip()
            for child in node.get("children") or []:
                found = first_text(child, kinds)
                if found:
                    return found
        return None

    def _width(node) -> float:
        cls = str((node.get("props") or {}).get("className") or "")
        for pat in (r"flex-\[(\d+(?:\.\d+)?)_0_0\]", r"max-w-\[(\d+(?:\.\d+)?)px\]", r"\bw-\[(\d+(?:\.\d+)?)px\]"):
            m = re.search(pat, cls)
            if m:
                return float(m.group(1))
        return 0.0

    def content_region(tree):
        """The widest region of the frame's first row. A lone frame has no
        shared chrome to remove, and its rail comes first in document order:
        its brand is not what the screen shows."""
        first = next((c for c in tree.get("children") or [] if isinstance(c, dict)), None)
        kids = [c for c in (first or {}).get("children") or [] if isinstance(c, dict)]
        if len(kids) >= 2 and any(_width(k) for k in kids):
            return max(kids, key=_width)
        return tree

    def _size(node) -> float:
        m = re.search(r"\btext-\[(\d+(?:\.\d+)?)px\]", str((node.get("props") or {}).get("className") or ""))
        return float(m.group(1)) if m else 0.0

    def texts(node, out, labels=False):
        """Every lettered text under ``node`` with its drawn size, in order.

        ``labels`` reads what a Button or Link SAYS as well. A rail drawn in
        the REST capture types its destinations as buttons — the word is the
        control's label, not a text node — so read as texts alone the rail
        named nothing and every frame fell back to its first word, the brand.
        Only the rail is read this way: a content button that happens to
        echo a rail entry ("+ New Case") is an action, not the screen's name.
        """
        if isinstance(node, dict):
            props = node.get("props") or {}
            kind = node.get("type")
            content = props.get("content") if kind in ("Heading", "Text") else None
            if content is None and labels and kind in ("Button", "Link"):
                content = props.get("label")
            if _words(content):
                out.append((content.strip(), _size(node)))
            for child in node.get("children") or []:
                texts(child, out, labels)
        elif isinstance(node, list):
            for child in node:
                texts(child, out, labels)
        return out

    def _norm(text: str) -> str:
        return "".join(ch for ch in text.lower() if ch.isalnum())

    def beside_content(tree):
        """The lone frame's chrome: what the first row holds beside the widest
        region — its rail, drawn once and shared with nothing."""
        first = next((c for c in tree.get("children") or [] if isinstance(c, dict)), None)
        kids = [c for c in (first or {}).get("children") or [] if isinstance(c, dict)]
        if len(kids) >= 2 and any(_width(k) for k in kids):
            widest = max(kids, key=_width)
            return [k for k in kids if k is not widest]
        return []

    # WHAT A FRAME SHOWS IS THE DESTINATION ITS RAIL NAMES. Fifteen frames of
    # one file each opened with a breadcrumb — "Criterion / Ticket Queue" —
    # and the first lettered text of every content region was the brand, so
    # the planner had fifteen frames called "Criterion" and routed them by
    # position: 14 of 15 wrong. A screen is one of the places its own rail
    # lists, and the rail is already in hand as the chrome. Among the content
    # region's texts that name a rail entry, the one drawn largest is the
    # title, and among equals the later one — a breadcrumb lists ancestors
    # first. The rail on a legislative dashboard names "لوحة التحكم" and so
    # does its header at 14px, beneath a 28px KPI and a 20px section heading
    # that name nothing; the first lettered text remains the fallback for a
    # frame whose rail names none of its texts.
    out: dict[str, str] = {}
    for node_id, tree in trees.items():
        if shared:
            content, removed = _chrome.split(tree, shared)
        else:
            content, removed = content_region(tree), beside_content(tree)
        # THE RAIL'S DESTINATIONS, NOT ITS EVERY WORD. The rail also carries
        # the brand, and a breadcrumb repeats the brand as its first crumb on
        # every frame — so a screen whose own title the rail does not list
        # (Notifications, on one real file) matched the brand and was named
        # after it. `navigation_from` already tells the brand from the
        # destinations; a rail it cannot read falls back to every word it
        # shows, which is what this read before.
        nav = _chrome.navigation_from(removed) if removed else {}
        destinations = [str(item.get("label") or "")
                        for group in (nav.get("groups") or [])
                        for item in (group.get("items") or [])]
        named = ({_norm(t) for t in destinations if _words(t)}
                 or {_norm(t) for t, _ in texts(removed, [], labels=True)})
        owned = named | {_norm(t) for t, _ in texts(removed, [], labels=True)}
        shown = [(size, i, t) for i, (t, size) in enumerate(texts(content, []))
                 if _norm(t) in named]
        heading = max(shown, key=lambda c: (c[0], c[1]))[2] if shown else None
        if heading is None:
            # A FRAME'S NAME IS NEVER A WORD ITS CHROME ALREADY OWNS. The
            # first lettered text of a content region is a breadcrumb's first
            # crumb — the brand — on every frame that has one, so the fallback
            # skips whatever the rail says (brand, section labels, the signed-in
            # user) and takes the first word that is the screen's own.
            heading = next((t for t, _ in texts(content, []) if _norm(t) not in owned),
                           None) or first_text(content, ("Heading", "Text"))
        if heading:
            out[node_id] = heading
    return out
