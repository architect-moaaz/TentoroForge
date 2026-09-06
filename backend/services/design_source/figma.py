"""Figma as a DesignSource.

Wraps the modules the Figma-only pipeline already had: the REST plan
builder for scope, the styles walker for tokens, the Dev Mode MCP client
for markup with the REST node-tree mapper as its fallback, the CDN
downloader for assets. Nothing here is new behaviour; it is the existing
behaviour behind the provider-neutral contract, so the pipeline body has
no Figma-only block left.

Markup comes in two kinds. When the Dev Mode MCP answers, a page is its
JSX (exact styles, real assets). When it does not, the page's REST node
tree is walked and mapped deterministically into a PageV2 tree — the
``schema`` kind — with the frame's icons and logos exported as SVG first
so the mapping can point Image and Icon nodes at cached files.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from figma_parser import parse_figma_url
from services.design_source.base import (
    DesignMarkup,
    DesignPage,
    DesignScope,
    DesignSourceError,
    DesignTokens,
)

logger = logging.getLogger(__name__)


class FigmaSource:
    provider = "figma"

    def __init__(
        self, url: str, token: str | None, *,
        output_dir: str | None = None, project_id: str | None = None,
    ) -> None:
        try:
            parsed = parse_figma_url(url)
        except Exception as exc:  # noqa: BLE001 — the parser raises on non-Figma URLs
            raise DesignSourceError(f"not a Figma design URL: {url!r}") from exc
        if not parsed or not parsed.get("file_key"):
            raise DesignSourceError(f"not a Figma design URL: {url!r}")
        self.url = url
        self.token = token or ""
        self.container: str = parsed["file_key"]
        self.node_id: str | None = parsed.get("node_id")
        #: Where the REST fallback caches exported assets. Set by the pipeline
        #: through :meth:`bind`; ``markup`` on an unbound source skips the
        #: SVG export and maps without assets.
        self.output_dir = output_dir
        self.project_id = project_id
        self._scope: DesignScope | None = None
        self._docs: dict[str, dict] = {}
        self._walked: list[dict] = []
        self._mcp_reachable: bool | None = None

    def bind(self, output_dir: str, project_id: str | None = None) -> "FigmaSource":
        self.output_dir = output_dir
        self.project_id = project_id
        return self

    # ---- scope --------------------------------------------------------------

    async def scope(self) -> DesignScope:
        if self._scope is not None:
            return self._scope
        from services.figma_plan_builder import build_plan_from_figma

        plan = await build_plan_from_figma(self.url, self.token)
        pages = tuple(
            DesignPage(
                route=p["route"],
                title=p.get("name") or p["route"],
                ref=p["figma_node_id"],
                kind=p.get("type"),
            )
            for p in plan.get("pages") or []
            if p.get("figma_node_id")
        )
        self._scope = DesignScope(
            provider="figma",
            container=self.container,
            name=plan.get("name") or "Untitled",
            pages=pages,
            ref=self.url,
        )
        return self._scope

    # ---- REST node cache ----------------------------------------------------

    async def prefetch(self, refs: list[str]) -> None:
        """Fetch the REST node tree for every ref in one batched call, so the
        per-page fallback and the theme tokens share it."""
        from services.figma_client import fetch_figma_node_batched
        from services.figma_node_walker import walk_and_flatten

        wanted = [r for r in refs[:50] if r and r not in self._docs]
        if not wanted:
            return
        docs = await fetch_figma_node_batched(self.container, wanted, self.token)
        for ref, doc in docs.items():
            if doc:
                self._docs[ref] = doc
                self._walked.extend(walk_and_flatten(doc))

    async def _doc(self, ref: str) -> dict:
        if ref not in self._docs:
            await self.prefetch([ref])
        return self._docs.get(ref) or {}

    # ---- tokens -------------------------------------------------------------

    async def tokens(self) -> DesignTokens:
        """Measured from the same compact style tree the prefetch writes to
        ``styles.json``, over every page in scope."""
        from figma_tools import _extract_styles
        from services.figma_context import tokens_from_styles

        scope = await self.scope()
        await self.prefetch([p.ref for p in scope.pages])
        styles = {ref: _extract_styles(doc) for ref, doc in self._docs.items() if doc}
        if not styles:
            return DesignTokens()
        return DesignTokens.from_dict(tokens_from_styles(styles))

    def theme_tokens(self) -> dict[str, Any]:
        """The ``tokens.custom.json`` categories (colours, spacing, typography…)
        extracted from every node walked so far. Empty until ``prefetch``."""
        if not self._walked:
            return {}
        from services.figma_style_extractor import extract_tokens
        from services.figma_typography_extractor import extract_typography

        merged = extract_tokens(self._walked)
        merged["typography"] = extract_typography(self._walked)
        return merged

    # ---- markup -------------------------------------------------------------

    def frame_url(self, ref: str) -> str:
        return f"https://www.figma.com/design/{self.container}/frame?node-id={ref.replace(':', '-')}"

    async def reachable(self) -> bool:
        """Whether *some* markup path answers. The REST fallback always does
        when a token exists, so the import phase never skips a Figma source;
        this only decides whether Dev Mode JSX is tried first."""
        return bool(self.token) or await self._dev_mode_reachable()

    async def _dev_mode_reachable(self) -> bool:
        if self._mcp_reachable is not None:
            return self._mcp_reachable
        import urllib.request as _urllib_request
        from agents.figma_mcp_agent import FIGMA_MCP_URL

        if "127.0.0.1" not in FIGMA_MCP_URL and "localhost" not in FIGMA_MCP_URL:
            self._mcp_reachable = True
            return True
        try:
            _urllib_request.urlopen(_urllib_request.Request(FIGMA_MCP_URL, method="GET"), timeout=2)
            self._mcp_reachable = True
        except _urllib_request.HTTPError:
            self._mcp_reachable = True
        except Exception:  # noqa: BLE001 — URLError, timeout, refused
            self._mcp_reachable = False
        return self._mcp_reachable

    async def markup(self, ref: str) -> DesignMarkup | None:
        if await self._dev_mode_reachable():
            from agents.figma_mcp_agent import fetch_jsx_via_mcp
            from services.figma_asset_downloader import extract_asset_urls

            jsx = await fetch_jsx_via_mcp(self.frame_url(ref))
            if jsx:
                return DesignMarkup(ref=ref, kind="jsx", source=jsx,
                                    asset_urls=tuple(extract_asset_urls(jsx)))
            logger.info("[figma] Dev Mode returned no JSX for %s — mapping the node tree", ref)
        return await self._markup_from_node_tree(ref)

    async def _markup_from_node_tree(self, ref: str) -> DesignMarkup | None:
        """The deterministic mapper: REST node tree → PageV2, with the frame's
        icons and logos exported as SVG and cached first."""
        from services.figma_to_schema import build_page_schema

        doc = await self._doc(ref)
        if not doc:
            return None
        asset_paths = await self._export_vector_assets(doc)
        result = build_page_schema(doc, asset_paths=asset_paths)
        preview = await self._preview_url(ref)
        return DesignMarkup(
            ref=ref, kind="schema", source=json.dumps(result.page),
            preview_url=preview, incomplete=len(result.incomplete_nodes or []),
        )

    async def _export_vector_assets(self, doc: dict) -> dict[str, str]:
        """Export every Image / Icon / vector node in ``doc`` as SVG and cache
        it; returns ``{figma node id: local public path}`` for the mapper."""
        if not self.output_dir:
            return {}
        from services.figma_client import fetch_figma_image_urls
        from services.figma_name_classifier import classify
        from services.figma_node_walker import walk_and_flatten
        from services.figma_to_schema import _is_vector_only_frame

        walked = walk_and_flatten(doc)
        children_count: dict[str, int] = {}
        for entry in walked:
            pid = (entry.get("parent") or {}).get("id")
            if pid:
                children_count[pid] = children_count.get(pid, 0) + 1

        exportable: list[str] = []
        for entry in walked:
            n = entry["node"]
            fid = n.get("id")
            if not fid:
                continue
            schema_type, _ = classify(n.get("name") or "", n.get("type") or "")
            figma_type = n.get("type")
            if schema_type == "Image" and figma_type == "FRAME":
                bbox = n.get("absoluteBoundingBox") or {}
                w, h = bbox.get("width") or 0, bbox.get("height") or 0
                # A screenshot-sized frame with many children is a mockup,
                # not an image asset; a small vector-only frame is a logo.
                if not _is_vector_only_frame(n) and (
                    children_count.get(fid, 0) > 4 or w > 600 or h > 600
                ):
                    continue
            if schema_type in ("Icon", "Image") or figma_type in ("VECTOR", "BOOLEAN_OPERATION"):
                exportable.append(fid)
        if not exportable:
            return {}
        try:
            url_by_fid = await fetch_figma_image_urls(self.container, exportable, self.token, format="svg")
        except Exception as exc:  # noqa: BLE001 — the page still maps without icons
            logger.warning("[figma] SVG export failed: %s", exc)
            return {}
        if not url_by_fid:
            return {}
        url_to_path = await self.assets(list(url_by_fid.values()), self.output_dir, self.project_id)
        return {fid: url_to_path[url] for fid, url in url_by_fid.items() if url in url_to_path}

    async def _preview_url(self, ref: str) -> str | None:
        """A PNG rendering of the frame, for the refiner. Best effort."""
        from services.figma_client import fetch_figma_image_urls
        try:
            urls = await fetch_figma_image_urls(self.container, [ref], self.token, format="png")
        except Exception:  # noqa: BLE001
            return None
        return (urls or {}).get(ref)

    # ---- assets -------------------------------------------------------------

    async def assets(
        self, urls: list[str], output_dir: str, project_id: str | None = None,
    ) -> dict[str, str]:
        from services.figma_asset_downloader import download_figma_assets

        return await download_figma_assets(list(urls), output_dir, project_id=project_id)
