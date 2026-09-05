"""A page built from the frame it was designed as, rather than composed.

`page_layouts` has one producer per page and two ways to get one. A2UI composes
a screen from the component catalog, which is right for a page nobody drew. A
page that WAS drawn should be the thing that was drawn.

The seam is `pages[].figmaFrame`. `page_design` sets it when a page is one of
the connected design's frames and omits it when nothing corresponds — so this
module is asked only about pages a person designed, and every other page falls
through to A2UI untouched. That is the mixed outcome on purpose: a design with
eight screens against a data model implying thirty pages should produce thirty
pages, eight of them pixel-accurate, not eight pages and a hole.

WHY NO SECOND FIGMA CALL
------------------------
`reference.extract` already asks `get_design_context` for every screen, and
`_structure_from_code` keeps what came back — the JSX under `structure.code`
and the CDN asset URLs under `structure.assets`. So the design is on disk
beside the Blueprint from the moment it is connected, and composing a page
costs no network at all. A frame that was never extracted, or was extracted
before the code path existed, simply has no `code` and falls through.

WHY THE TREES ARE INTERCHANGEABLE
---------------------------------
`jsx_to_schema` emits Container, Stack, Row, Grid, Text, Heading, Image, Form
and Checkbox. Every one is in `contracts/component-catalog.json`, the same
registry the engine renders `pageLayouts` from — so a Figma-derived tree and an
A2UI-composed tree are the same kind of object, stored in the same section and
rendered by the same code. This module returns the tree; the caller wraps it in
the same `ArtifactProposal` A2UI's result uses.

FALLING THROUGH IS NOT FAILING
------------------------------
Every branch that cannot produce a tree returns None, and None means "A2UI
composes this one". A missing extraction, an unparseable frame, an asset
download that fails — none of them may cost the page, because the page is
buildable without them. The one thing that would be worse than a composed page
is no page.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _run(coro: Any) -> Any:
    """Run the async pipeline from the orchestrator's synchronous executor."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def frame_of(page: dict) -> str:
    """The node id this page was designed as, or "" for a page that was not."""
    return str((page or {}).get("figmaFrame") or "").strip()


def screen_for(doc: dict, output_dir: str | Path, node_id: str) -> Any:
    """The extracted screen for ``node_id``, across every connected source.

    Searches sources rather than taking the first: a project may connect more
    than one file, and a frame belongs to exactly one of them. Returns None when
    the frame is not in any stored extraction — which happens legitimately when
    a Blueprint version is restored without its design payload (§93).
    """
    from services.figma import store

    for source in doc.get("designSources") or []:
        source_id = str(source.get("id") or "")
        if not source_id:
            continue
        try:
            ref = store.load(source_id, output_dir)
        except Exception:  # noqa: BLE001 — a bad store must not stop the build
            logger.warning("[figma] could not load %s", source_id)
            continue
        if ref is None:
            continue
        for screen in ref.screens:
            if screen.node_id == node_id:
                return screen
    return None


def compose(svc: Any, page: dict, *, app_root: str | Path) -> dict | None:
    """The page's frame as a renderable tree, or None to let A2UI compose it.

    Returns ``{"root": <node>, "dataSources": [...], "assets": {url: path}}``.

    `assets` is the download map: every CDN url the frame referenced against the
    local path now under ``public/figma/``. The srcs in the tree are already
    rewritten to those paths — a tree pointing at figma.com would render for as
    long as the CDN url lived and then silently stop.
    """
    node_id = frame_of(page)
    if not node_id:
        return None

    screen = screen_for(svc.doc, svc.output_dir, node_id)
    if screen is None:
        logger.info("[figma] %s names frame %s, which no extraction holds — "
                    "composing instead", page.get("id"), node_id)
        return None

    code = str((screen.structure or {}).get("code") or "")
    if not code:
        # An extraction that recorded the node tree rather than the code. §102
        # wants that visible as a thin reference, not as a broken page.
        logger.info("[figma] %s has no design_context code for %s — composing "
                    "instead", page.get("id"), node_id)
        return None

    from services.figma_mcp_pipeline import build_schema_from_jsx

    # THE FRAME'S OWN SIZE, WHICH THE EXTRACTION ALREADY RECORDED. Without it
    # the root's `size-full` resolves against the viewport, and every child
    # positioned against a 3902px-wide drawing lands somewhere else — which is
    # how a thirty-card dashboard rendered three cards and blank space.
    # THE CLOSED VOCABULARIES, WHICH NOTHING WAS SUPPLYING.
    #
    # `figma_llm_ctx` exists so a button's action can only ever name a route or
    # workflow this application actually defines — "the LLM cannot invent a
    # target that isn't in the supplied lists". Nothing called
    # `set_figma_llm_context`, so the lists were always empty, the guarded
    # classifier never ran, and every button fell through to keyword matching.
    #
    # That left a design with buttons unbuildable from either side: inventing a
    # target failed as "targets workflow 'dashboard', which this application
    # does not define", and inventing nothing failed as "Button 'Dashboard'
    # declares no action — it would do nothing". A real 15-screen design lost
    # every page to it. The lists are the way out, and the Blueprint has had
    # them all along.
    _set_action_vocabulary(svc.doc)

    try:
        cw = float(getattr(screen, "width", 0) or 0)
        ch = float(getattr(screen, "height", 0) or 0)
    except (TypeError, ValueError):
        cw = ch = 0.0
    canvas = (cw, ch) if cw > 0 and ch > 0 else None
    if canvas is None:
        logger.info("[figma] %s has no recorded frame size — composing flowed",
                    page.get("id"))

    try:
        schema, assets = _run(build_schema_from_jsx(
            code,
            str(app_root),
            route=str(page.get("route") or "") or None,
            title=str(page.get("name") or "") or None,
            canvas=canvas,
        ))
    except Exception as exc:  # noqa: BLE001 — one frame, never the run
        logger.warning("[figma] %s: %s", page.get("id"), exc)
        return None

    # THE DESIGN'S CHROME IS THE SHELL'S, NOT THIS PAGE'S.
    #
    # Every frame is drawn whole — rail, brand, page — and the rail is the
    # same subtree on every frame. Composed whole, each page carried its own
    # sidebar beside the scaffold's, and `/cases/new` (a modal route) put a
    # third inside a dialog. `chrome.shared_chrome` finds what every screen
    # shares; `split` takes it out and unwraps the frame's boxes so the shell
    # wraps content that is only content. A design with one frame, or frames
    # that share nothing, has no chrome and composes exactly as before.
    try:
        from services.figma import chrome as _chrome

        shared = _shared_chrome_for(svc)
        if shared:
            schema["children"][0], removed = _chrome.split(schema["children"][0], shared)
            if removed:
                logger.info("[figma] %s: removed %d chrome subtree(s)",
                            page.get("id"), len(removed))
    except Exception as exc:  # noqa: BLE001 — never the page
        logger.warning("[figma] chrome split failed for %s: %s", page.get("id"), exc)

    # A CARD ON A LIST PAGE OPENS THE ITEM, NOT THE LIST IT IS ON. The
    # classifier bound the card's title to the page's own route because it
    # does not know which page the card sits on; this step does.
    from services.figma import cards as _cards

    routes = [str(p.get("route") or "") for p in (svc.doc.get("pages") or [])]
    retargeted = _cards.bind_cards(schema["children"][0], str(page.get("route") or ""), routes)
    if retargeted:
        logger.info("[figma] %s: %d card(s) retargeted from the page itself",
                    page.get("id"), retargeted)

    # A PICTURE OF A CHART BECOMES A CHART, BEFORE PROVENANCE IS STRIPPED.
    #
    # `realize` finds its regions by `_figmaNodeId`, which the block below
    # removes — so this runs first or it finds nothing. Everything about it is
    # optional: no gateway, no classification, no confident binding all leave
    # the tree exactly as composed, which is the page that already renders.
    live_sources: list[dict] = []
    try:
        classified = _classify_regions(svc, page, code, screen, app_root)
        # A TABLE DRAWN AS TEXT is read from its layers rather than looked
        # at: header, first rows, the card's title. Bound to an entity it
        # becomes a live Table whose rows open the entity's detail page.
        classified = list(classified or []) + _classify_tables(svc, code)
        if classified:
            from services.figma import realize as _realize

            schema["children"][0], live_sources, applied = _realize.realize(
                schema["children"][0], classified)
            if applied:
                logger.info("[figma] %s: %d region(s) now live", page.get("id"),
                            len(applied))
    except Exception as exc:  # noqa: BLE001 — enrichment, never the page
        logger.warning("[figma] region pass failed for %s: %s",
                       page.get("id"), exc)

    # WHAT THE RENDERER WILL NOT RENDER DOES NOT BELONG IN THE BLUEPRINT.
    #
    # `_figmaNodeId` is provenance the transformer stamps on every node — Forge's
    # own metadata, not something a component draws.
    #
    # `style` IS KEPT. It was dropped while the renderer stripped it — storing
    # it would have claimed a fidelity the application did not have — and
    # `registry.ts` now forwards it beside `className` and `data-*`. Figma
    # expresses in it what Tailwind cannot: exact gradients, transforms, clip
    # paths. On one real dashboard that is 81 of 626 nodes.
    _DROP = ("_figmaNodeId",)

    def _strip_provenance(node: Any) -> Any:
        if isinstance(node, dict):
            props = node.get("props")
            if isinstance(props, dict) and any(k in props for k in _DROP):
                node["props"] = {k: v for k, v in props.items()
                                 if k not in _DROP}
            for child in node.get("children") or []:
                _strip_provenance(child)
        return node

    children = [_strip_provenance(c) for c in (schema.get("children") or [])]
    root = children[0] if children else None
    if not isinstance(root, dict):
        logger.info("[figma] %s produced no root node — composing instead",
                    page.get("id"))
        return None

    out = {
        "root": root,
        "dataSources": list(schema.get("dataSources") or []) + live_sources,
        "assets": dict(assets or {}),
    }
    if schema.get("_figmaCanvas"):
        out["canvas"] = schema["_figmaCanvas"]
    return out


def _set_action_vocabulary(doc: dict) -> None:
    """Give the action classifier this application's real routes and workflows.

    Best-effort: a doc without pages or workflows leaves the vocabulary empty,
    which is the behaviour every run had before this existed.
    """
    try:
        from services.figma_llm_ctx import set_figma_llm_context
    except Exception:  # noqa: BLE001
        return

    routes = [str(p.get("route") or "") for p in (doc.get("pages") or [])]
    routes = [r for r in routes if r.startswith("/")]

    # IDS ONLY, BECAUSE IDS ARE WHAT RESOLVE.
    #
    # This offered names as well as ids, reasoning that a model reading a
    # button recognises "Refund Approval Decision" more readily than
    # "FLOW-014". It does — and then binds to it, and the validator rejects the
    # page: "targets workflow 'Refund Approval Decision', which this
    # application does not define", because `functional_completeness` resolves
    # a button's `workflow` against `workflows[].id` alone. Offering a spelling
    # that cannot resolve manufactures the exact failure the closed vocabulary
    # exists to prevent.
    #
    # The cost is real: an opaque id is harder to choose correctly, so fewer
    # buttons bind to workflows. Routes carry their own meaning and do most of
    # the binding, and a button that binds to nothing now becomes Text rather
    # than an invalid control.
    # THE ID IS THE ONLY LEGAL SPELLING; THE NAME IS WHAT A LABEL CAN MATCH.
    # Offered as bare ids, "Approve" had nothing to match against FLOW-009
    # and every drawn action fell to text — in one fifteen-screen build not a
    # single button ran a workflow. Each entry now reads
    # "FLOW-009 — Refund Approval Decision: <trigger>"; the classifier
    # matches the label to the words and returns the id.
    workflows: list[str] = []
    seen: set[str] = set()
    for flow in doc.get("workflows") or []:
        value = str(flow.get("id") or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        name = str(flow.get("name") or "").strip()
        trigger = str((flow.get("trigger") or {}).get("detail") or "").strip()
        workflows.append(value + (f" — {name}" if name else "") + (f": {trigger[:120]}" if trigger else ""))

    try:
        set_figma_llm_context(routes=routes or None,
                              workflows=workflows or None)
    except Exception:  # noqa: BLE001 — an enrichment, never the page
        logger.info("[figma] could not set the action vocabulary")


def _classify_tables(svc: Any, code: str) -> list[dict]:
    """Drawn tables bound to entities, with the row link resolved."""
    from services.figma import tables as _tables
    try:
        drawn = _tables.drawn_tables(code)
        if not drawn:
            return []
        from services.blueprint.executors import AnthropicModel
        entities = (svc.doc.get("data") or {}).get("entities") or []
        found = _tables.classify_tables(AnthropicModel(max_tokens=4000), drawn, entities)
        for entry in found:
            route = _tables.detail_route_for_entity(svc.doc, entry["entity"])
            if route:
                entry["rowHref"] = _tables.row_link(route)
        return found
    except Exception as exc:  # noqa: BLE001 — an enrichment, never the page
        logger.warning("[figma] drawn-table binding failed: %s", exc)
        return []


def _classify_regions(svc: Any, page: dict, code: str, screen: Any,
                      app_root: str | Path) -> list[dict]:
    """What the frame's rectangles are, looked at rather than guessed.

    Kept in one guarded place because every part of it is allowed to be
    unavailable: a project with no Figma credential in its integrations, a
    frame with no recorded size, an endpoint that is not running. Each returns
    [] and the page composes from the drawing exactly as before.
    """
    from services.figma.credentials import EnvSecretResolver, FigmaCredential
    from services.figma.gateway import FigmaGateway
    from services.figma.integrations import (
        MappingResolver, config_for, endpoint_from,
    )
    from services.figma.regions import candidates
    from services.figma import vision

    width = float(getattr(screen, "width", 0) or 0)
    height = float(getattr(screen, "height", 0) or 0)
    regions = candidates(code, width, height)
    if not regions:
        return []

    file_key = ""
    for source in svc.doc.get("designSources") or []:
        file_key = str(source.get("fileKey") or source.get("file_key") or "")
        if file_key:
            break
    if not file_key:
        return []

    values = config_for(svc.output_dir)
    ref_name = "FIGMA_TOKEN"
    resolver = (MappingResolver(values) if values.get(ref_name)
                else EnvSecretResolver())
    gateway = FigmaGateway(credential=FigmaCredential(ref=ref_name),
                           resolver=resolver, endpoint=endpoint_from(values))

    shots = _run(vision.render_regions(gateway, file_key, regions, app_root))
    if not shots:
        return []

    from services.blueprint.executors import AnthropicModel

    entities = (svc.doc.get("data") or {}).get("entities") or []
    return vision.classify(AnthropicModel(max_tokens=8000), shots, entities)


#: Chrome per (project, designs) for the life of the process. The fan-out
#: composes twelve pages at once and each call would otherwise transform every
#: screen again; the rail does not change between pages of one run.
_CHROME_CACHE: dict[tuple, set[str]] = {}


def _shared_chrome_for(svc: Any) -> set[str]:
    """The fingerprints every screen of this application's designs share.

    NEVER THROUGH THE ACTION CLASSIFIER. `compose` sets the routes/workflows
    vocabulary before it transforms a page, so that page's buttons bind. The
    same vocabulary was still set when this transformed the OTHER fourteen
    screens for their fingerprints — and with it set, every button on every
    screen is a real classifier call. Fifteen screens, twenty-odd buttons each,
    twelve subjects at once: a run sat nine minutes in `page_layouts` without
    composing one page or rendering one crop. A fingerprint is types and text;
    the context is cleared for the transform and restored after.
    """
    key = (str(svc.output_dir),
           tuple(str(s.get("id") or "") for s in svc.doc.get("designSources") or []))
    cached = _CHROME_CACHE.get(key)
    if cached is not None:
        return cached

    from services.figma import chrome as _chrome
    from services.figma import store
    from services.figma_llm_ctx import (
        get_routes, get_workflows, reset_figma_llm_context, set_figma_llm_context,
    )
    from services.jsx_to_schema import transform_jsx_to_schema

    saved = (list(get_routes()), list(get_workflows()))
    reset_figma_llm_context()
    roots: list[dict] = []
    try:
        for source in svc.doc.get("designSources") or []:
            try:
                ref = store.load(str(source.get("id") or ""), svc.output_dir)
            except Exception:  # noqa: BLE001
                ref = None
            for screen in (ref.screens if ref else []):
                code = str((screen.structure or {}).get("code") or "")
                if not code:
                    continue
                try:
                    w, h = float(screen.width or 0), float(screen.height or 0)
                    canvas = (w, h) if w > 0 and h > 0 else None
                    roots.append(transform_jsx_to_schema(code, {}, canvas=canvas)["children"][0])
                except Exception:  # noqa: BLE001 — one frame, never the set
                    continue
    finally:
        set_figma_llm_context(routes=saved[0] or None, workflows=saved[1] or None)

    shared = _chrome.shared_chrome(roots)
    _CHROME_CACHE[key] = shared
    return shared
