"""The journey a design draws, written down before anything is generated.

Screen by screen, chapter by chapter: what each screen shows (its contract's
lists, records and forms), what each thing pressed does and where it leads
(its actions, with the prototype's own targets), and what the screen states
in words — "codes above 30% need finance approval", "two-person approval",
"overrides are time-boxed and logged". Those statements are the rules of the
application the design already decided; a model reading only the markup's
classes would never find them.

The document is kept with the person's other documents (`blueprint.documents`),
so the requirements step reads it as evidence and cites it, and the person
reviews it with the requirements before the data model is written.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

#: A visible line this long is a statement the screen makes, not a label.
STATEMENT_CHARS = 48
#: At most this many statements are kept per screen.
MAX_STATEMENTS = 14

TITLE = "# The connected design, screen by screen"


def _frames(doc: dict) -> dict[str, dict]:
    from services.figma.store import frame_ref
    out = {}
    for source in doc.get("designSources") or []:
        for f in source.get("frames") or []:
            if f.get("nodeId"):
                out[frame_ref(str(source.get("id") or ""), str(f["nodeId"]))] = {**f, "source": source.get("id")}
    return out


def _statements(doc: dict, output_dir: str | Path, ref: str) -> list[str]:
    """The sentences a screen writes out, from its frame less the shell."""
    from services.drawn import convert
    from services.figma.reference import labels_from_document

    prepared = convert.prepare(doc, output_dir)
    static = prepared.static.get(ref, "")
    words = re.findall(r">([^<>{}]{%d,})<" % STATEMENT_CHARS, static)
    out: list[str] = []
    for line in words:
        line = re.sub(r"\s+", " ", line.replace("&#123;", "{").replace("&#125;", "}")).strip()
        if line and line not in out and not re.search(r"\d{2,}.*\d{2,}", line[:20]):
            out.append(line)
    if not out:
        from services.figma import store
        source, node = store.split_frame_ref(ref)
        screen = store.load_screen(source or "FIGMA-001", node, output_dir)
        document = ((screen.structure or {}).get("document") if screen else None) or {}
        out = [l for l in labels_from_document(document) if len(l) >= STATEMENT_CHARS]
    return out[:MAX_STATEMENTS]


def document(doc: dict, output_dir: str | Path) -> str:
    """The flow document, or "" when the application has no drawn views."""
    from services.drawn.pairs import phone_of, wide_of

    twins, phones = phone_of(doc), wide_of(doc)
    # A phone drawing of a desktop screen is that screen: said with it, not again.
    views = {str(v.get("frame")): v for v in doc.get("drawnViews") or []
             if isinstance(v, dict) and v.get("kind") == "screen" and v.get("frame")
             and str(v.get("frame")) not in phones}
    if not views:
        return ""
    frames = _frames(doc)
    chapters: dict[str, list[str]] = {}
    for ref in views:
        group = str((frames.get(ref) or {}).get("group") or "The design")
        chapters.setdefault(group, []).append(ref)
    # The designer's layer name: a heading read off the frame can be its chrome's.
    name_of = {ref: str(f.get("name") or f.get("shows") or ref) for ref, f in frames.items()}
    lines = [TITLE, "",
             "The design is held as the specification and its screens are built as drawn. This is what each "
             "screen shows, what a person does on it and where that leads, and what it says in its own "
             "words — the application's rules as the design states them.", ""]
    from services.drawn.convert import portals

    products = portals(doc)
    if len(products) > 1:
        lines += ["## The products the design draws", "",
                  f"The design draws {len(products)} products side by side, each in its own frame with its own "
                  "menu, for its own kind of person — one application on one set of records:", ""]
        lines += [f"- {p}" for p in products] + [""]
    shells = [v for v in doc.get("drawnViews") or [] if isinstance(v, dict) and v.get("kind") == "shell"]
    for shell in shells:
        nav = [str(row.get("label") or "") for row in (shell.get("sample") or {}).get("nav") or [] if isinstance(row, dict)]
        if nav:
            head = (f"## The frame {shell['portal']}'s screens are drawn in" if shell.get("portal")
                    else "## The frame every screen is drawn in")
            lines += [head, "", "Its menu: " + ", ".join(n for n in nav if n), ""]
    for chapter, refs in chapters.items():
        lines += [f"## {chapter}", ""]
        for ref in refs:
            view = views[ref]
            contract = view.get("contract") or {}
            lines.append(f"### {name_of.get(ref, view.get('name'))}")
            shows = [f"{s.get('label') or s.get('name')} ({s.get('kind')}"
                     + (": " + ", ".join(str(f.get("label") or f.get("name")) for f in s.get("fields") or [])
                        if s.get("fields") else "") + ")"
                     for s in contract.get("data") or [] if isinstance(s, dict)]
            if shows:
                lines.append("- Shows: " + "; ".join(shows))
            for action in contract.get("actions") or []:
                if not isinstance(action, dict):
                    continue
                where = name_of.get(str(action.get("target") or ""), "")
                verb = {"navigate": "goes to", "open": "opens", "submit": "submits", "run": "does"}.get(
                    str(action.get("kind") or ""), "does")
                lines.append(f"- “{action.get('label') or action.get('name')}” {verb}"
                             + (f" {where}" if where else (f" it to {action.get('on')}" if action.get("on") else ""))
                             + ".")
            statements = _statements(doc, output_dir, ref)
            if statements:
                lines.append("- It says: " + " · ".join(f"“{s}”" for s in statements))
            if twins.get(ref):
                lines.append(f"- Also drawn for the phone, as {name_of.get(twins[ref], twins[ref])}.")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write(svc: Any) -> dict[str, Any]:
    """Keep the flow document with the person's documents, replacing an
    earlier version of it. Returns what was written."""
    from services.blueprint import documents

    text = document(svc.doc, svc.output_dir)
    if not text:
        return {}
    # REWRITTEN WHERE IT IS: requirements cite documents by number, so the
    # design's earlier account keeps its number and gets the new words.
    folder = documents.directory(svc.output_dir)
    if folder.is_dir():
        for path in sorted(folder.iterdir()):
            try:
                if path.is_file() and path.read_text("utf-8").startswith(TITLE):
                    path.write_text(text, encoding="utf-8")
                    return {"chars": len(text), "screens": text.count("\n### "), "rewritten": path.name}
            except OSError:
                continue
    documents.store(svc.output_dir, [text])
    return {"chars": len(text), "screens": text.count("\n### ")}
