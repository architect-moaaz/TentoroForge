"""A connected design's frames as `drawnViews` rows: screens, shells, components.

The design is read once per build (`prepare`, cached for the fan-out's
threads): every frame of a design held as the specification is loaded, the
shell and the prototype's furniture found (`shell`), the shared components
found (`components`) and each frame drawn as static markup (`tsx`). A screen's
row then costs one model call (`params`); each shell's one more; components
none.

A DESIGN OF SEVERAL PRODUCTS HAS A SHELL FOR EACH. A file that draws a
candidate app, a recruiter portal and an admin back office side by side, one
top-level section each (the frames' `portal`), draws three different sidebars;
one shell for all of them put the admin's menu around the candidate's screens.
Each portal's shell is found among its own frames, and so is its furniture.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from services.drawn import shell as _shell
from services.drawn.components import Library
from services.drawn.tsx import Assets, Emitter, component_name

SHELL_KEY = "shell"
SHELL_NAME = "DrawnShell"
#: A portal's shell is the subject `shell:<portal>` when the design has several.
SHELL_PREFIX = "shell:"
#: The subject that writes every shared component's row at once.
COMPONENTS_KEY = "components"


def _spec_frames(doc: dict) -> list[tuple[dict, dict]]:
    """``(source, frame)`` for every screen of a design held as the specification."""
    out = []
    for source in doc.get("designSources") or []:
        if str(source.get("treatAs") or "") != "specification":
            continue
        for frame in source.get("frames") or []:
            if frame.get("nodeId") and frame.get("looksLikeScreen", True):
                out.append((source, frame))
    return out


def frame_subjects(doc: dict) -> list[str]:
    """The frames `drawn_views` converts, by reference."""
    from services.figma.store import frame_ref
    return [frame_ref(str(s.get("id") or ""), str(f["nodeId"])) for s, f in _spec_frames(doc)]


def portals(doc: dict) -> list[str]:
    """The products the design draws side by side, in the order drawn: its
    frames' top-level sections. One or none is a design of one product."""
    out: list[str] = []
    for _s, f in _spec_frames(doc):
        portal = str(f.get("portal") or "")
        if portal and portal not in out:
            out.append(portal)
    return out


def shell_key(doc: dict, portal: str) -> str:
    """The subject — and the row key — of a portal's shell."""
    return SHELL_PREFIX + portal if len(portals(doc)) > 1 else SHELL_KEY


def shell_subjects(doc: dict) -> list[str]:
    many = portals(doc)
    return [SHELL_PREFIX + p for p in many] if len(many) > 1 else [SHELL_KEY]


def is_shell_subject(subject: str) -> bool:
    return subject == SHELL_KEY or subject.startswith(SHELL_PREFIX)


def shell_name(portal: str, many: bool) -> str:
    """`DrawnShell`, or one per portal: `EmployerRecruiterShell`."""
    return component_name(portal, "Shell") if many and portal else SHELL_NAME


@dataclass
class Prepared:
    """One design, read for conversion."""
    names: dict[str, str] = field(default_factory=dict)          # frame ref -> component name
    static: dict[str, str] = field(default_factory=dict)         # frame ref -> markup
    headings: dict[str, str] = field(default_factory=dict)       # frame ref -> what it shows
    images: dict[str, str] = field(default_factory=dict)         # frame ref -> picture path
    links: dict[str, list[dict]] = field(default_factory=dict)   # frame ref -> links
    dropped: dict[str, list[str]] = field(default_factory=dict)  # frame ref -> furniture left out
    #: The shell of a design of one product…
    shell_markup: str = ""
    shell_frame: str = ""
    shell_image: str = ""
    #: …and every portal's, by subject: ``{key: {markup, frame, image, portal, name}}``.
    shells: dict[str, dict] = field(default_factory=dict)
    portal_of: dict[str, str] = field(default_factory=dict)      # frame ref -> portal
    components: dict[str, str] = field(default_factory=dict)     # name -> file
    component_keys: dict[str, list[str]] = field(default_factory=dict)
    assets: Assets = field(default_factory=Assets)
    file_keys: dict[str, str] = field(default_factory=dict)      # source id -> file key


_CACHE: dict[str, Prepared] = {}
_LOCK = threading.Lock()


def _signature(doc: dict, output_dir: str | Path) -> str:
    frames = [(s.get("id"), s.get("extractedAt"), f.get("nodeId")) for s, f in _spec_frames(doc)]
    return hashlib.sha1(json.dumps([str(output_dir), frames], default=str).encode()).hexdigest()


def prepare(doc: dict, output_dir: str | Path) -> Prepared:
    """The design read for conversion — once per design, however many threads ask."""
    key = _signature(doc, output_dir)
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
        prepared = _prepare(doc, output_dir)
        _CACHE[key] = prepared
        return prepared


def _prepare(doc: dict, output_dir: str | Path) -> Prepared:
    from services.figma import store
    from services.figma.react_reference import screen_image

    out = Prepared()
    documents: dict[str, dict] = {}
    screens_by_ref: dict[str, Any] = {}
    frame_names: dict[str, str] = {}
    for source, frame in _spec_frames(doc):
        ref = store.frame_ref(str(source.get("id") or ""), str(frame["nodeId"]))
        out.file_keys[str(source.get("id") or "")] = str(source.get("fileKey") or "")
        screen = store.load_screen(str(source.get("id") or ""), str(frame["nodeId"]), output_dir)
        structure = (getattr(screen, "structure", None) or {}) if screen else {}
        document = structure.get("document") if isinstance(structure.get("document"), dict) else None
        frame_names[str(frame["nodeId"])] = str(frame.get("shows") or frame.get("name") or "")
        out.portal_of[ref] = str(frame.get("portal") or "")
        if document is None:
            continue
        documents[ref] = document
        screens_by_ref[ref] = (source, screen, frame)
    # Each portal read on its own: its frame, and its prototype's furniture.
    many = len(portals(doc)) > 1
    groups: dict[str, dict[str, dict]] = {}
    for ref, document in documents.items():
        groups.setdefault(out.portal_of.get(ref, "") if many else "", {})[ref] = document
    read_by: dict[str, dict] = {portal: _shell.read_all(docs) for portal, docs in groups.items()}
    read = {ref: s for by in read_by.values() for ref, s in by.items()}
    skip: set[str] = set()
    for s in read.values():
        skip |= s.skip
    emitter = Emitter(assets=out.assets, skip=skip)
    library = Library.build([s.page_root for s in read.values() if s.page_root is not None], emitter)
    emitter.component = library.use
    out.components = library.files()
    out.component_keys = {sh.name: sh.keys for sh in library.shared.values()}
    taken: set[str] = set()
    for ref, screen_read in read.items():
        source, screen, frame = screens_by_ref[ref]
        name = component_name(str(frame.get("name") or ref))
        base, n = name, 2
        while name in taken:
            name, n = f"{base[:-4]}{n}View", n + 1
        taken.add(name)
        out.names[ref] = name
        out.static[ref] = emitter.frame(screen_read.page_root or screen_read.document, name)
        out.headings[ref] = str(frame.get("shows") or frame.get("name") or "")
        image = screen_image(screen, output_dir, str(source.get("id") or ""))
        if image:
            out.images[ref] = str(image)
        out.links[ref] = [{**link, "to": store.frame_ref(str(source.get("id") or ""), str(link.get("to") or "")),
                           "to_name": frame_names.get(str(link.get("to") or ""), "")}
                          for link in frame.get("links") or [] if isinstance(link, dict)]
        out.dropped[ref] = list(screen_read.dropped)
    for portal, portal_read in read_by.items():
        chosen = _shell.the_shell(portal_read)
        if chosen is None:
            continue
        ref, screen_read = chosen
        # THE SHELL IS DRAWN WITH ITS OWN PARTS. Every page leaves the sidebar
        # and the top bar out; the shell is exactly them, so it leaves out only
        # the prototype's furniture — drawn with the page emitter it came out
        # empty, and was refused for losing the drawing (d6drawn, 2026-10-28).
        shell_parts = {str((screen_read.sidebar or {}).get("id")), str((screen_read.topbar or {}).get("id"))}
        furniture = {i for s in portal_read.values() for i in s.skip
                     if i not in {str((s.sidebar or {}).get("id")), str((s.topbar or {}).get("id"))}}
        own = Emitter(assets=out.assets, skip=furniture - shell_parts, component=library.use)
        name = shell_name(portal, many)
        key = SHELL_PREFIX + portal if many else SHELL_KEY
        out.shells[key] = {"markup": _shell.shell_markup(screen_read, own, name), "frame": ref,
                           "image": out.images.get(ref, ""), "portal": portal, "name": name}
    if SHELL_KEY in out.shells:
        only = out.shells[SHELL_KEY]
        out.shell_markup, out.shell_frame, out.shell_image = only["markup"], only["frame"], only["image"]
    return out


def component_rows(prepared: Prepared) -> list[dict]:
    """A `drawnViews` row for every shared component. No model: its props are
    its words."""
    rows = []
    for name, code in prepared.components.items():
        keys = prepared.component_keys.get(name, [])
        body = ('"use client";\nimport type * as React from "react";\n\n' + code)
        rows.append({"key": f"component:{name}", "kind": "component", "name": name, "code": body,
                     "contract": {"data": [{"name": k, "kind": "value", "label": k, "fields": [], "type": "string"}
                                           for k in keys], "actions": []},
                     "sample": {}, "source": hashlib.sha1(code.encode()).hexdigest()[:16]})
    return rows


def screen_row(client: Any, prepared: Prepared, ref: str, *, usage: list | None = None) -> dict:
    """A screen's `drawnViews` row: its view, contract and sample."""
    from services.drawn.params import parameterise

    name, static = prepared.names[ref], prepared.static[ref]
    used = {n: prepared.component_keys.get(n, []) for n in prepared.components if f"<{n} " in static}
    out = parameterise(client, name, static, heading=prepared.headings.get(ref, ""),
                       image=prepared.images.get(ref), links=prepared.links.get(ref, []),
                       components=used, usage=usage)
    return {"key": ref, "kind": "screen", "name": name, "frame": ref, "code": out["code"],
            "contract": out["contract"], "sample": out["sample"],
            "source": hashlib.sha1(static.encode()).hexdigest()[:16],
            **({"portal": prepared.portal_of[ref]} if prepared.portal_of.get(ref) else {})}


SHELL_BRIEF = "The application's shell: the sidebar and top bar every screen is drawn in"


def shell_row(client: Any, prepared: Prepared, key: str = SHELL_KEY, *, usage: list | None = None) -> dict | None:
    """A shell's `drawnViews` row (the design's, or one portal's), or None
    when that part of the design draws none."""
    from services.drawn.params import parameterise

    shell = prepared.shells.get(key)
    if not shell or not shell.get("markup"):
        return None
    static, name = str(shell["markup"]), str(shell["name"])
    used = {n: prepared.component_keys.get(n, []) for n in prepared.components if f"<{n} " in static}
    out = parameterise(client, name, static, heading=SHELL_BRIEF, image=shell.get("image") or None,
                       links=prepared.links.get(str(shell["frame"]), []), components=used, usage=usage,
                       children=True)
    return {"key": key, "kind": "shell", "name": name, "frame": shell["frame"],
            "code": out["code"], "contract": out["contract"], "sample": out["sample"],
            "source": hashlib.sha1(static.encode()).hexdigest()[:16],
            **({"portal": shell["portal"]} if shell.get("portal") else {})}


def export_assets(prepared: Prepared, output_dir: str | Path) -> dict:
    """Every icon and picture the views refer to, rendered by Figma into the app."""
    from services.drawn.assets import export

    report: dict[str, Any] = {"saved": 0, "kept": 0, "missing": []}
    by_source: dict[str, dict] = {}
    for name, (nid, fmt) in prepared.assets.items.items():
        source_id = nid.split("/", 1)[0] if "/" in nid else next(iter(prepared.file_keys), "")
        by_source.setdefault(source_id, {})[name] = (nid.split("/")[-1], fmt)
    for source_id, items in by_source.items():
        file_key = prepared.file_keys.get(source_id) or next(iter(prepared.file_keys.values()), "")
        got = export(output_dir, file_key, items)
        report["saved"] += got.get("saved", 0)
        report["kept"] += got.get("kept", 0)
        report["missing"] += got.get("missing", [])
        if got.get("why"):
            report["why"] = got["why"]
    return report
