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
_ID = re.compile(r"^FIGMA-(\d{3,})$")


def store_dir(output_dir: str | Path) -> Path:
    return Path(output_dir) / STORE_DIR


def next_source_id(doc: dict) -> str:
    """The next ``FIGMA-nnn``, from what the document already records.

    Derived from the document rather than a counter file: the document is what
    survives a restore (§93), and a counter that disagreed with it would hand
    out an id already in use.
    """
    used = [
        int(m.group(1))
        for s in (doc.get("designSources") or [])
        if (m := _ID.match(str(s.get("id") or "")))
    ]
    return f"FIGMA-{max(used, default=0) + 1:03d}"


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
        "type": "figma",
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


def _chrome_evidence(ref: DesignReference) -> dict[str, Any]:
    """The rail the screens share, read as brand, groups and destinations."""
    try:
        from services.figma import chrome as _chrome
        from services.jsx_to_schema import transform_jsx_to_schema
    except Exception:  # noqa: BLE001
        return {}
    # Neutral context on purpose: a fingerprint is types and text, and a
    # vocabulary left set by an earlier turn would turn every button here into
    # a classifier call.
    from services.figma_llm_ctx import (
        get_routes, get_workflows, reset_figma_llm_context, set_figma_llm_context,
    )
    saved = (list(get_routes()), list(get_workflows()))
    reset_figma_llm_context()
    roots: list[dict] = []
    try:
        for screen in ref.screens:
            code = str((screen.structure or {}).get("code") or "")
            if not code:
                continue
            try:
                w, h = float(screen.width or 0), float(screen.height or 0)
                tree = transform_jsx_to_schema(
                    code, {}, canvas=(w, h) if w > 0 and h > 0 else None)
                roots.append(tree["children"][0])
            except Exception:  # noqa: BLE001
                continue
    finally:
        set_figma_llm_context(routes=saved[0] or None, workflows=saved[1] or None)
    shared = _chrome.shared_chrome(roots)
    if not shared or not roots:
        return {}
    _content, removed = _chrome.split(roots[0], shared)
    if not removed:
        return {}
    nav = _chrome.navigation_from(removed)
    if not nav.get("groups"):
        return {}
    return {"sidebar": nav, "sharedBy": len(roots)}


def _frame_headings(ref: DesignReference) -> dict[str, str]:
    """node id -> the first heading the frame shows once its chrome is gone."""
    try:
        from services.figma import chrome as _chrome
        from services.figma_llm_ctx import (
            get_routes, get_workflows, reset_figma_llm_context, set_figma_llm_context,
        )
        from services.jsx_to_schema import transform_jsx_to_schema
    except Exception:  # noqa: BLE001
        return {}
    saved = (list(get_routes()), list(get_workflows()))
    reset_figma_llm_context()
    trees: dict[str, dict] = {}
    try:
        for screen in ref.screens:
            code = str((screen.structure or {}).get("code") or "")
            if not code:
                continue
            try:
                w, h = float(screen.width or 0), float(screen.height or 0)
                trees[screen.node_id] = transform_jsx_to_schema(
                    code, {}, canvas=(w, h) if w > 0 and h > 0 else None)["children"][0]
            except Exception:  # noqa: BLE001
                continue
    finally:
        set_figma_llm_context(routes=saved[0] or None, workflows=saved[1] or None)
    shared = _chrome.shared_chrome(list(trees.values()))

    def first_heading(node):
        if isinstance(node, dict):
            props = node.get("props") or {}
            text = props.get("content") if node.get("type") == "Heading" else None
            if isinstance(text, str) and len(text.strip()) >= 3:
                return text.strip()
            for child in node.get("children") or []:
                found = first_heading(child)
                if found:
                    return found
        return None

    out: dict[str, str] = {}
    for node_id, tree in trees.items():
        content, _removed = _chrome.split(tree, shared) if shared else (tree, [])
        heading = first_heading(content)
        if heading:
            out[node_id] = heading
    return out
