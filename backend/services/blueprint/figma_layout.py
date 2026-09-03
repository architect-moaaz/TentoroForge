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

    try:
        schema, assets = _run(build_schema_from_jsx(
            code,
            str(app_root),
            route=str(page.get("route") or "") or None,
            title=str(page.get("name") or "") or None,
        ))
    except Exception as exc:  # noqa: BLE001 — one frame, never the run
        logger.warning("[figma] %s: %s", page.get("id"), exc)
        return None

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

    return {
        "root": root,
        "dataSources": list(schema.get("dataSources") or []),
        "assets": dict(assets or {}),
    }
