"""UX Pilot as the page designer — one generated screen per page contract.

The design note is ``docs/plans/2026-09-13-ux-pilot-page-generation.md``; this
is its agent. It is an executor with no model step of its own: everything it
does is derived from the page brief, the gateway, and the tree that comes back.

The seam it fills
-----------------
`page_layouts` has one producer per page and, before this, two ways to get a
tree: a frame a person drew (``figma_layout.compose``) and A2UI composing from
the catalog. This adds a third, chosen by the user at the approval gate and
recorded as ``application.uiDesigner`` (with ``pages[].designedBy`` as the
per-page override). :func:`designer_for` is the whole dispatch rule; the
executor asks it per page and calls :func:`compose` when the answer is
``uxpilot``. What comes back is the same kind of object the other two produce
— catalog components, live ``dataSources`` — so nothing downstream knows.

Why Forge writes the prompt, and why the labels matter
------------------------------------------------------
UX Pilot returns HTML with invented literals: "142 tasks", "Follow up with
client". Imported verbatim that is a page that looks finished and is entirely
fiction, which is the failure the A2UI converter was written to prevent. So
the prompt is built from the page brief — the widgets, the derived columns, the
actions, the states — and it dictates the labels. When the HTML comes back,
the tile labelled with a widget's name IS that widget, the header row carrying
the entity's columns IS its table, the button carrying a workflow's name
launches it. Binding is a lookup against words this module chose, not an
inference about words a model chose (:func:`bind_by_label`). What does not
match stays as drawn and is said in ``warnings``, never guessed.

Generated designs are not design sources
----------------------------------------
``designSources`` is evidence: `figma_intelligence` fans out over it and
extracts requirements from what it finds. A design generated FROM this
application's brief fed back in as evidence FOR it is a loop. So generated
designs live in a ledger beside the Blueprint (``.forge/uxpilot/generated.json``)
keyed by page and by the hash of the prompt that produced them: a rebuild
re-projects from the ledger and spends credits only for a page whose brief
changed. The design also lives in the user's UX Pilot workspace under the
recorded design id.

Falling through is said, not silent
-----------------------------------
Every failure returns an :class:`Outcome` with ``root=None`` and a reason.
The executor composes that page with A2UI and records the reason on the
layout, so the user who clicked UX Pilot can see which pages did not come
from it and why. A missing key is refused before any page is attempted, by
the approval gate (:mod:`services.smith.ui_designer`), not here.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_KEY_ENV = "UXPILOT_API_KEY"
ENDPOINT_KEY = "UXPILOT_MCP_URL"
LEDGER_RELATIVE = Path(".forge") / "uxpilot" / "generated.json"

#: Only this many labels per group go into the prompt. A page with forty
#: widgets is a page-design problem, not a prompt-length one.
_MAX_LABELS = 12

_ledger_lock = threading.Lock()


# ---------------------------------------------------------------------------
# The dispatch rule
# ---------------------------------------------------------------------------

def designer_for(doc: dict, page: dict) -> str:
    """``forge`` or ``uxpilot``: the page's own override, else the application's,
    else Forge — which is what every application built before the choice
    existed was."""
    own = str((page or {}).get("designedBy") or "").strip()
    if own in ("forge", "uxpilot"):
        return own
    app = str(((doc or {}).get("application") or {}).get("uiDesigner") or "").strip()
    return app if app in ("forge", "uxpilot") else "forge"


# ---------------------------------------------------------------------------
# Credentials and the gateway (§42, §98)
# ---------------------------------------------------------------------------

def settings_for(output_dir: str | Path) -> dict[str, str]:
    """The organisation's UX Pilot settings, environment as fallback.

    Same seam `uxpilot_connect` reads. The key is never returned to a caller
    that prints; it stays inside the resolver the gateway holds.
    """
    from services.figma.integrations import config_for

    values = dict(config_for(output_dir, provider="uxpilot") or {})
    for key in (DEFAULT_KEY_ENV, ENDPOINT_KEY):
        if not values.get(key):
            from_env = (os.environ.get(key) or "").strip()
            if from_env:
                values[key] = from_env
    return values


def configured(output_dir: str | Path) -> bool:
    """Whether a run pointed at UX Pilot could authenticate at all."""
    return bool(settings_for(output_dir).get(DEFAULT_KEY_ENV))


def gateway_for(output_dir: str | Path) -> Any:
    """A gateway opened for generation — the one place ``may_generate`` is set."""
    from services.figma.integrations import MappingResolver
    from services.uxpilot.credentials import EnvKeyResolver, UxPilotCredential
    from services.uxpilot.gateway import UxPilotGateway

    values = settings_for(output_dir)
    resolver = MappingResolver(values) if values.get(DEFAULT_KEY_ENV) else EnvKeyResolver()
    endpoint = (values.get(ENDPOINT_KEY) or "").strip()
    return UxPilotGateway(
        credential=UxPilotCredential(ref=DEFAULT_KEY_ENV),
        resolver=resolver,
        may_generate=True,
        **({"endpoint": endpoint} if endpoint else {}),
    )


# ---------------------------------------------------------------------------
# The prompt — Forge dictates the labels
# ---------------------------------------------------------------------------

def _entities_by_id(doc: dict) -> dict[str, dict]:
    return {str(e.get("id")): e for e in ((doc.get("data") or {}).get("entities") or [])
            if isinstance(e, dict) and e.get("id")}


def _entity_name(doc: dict, entity_ref: str) -> str:
    ent = _entities_by_id(doc).get(str(entity_ref or ""))
    if ent:
        return str(ent.get("name") or entity_ref)
    return str(entity_ref or "")


def _plural(name: str) -> str:
    n = (name or "").strip()
    if not n:
        return n
    if n.endswith("y") and n[-2:-1].lower() not in "aeiou":
        return n[:-1] + "ies"
    if n.endswith(("s", "x", "ch", "sh")):
        return n + "es"
    return n + "s"


def _label_of(field_name: str) -> str:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(field_name or "").replace("_", " "))
    return spaced[:1].upper() + spaced[1:]


def _live(items: Any) -> list[dict]:
    return [x for x in (items or []) if isinstance(x, dict) and x.get("status") != "DEPRECATED"]


def _launched_here(doc: dict, page_id: str) -> list[dict]:
    """Workflows a control on this page may start, by their declared launch pages."""
    return [w for w in _live(doc.get("workflows"))
            if page_id in (w.get("launchedFrom") or []) and w.get("name")]


def _column_defs(brief: dict) -> list[dict]:
    derived = brief.get("derived") or {}
    cols = [c for c in (derived.get("columns") or []) if isinstance(c, dict) and c.get("key")]
    return [{"key": str(c["key"]), "label": str(c.get("label") or _label_of(c["key"]))}
            for c in cols]


def _form_fields(brief: dict) -> list[dict]:
    derived = brief.get("derived") or {}
    out = []
    for f in derived.get("formFields") or []:
        if isinstance(f, dict) and f.get("name"):
            out.append({"name": str(f["name"]),
                        "label": str(f.get("label") or _label_of(f["name"]))})
        elif isinstance(f, str):
            out.append({"name": f, "label": _label_of(f)})
    return out


def _metric_widgets(brief: dict) -> list[dict]:
    """Widgets that read as one number: the ones a tile can be bound to."""
    out = []
    for w in brief.get("widgets") or []:
        src = w.get("dataSource") or {}
        if src.get("op") == "aggregate" and w.get("label"):
            out.append(w)
    return out


def _design_language(doc: dict) -> str:
    ds = doc.get("designSystem") or {}
    lines: list[str] = []
    if ds.get("visualPersonality"):
        lines.append(f"Personality: {ds['visualPersonality']}.")
    colors = ds.get("colors") or {}
    if colors:
        lines.append("Colours: " + ", ".join(f"{k} {v}" for k, v in list(colors.items())[:8]) + ".")
    typo = ds.get("typography") or {}
    if typo:
        lines.append("Typography: " + ", ".join(f"{k} {v}" for k, v in list(typo.items())[:6]) + ".")
    if ds.get("informationDensity"):
        lines.append(f"Information density: {ds['informationDensity']}.")
    return "\n".join(lines)


def prompt_for(doc: dict, page: dict, *, feedback: str = "") -> str:
    """The generate prompt for one page, from its brief and nothing else.

    Deterministic on purpose: the same Blueprint produces the same prompt, so
    the ledger's hash means "the brief has not changed" and a rebuild does not
    spend credits. Every label the binder later looks for is written here,
    spelled exactly as the binder will look for it.
    """
    from services.blueprint.page_planner import page_brief

    page_id = str(page.get("id") or "")
    brief = page_brief(doc, page_id) if page_id else {}
    app = doc.get("application") or {}
    entity = brief.get("entity") or {}
    entity_name = str(entity.get("name") or "")

    parts: list[str] = [
        f"Design one desktop web page for \"{app.get('name') or 'the application'}\""
        + (f", a {app['domain']} application" if app.get("domain") and app.get("domain") != "unknown" else "")
        + ".",
        f"Page: {page.get('name') or page_id}. Purpose: {page.get('purpose') or ''}",
    ]
    if page.get("pattern"):
        parts.append(f"Page pattern: {str(page['pattern']).replace('_', ' ')}.")
    language = _design_language(doc)
    if language:
        parts.append("Design language, which every page of this application shares:\n" + language)
    parts.append(
        "Render the PAGE BODY ONLY. Do not draw a sidebar, a top navigation bar "
        "or any application shell: the application provides those around every "
        f"page. Start with the page heading \"{page.get('name') or page_id}\"."
    )
    parts.append(
        "Use exactly the labels below, spelled exactly as written. They are "
        "bound to live data after generation, so a label that differs is a "
        "widget that shows nothing."
    )
    metrics = _metric_widgets(brief)[:_MAX_LABELS]
    if metrics:
        parts.append("Metric tiles, each with its label and one number: "
                     + "; ".join(f"\"{w['label']}\"" for w in metrics) + ".")
    cols = _column_defs(brief)[:_MAX_LABELS]
    if cols and entity_name:
        parts.append(
            f"A table of {_plural(entity_name)} with exactly these column headers, "
            "in this order, and three or four example rows: "
            + ", ".join(f"\"{c['label']}\"" for c in cols) + "."
        )
    fields = _form_fields(brief)[:_MAX_LABELS]
    if fields and str(page.get("pattern") or "") in ("form", "wizard"):
        parts.append("A form with exactly these fields, labelled: "
                     + ", ".join(f"\"{f['label']}\"" for f in fields) + ".")
    buttons = [w["name"] for w in _launched_here(doc, page_id)][:_MAX_LABELS]
    buttons += [str(a) for a in (page.get("actions") or []) if str(a).strip()][:_MAX_LABELS]
    if buttons:
        parts.append("Buttons, labelled exactly: "
                     + ", ".join(f"\"{b}\"" for b in dict.fromkeys(buttons)) + ".")
    states = [s for s in (page.get("states") or []) if s in ("empty", "error")]
    if "empty" in states and entity_name:
        parts.append(f"Include, visually secondary, an empty state reading "
                     f"\"No {_plural(entity_name).lower()} yet\".")
    reqs = [str(r.get("text") or r.get("statement") or r.get("description") or "")
            for r in (brief.get("requirements") or []) if isinstance(r, dict)]
    reqs = [r for r in reqs if r][:6]
    if reqs:
        parts.append("What people come here to do:\n" + "\n".join(f"- {r}" for r in reqs))
    if feedback.strip():
        parts.append("The previous attempt was refused. Fix exactly this:\n" + feedback.strip())
    return "\n\n".join(parts)


def brief_hash(prompt: str) -> str:
    return hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# The ledger — generate once, re-project many
# ---------------------------------------------------------------------------

def ledger_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / LEDGER_RELATIVE


def _read_ledger(output_dir: str | Path) -> dict[str, dict]:
    path = ledger_path(output_dir)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text("utf-8"))
    except Exception:  # noqa: BLE001 — a corrupt ledger means regenerate, not crash
        logger.warning("[uxpilot] ledger at %s unreadable; ignoring it", path)
        return {}
    return data if isinstance(data, dict) else {}


def ledger_entry(output_dir: str | Path, page_id: str) -> dict | None:
    with _ledger_lock:
        entry = _read_ledger(output_dir).get(page_id)
    return entry if isinstance(entry, dict) else None


def _record(output_dir: str | Path, page_id: str, entry: dict) -> None:
    # Load-modify-save under one lock: pages generate on worker threads and
    # two of them writing the ledger unguarded would each keep only their
    # own page.
    with _ledger_lock:
        data = _read_ledger(output_dir)
        data[page_id] = entry
        path = ledger_path(output_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), "utf-8")
        os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

class GenerationFailed(RuntimeError):
    """UX Pilot did not give us a design. The message is the reason, said
    plainly enough to sit on a page layout's rationale."""


@dataclass(frozen=True)
class GeneratedDesign:
    page_id: str
    design_id: str
    html: str
    prompt: str
    preview_url: str = ""
    reused: bool = False


def _run(coro: Any) -> Any:
    """Run the async gateway from the orchestrator's synchronous executor."""
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _design_id_of(payload: Any) -> str:
    from services.uxpilot.reference import _find_key, _first_str

    if isinstance(payload, dict):
        design = payload.get("design") if isinstance(payload.get("design"), dict) else payload
        found = _first_str(design, ("designId", "design_id", "designUuid", "id", "uuid"))
        if found:
            return found
    for key in ("designId", "design_id", "id"):
        hit = _find_key(payload, key)
        if isinstance(hit, str) and hit.strip():
            return hit.strip()
    return ""


def _preview_of(payload: Any) -> str:
    from services.uxpilot.reference import _find_key

    for key in ("previewUrl", "preview_url", "imageUrl", "image_url", "url"):
        hit = _find_key(payload, key)
        if isinstance(hit, str) and hit.startswith("http"):
            return hit
    return ""


async def _generate_async(gateway: Any, prompt: str) -> tuple[str, str, str]:
    """``(design_id, html, preview_url)`` from one generation."""
    from services.uxpilot.reference import _find_html, payload_of

    payload = payload_of(await gateway.call("generate_design", prompt=prompt))
    design_id = _design_id_of(payload)
    html = _find_html(payload)
    preview = _preview_of(payload)
    if not html and design_id:
        # The generation acknowledged with an id and no markup; the reader
        # tool has the HTML the same way it does for a page a person drew.
        detail = payload_of(await gateway.call("get_design", design=design_id, include_html=True))
        html = _find_html(detail)
        preview = preview or _preview_of(detail)
    return design_id, html, preview


def generate(svc: Any, page: dict, *, gateway: Any = None, feedback: str = "") -> GeneratedDesign:
    """The page's design: from the ledger when its brief is unchanged, else
    from UX Pilot. Raises :class:`GenerationFailed` with the reason."""
    from services.uxpilot.credentials import UxPilotCredentialError
    from services.uxpilot.gateway import UxPilotGatewayError

    page_id = str(page.get("id") or "")
    prompt = prompt_for(svc.doc, page, feedback=feedback)
    digest = brief_hash(prompt)

    prior = ledger_entry(svc.output_dir, page_id)
    if prior and prior.get("briefHash") == digest and prior.get("html") and not feedback:
        return GeneratedDesign(page_id=page_id, design_id=str(prior.get("designId") or ""),
                               html=str(prior["html"]), prompt=prompt,
                               preview_url=str(prior.get("previewUrl") or ""), reused=True)

    gw = gateway or gateway_for(svc.output_dir)
    try:
        design_id, html, preview = _run(_generate_async(gw, prompt))
    except UxPilotCredentialError as exc:
        raise GenerationFailed(f"no UX Pilot key could be resolved ({exc})") from exc
    except UxPilotGatewayError as exc:
        raise GenerationFailed(f"UX Pilot {exc.kind}: {exc.detail}") from exc
    except Exception as exc:  # noqa: BLE001 — the reason travels, the page does not die
        raise GenerationFailed(f"UX Pilot call failed: {type(exc).__name__}: {exc}") from exc
    if not html:
        raise GenerationFailed(
            "UX Pilot returned no HTML for the generated design"
            + (f" {design_id}" if design_id else ""))

    _record(svc.output_dir, page_id, {
        "page": page_id, "designId": design_id, "briefHash": digest,
        "html": html, "previewUrl": preview, "prompt": prompt,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    return GeneratedDesign(page_id=page_id, design_id=design_id, html=html,
                           prompt=prompt, preview_url=preview)


# ---------------------------------------------------------------------------
# HTML → tree → bound tree
# ---------------------------------------------------------------------------

_ID_PROP = "_figmaNodeId"
_TEXT_TYPES = ("Heading", "Text")
_BUTTON_TYPES = ("Button", "IconButton")


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _stamp_ids(root: dict) -> None:
    """Give every node an identity `realize` can address. The HTML transform
    emits none; a frame's come from Figma."""
    counter = 0

    def walk(node: Any) -> None:
        nonlocal counter
        if not isinstance(node, dict):
            return
        counter += 1
        props = node.setdefault("props", {})
        if isinstance(props, dict):
            props[_ID_PROP] = f"ux{counter}"
        for child in node.get("children") or []:
            walk(child)

    walk(root)


def _strip_ids(node: Any) -> Any:
    if isinstance(node, dict):
        props = node.get("props")
        if isinstance(props, dict) and _ID_PROP in props:
            node["props"] = {k: v for k, v in props.items() if k != _ID_PROP}
        for child in node.get("children") or []:
            _strip_ids(child)
    return node


def _node_id(node: dict) -> str:
    return str((node.get("props") or {}).get(_ID_PROP) or "")


def _parents(root: dict) -> dict[int, dict]:
    out: dict[int, dict] = {}

    def walk(node: dict) -> None:
        for child in node.get("children") or []:
            if isinstance(child, dict):
                out[id(child)] = node
                walk(child)

    walk(root)
    return out


def _text_leaves(node: dict) -> list[dict]:
    found: list[dict] = []

    def walk(n: Any) -> None:
        if not isinstance(n, dict):
            return
        if n.get("type") in _TEXT_TYPES and isinstance((n.get("props") or {}).get("content"), str):
            found.append(n)
        for c in n.get("children") or []:
            walk(c)

    walk(node)
    return found


def _has_number(node: dict) -> bool:
    from services.figma.realize import _NUMBER_RE

    return any(_NUMBER_RE.match(str((leaf.get("props") or {}).get("content") or ""))
               for leaf in _text_leaves(node))


def _ancestors(node: dict, parents: dict[int, dict], root: dict) -> list[dict]:
    """Nearest first, the root excluded."""
    out: list[dict] = []
    cur = parents.get(id(node))
    while cur is not None and cur is not root:
        out.append(cur)
        cur = parents.get(id(cur))
    return out


def _metric_region(leaf: dict, parents: dict[int, dict], root: dict) -> dict:
    """The tile around a metric's label: the nearest ancestor that also draws
    a number. Without one the label's own parent is the region, and `realize`
    replaces it whole."""
    chain = _ancestors(leaf, parents, root)
    for anc in chain:
        if _has_number(anc):
            return anc
    return chain[0] if chain else leaf


def _table_region(root: dict, labels: list[str], parents: dict[int, dict],
                  reserved: set[str]) -> dict | None:
    """The table around the column headers: the smallest subtree carrying
    most of them, widened to take its rows.

    The header row alone is the smallest match, and replacing only that left
    the generated example rows drawn beneath a live table — the fiction the
    whole module exists to discard. So the match climbs while the ancestor
    still holds nothing that belongs to something else on the page: no
    metric's label, no button's, not the page heading (``reserved``). The
    first ancestor that does is the page around the table; the one below it
    is the table, rows and all.
    """
    wanted = {_norm(l) for l in labels if _norm(l)}
    if not wanted:
        return None
    need = min(len(wanted), max(2, (len(wanted) + 1) // 2)) if len(wanted) > 1 else 1

    best: dict | None = None

    def walk(n: Any) -> set[str]:
        nonlocal best
        if not isinstance(n, dict):
            return set()
        hits: set[str] = set()
        own = _norm((n.get("props") or {}).get("content")) if n.get("type") in _TEXT_TYPES else ""
        if own in wanted:
            hits.add(own)
        for c in n.get("children") or []:
            hits |= walk(c)
        # Deepest wins: children are visited before the parent decides, and a
        # parent only replaces a child that did not already qualify.
        if len(hits) >= need and best is None and n is not root:
            best = n
        return hits

    walk(root)
    if best is None:
        return None

    region = best
    for anc in _ancestors(best, parents, root):
        texts = {_norm((leaf.get("props") or {}).get("content")) for leaf in _text_leaves(anc)}
        if texts & reserved:
            break
        region = anc
    return region


def _detail_route(doc: dict, page: dict, entity_id: str) -> str:
    for p in _live(doc.get("pages")):
        if p is page or not entity_id:
            continue
        if str((p.get("data") or {}).get("primaryEntity") or "") != entity_id:
            continue
        route = str(p.get("route") or "")
        if "[id]" in route:
            return route.replace("[id]", "{{id}}")
    return ""


def _create_route(doc: dict, entity_id: str) -> str:
    for p in _live(doc.get("pages")):
        if str((p.get("data") or {}).get("primaryEntity") or "") != entity_id:
            continue
        route = str(p.get("route") or "")
        if route.endswith("/new"):
            return route
    return ""


_CREATE_WORDS = ("create", "add", "new")


def bind_by_label(root: dict, doc: dict, page: dict) -> tuple[dict, list[dict], list[str]]:
    """Bind the generated tree to the page's data by the labels the prompt chose.

    Returns ``(root, dataSources, warnings)``. Three things are looked for:
    each metric widget's label (its tile becomes live), the entity's column
    headers (their table becomes a live list), and each button's label (it
    launches the workflow or opens the page it names). Anything unmatched is
    a warning, never a guess.
    """
    from services.blueprint.page_planner import page_brief
    from services.figma import realize as _realize

    page_id = str(page.get("id") or "")
    brief = page_brief(doc, page_id) if page_id else {}
    entity = brief.get("entity") or {}
    entity_id = str(entity.get("id") or "")
    entity_name = str(entity.get("name") or "")
    warnings: list[str] = []

    _stamp_ids(root)
    parents = _parents(root)
    leaves = _text_leaves(root)
    by_text: dict[str, dict] = {}
    for leaf in leaves:
        by_text.setdefault(_norm((leaf.get("props") or {}).get("content")), leaf)

    classifications: list[dict] = []
    filters_by_title: dict[str, dict] = {}

    for widget in _metric_widgets(brief):
        label = str(widget["label"])
        src = widget.get("dataSource") or {}
        fn = str(src.get("aggregation") or "count")
        if fn not in ("count", "sum", "avg", "min", "max"):
            warnings.append(f"metric \"{label}\" uses {fn}, which a tile cannot show live; left as drawn")
            continue
        leaf = by_text.get(_norm(label))
        if leaf is None:
            warnings.append(f"metric \"{label}\" was not found on the generated page; left unbound")
            continue
        region = _metric_region(leaf, parents, root)
        classifications.append({
            "nodeId": _node_id(region), "kind": "metric",
            "entity": _entity_name(doc, str(src.get("entity") or "")),
            "fn": fn, "valueField": src.get("field") or "",
            "title": label, "confidence": 1.0,
        })
        if src.get("filter"):
            filters_by_title[label] = dict(src["filter"])

    workflows = {_norm(w["name"]): str(w.get("id")) for w in _launched_here(doc, page_id)}
    action_labels = {_norm(a) for a in (page.get("actions") or []) if str(a).strip()}
    reserved = ({_norm(w["label"]) for w in _metric_widgets(brief)}
                | set(workflows) | action_labels | {_norm(page.get("name"))})

    cols = _column_defs(brief)
    if cols and entity_name:
        region = _table_region(root, [c["label"] for c in cols], parents, reserved)
        if region is None:
            warnings.append(f"the {_plural(entity_name)} table was not found on the generated page; left unbound")
        else:
            classifications.append({
                "nodeId": _node_id(region), "kind": "table", "entity": entity_name,
                "columns": [c["key"] for c in cols],
                "columnLabels": {c["key"]: c["label"] for c in cols},
                "title": _plural(entity_name), "confidence": 1.0,
                **({"rowHref": _detail_route(doc, page, entity_id)}
                   if _detail_route(doc, page, entity_id) else {}),
            })

    # `realize` deep-copies and rebuilds; the ids it matches are the ones
    # stamped above.
    root, sources, applied = _realize.realize(
        root, classifications,
        locale=str((doc.get("product") or {}).get("locale") or ""))
    for a in applied:
        flt = filters_by_title.get(str(a.get("title") or ""))
        if flt:
            for s in sources:
                if s.get("name") == a.get("source"):
                    s["filter"] = flt

    # Buttons: by label, against what this page may launch or open. The
    # HTML transform hands an unbound <button> over as Text — a control that
    # would do nothing is not a control — so a text leaf carrying a wanted
    # label becomes the Button it was generated as, now with something to do.
    create_route = _create_route(doc, entity_id)
    wanted_buttons = set(workflows) | action_labels
    seen_buttons: set[str] = set()

    def _binding_for(label: str) -> dict | None:
        if label in workflows:
            return {"workflow": workflows[label]}
        if label in action_labels and create_route and label.split(" ")[0] in _CREATE_WORDS:
            return {"navigate": create_route}
        return None

    def bind_buttons(n: Any) -> Any:
        if not isinstance(n, dict):
            return n
        props = n.get("props") or {}
        if n.get("type") in _BUTTON_TYPES or n.get("type") in _TEXT_TYPES:
            text = props.get("label") if n.get("type") in _BUTTON_TYPES else props.get("content")
            label = _norm(text)
            binding = _binding_for(label) if label in wanted_buttons else None
            if binding is not None:
                seen_buttons.add(label)
                if n.get("type") in _BUTTON_TYPES:
                    kept = {k: v for k, v in props.items() if k not in ("workflow", "navigate")}
                    return {**n, "props": {**kept, **binding}}
                return {"type": "Button",
                        "props": {"label": str(text), "variant": "primary", **binding},
                        "children": []}
        kids = n.get("children")
        if isinstance(kids, list):
            n["children"] = [bind_buttons(c) for c in kids]
        return n

    root = bind_buttons(root)
    for label in sorted(wanted_buttons - seen_buttons):
        warnings.append(f"button \"{label}\" was not found on the generated page, or has nothing to bind to")

    _strip_ids(root)
    return root, sources, warnings


@dataclass
class Outcome:
    """What the executor gets. ``root`` is None exactly when ``reason`` says why."""

    root: dict | None = None
    data_sources: list[dict] = field(default_factory=list)
    design_id: str = ""
    preview_url: str = ""
    warnings: list[str] = field(default_factory=list)
    reason: str = ""
    reused: bool = False


def compose(svc: Any, page: dict, *, app_root: str | Path, gateway: Any = None,
            feedback: str = "") -> Outcome:
    """The page as UX Pilot designed it, bound to this application's data.

    Generate (or reuse), HTML to tree through the same route a drawn UX Pilot
    page takes, chrome off, labels bound. Never raises: the executor reads
    ``reason`` and composes the page another way.
    """
    page_id = str(page.get("id") or "")
    try:
        design = generate(svc, page, gateway=gateway, feedback=feedback)
    except GenerationFailed as exc:
        return Outcome(reason=str(exc))

    try:
        from services.blueprint.figma_layout import _build_from_html
        from services.html_to_schema import extract_html_asset_urls

        schema, _assets = _run(_build_from_html(
            design.html, extract_html_asset_urls(design.html), str(app_root),
            title=str(page.get("name") or "") or None))
    except Exception as exc:  # noqa: BLE001 — the page is composed another way
        return Outcome(design_id=design.design_id,
                       reason=f"the generated HTML could not be read as a page: {type(exc).__name__}: {exc}")

    children = [c for c in (schema.get("children") or []) if isinstance(c, dict)]
    if not children:
        return Outcome(design_id=design.design_id, reason="the generated HTML produced no page content")
    root = children[0]

    # THE PROMPT SAID NO CHROME; A BACKSTOP FOR WHEN IT DREW SOME ANYWAY.
    try:
        from services.figma import chrome as _chrome

        rail = _chrome.lone_chrome(root)
        if rail:
            root, removed = _chrome.split(root, rail)
            if removed:
                logger.info("[uxpilot] %s: removed %d chrome subtree(s) the prompt asked not to draw",
                            page_id, len(removed))
    except Exception as exc:  # noqa: BLE001 — never the page
        logger.warning("[uxpilot] chrome split failed for %s: %s", page_id, exc)

    try:
        root, sources, warnings = bind_by_label(root, svc.doc, page)
    except Exception as exc:  # noqa: BLE001
        return Outcome(design_id=design.design_id,
                       reason=f"binding the generated page failed: {type(exc).__name__}: {exc}")

    return Outcome(root=root, data_sources=list(schema.get("dataSources") or []) + sources,
                   design_id=design.design_id, preview_url=design.preview_url,
                   warnings=warnings, reused=design.reused)
