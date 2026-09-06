"""UX Pilot as a DesignSource, over its hosted MCP server.

Server: ``https://mcp.uxpilot.net/mcp`` (Streamable HTTP, MCP 2025-11-25),
registered as an org-level :class:`PlatformMcpServer` row so the API key
stays in the encrypted store and every call goes through
:mod:`services.mcp_client`.

The four inputs map onto the server's read tools, none of which spend
credits:

- scope   → ``get_page_context`` (designs on the page) + ``list_diagrams``
- tokens  → ``get_theme`` when the page names one, else measured from HTML
- markup  → ``get_design`` with HTML included
- assets  → the shared downloader (URL in, local path out)

Tool argument names are read from each tool's input schema at call time
rather than hard-coded: the README documents tool names, not parameters,
and the server's toolset revision moves independently of this code.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Awaitable, Callable

from services.design_source.base import (
    DesignMarkup,
    DesignPage,
    DesignScope,
    DesignSourceError,
    DesignTokens,
)

logger = logging.getLogger(__name__)

UXPILOT_MCP_URL = "https://mcp.uxpilot.net/mcp"

#: Semantic argument → the property names a tool schema might use for it.
_ARG_ALIASES: dict[str, tuple[str, ...]] = {
    "page": ("pageid", "page_id", "page", "pageuuid"),
    "design": ("designid", "design_id", "design", "designuuid", "id"),
    "theme": ("themeid", "theme_id", "theme", "id"),
    "include_html": ("includehtml", "include_html", "withhtml", "with_html", "html"),
}

_HTML_MARK_RE = re.compile(r"<\s*(?:!doctype|html|body|div|section|main|header|nav)\b", re.I)

CallTool = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
ListTools = Callable[[], Awaitable[list[Any]]]


def parse_uxpilot_ref(ref: str) -> str:
    """A UX Pilot page id, from an id or a pasted page URL."""
    s = (ref or "").strip()
    if "://" in s:
        m = re.search(r"[?&]page(?:Id)?=([^&#]+)", s)
        if m:
            return m.group(1)
        parts = [p for p in s.split("?", 1)[0].split("#", 1)[0].split("/") if p]
        if parts:
            return parts[-1]
    return s


def _classify_type_from_name(name: str) -> str | None:
    from services.figma_plan_builder import _classify_type_from_name as _c

    return _c(name)


def _find_key(obj: Any, key: str) -> Any:
    """First value under ``key`` anywhere in a nested payload (case-insensitive)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() == key.lower():
                return v
        for v in obj.values():
            hit = _find_key(v, key)
            if hit is not None:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = _find_key(v, key)
            if hit is not None:
                return hit
    return None


def _first_str(obj: dict, keys: tuple[str, ...]) -> str:
    for k in keys:
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _find_html(obj: Any) -> str | None:
    if isinstance(obj, str):
        return obj if _HTML_MARK_RE.search(obj) else None
    if isinstance(obj, dict):
        for k in ("html", "content", "source", "markup"):
            v = obj.get(k)
            if isinstance(v, str) and _HTML_MARK_RE.search(v):
                return v
        for v in obj.values():
            hit = _find_html(v)
            if hit:
                return hit
    if isinstance(obj, list):
        for v in obj:
            hit = _find_html(v)
            if hit:
                return hit
    return None


def _walk_strings(obj: Any, path: str = ""):
    """Yield (key path, leaf) pairs. The path carries every ancestor key so
    ``{"font": {"body": "Inter"}}`` is seen as a font, not as a "body"."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v, path)
    else:
        yield path, obj


_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")


def tokens_from_theme(theme: Any) -> DesignTokens:
    """Measure a theme JSON without knowing its layout: hex strings are
    colours, strings under font keys are families, numbers under size /
    radius / spacing keys are what their key says."""
    colors: set[str] = set()
    fonts: set[str] = set()
    sizes: set[float] = set()
    radii: set[float] = set()
    spacings: set[float] = set()
    for key, val in _walk_strings(theme):
        k = key.lower()
        if isinstance(val, str):
            v = val.strip()
            if _HEX_RE.match(v):
                h = v[1:]
                if len(h) == 3:
                    h = "".join(c * 2 for c in h)
                colors.add("#" + h.upper())
            elif "font" in k and "size" not in k and "weight" not in k:
                fam = v.split(",")[0].strip().strip("'\"")
                if fam and not fam.startswith("var("):
                    fonts.add(fam)
            elif v.endswith("px"):
                try:
                    n = float(v[:-2])
                except ValueError:
                    continue
                if "radius" in k or "rounded" in k:
                    radii.add(n)
                elif "size" in k and "font" in k:
                    sizes.add(n)
                elif any(w in k for w in ("spacing", "gap", "padding", "space")):
                    spacings.add(n)
        elif isinstance(val, (int, float)) and not isinstance(val, bool):
            n = float(val)
            if n <= 0:
                continue
            if "radius" in k or "rounded" in k:
                radii.add(n)
            elif "fontsize" in k.replace("_", "").replace("-", ""):
                sizes.add(n)
            elif any(w in k for w in ("spacing", "gap", "padding")):
                spacings.add(n)
    return DesignTokens(
        colors=tuple(sorted(colors)), fonts=tuple(sorted(fonts)),
        font_sizes=tuple(sorted(sizes)), border_radii=tuple(sorted(radii)),
        spacings=tuple(sorted(spacings)),
    )


class UxPilotSource:
    provider = "uxpilot"

    def __init__(
        self,
        page_id: str,
        *,
        call_tool: CallTool,
        list_tools: ListTools,
        max_token_pages: int = 12,
    ) -> None:
        self.page_id = parse_uxpilot_ref(page_id)
        if not self.page_id:
            raise DesignSourceError("a UX Pilot page id is required")
        self.container: str = self.page_id
        self._call_tool = call_tool
        self._list_tools = list_tools
        self._max_token_pages = max_token_pages
        self._schemas: dict[str, dict] | None = None
        self._page_ctx: Any = None
        self._scope: DesignScope | None = None

    @classmethod
    def from_credentials(
        cls, page_id: str, api_key: str, url: str = UXPILOT_MCP_URL,
    ) -> "UxPilotSource":
        """Bind to the hosted server with a key the entry point already
        resolved from the org's MCP-server row. The pipeline holds the key
        for one run and never persists it."""
        from services import mcp_client

        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

        async def _call(name: str, args: dict[str, Any]) -> dict[str, Any]:
            return await mcp_client.call_tool_at(url, name, args, headers=headers)

        async def _tools() -> list[Any]:
            return await mcp_client.list_tools_at(url, headers=headers)

        return cls(page_id, call_tool=_call, list_tools=_tools)

    @classmethod
    def from_server(cls, server: Any, page_id: str) -> "UxPilotSource":
        """Bind to a :class:`PlatformMcpServer` row through the platform MCP
        client, which decrypts the row's key for each session."""
        from services import mcp_client

        async def _call(name: str, args: dict[str, Any]) -> dict[str, Any]:
            return await mcp_client.call_tool(server, name, args)

        async def _tools() -> list[Any]:
            return await mcp_client.list_tools(server)

        return cls(page_id, call_tool=_call, list_tools=_tools)

    # ---- tool plumbing ------------------------------------------------------

    async def _schema(self, tool: str) -> dict:
        if self._schemas is None:
            tools = await self._list_tools()
            self._schemas = {
                getattr(t, "name", None) or t.get("name"): dict(
                    getattr(t, "input_schema", None) or t.get("input_schema") or t.get("inputSchema") or {}
                )
                for t in tools
            }
        if tool not in self._schemas:
            raise DesignSourceError(f"UX Pilot server does not expose {tool!r}")
        return self._schemas[tool]

    async def _args(self, tool: str, semantic: dict[str, Any]) -> dict[str, Any]:
        schema = await self._schema(tool)
        props = {str(k): v for k, v in (schema.get("properties") or {}).items()}
        lowered = {k.lower().replace("_", "").replace("-", ""): k for k in props}
        out: dict[str, Any] = {}
        for sem, value in semantic.items():
            aliases = _ARG_ALIASES.get(sem, (sem,))
            for alias in aliases:
                key = lowered.get(alias.replace("_", ""))
                if key is not None:
                    out[key] = value
                    break
            else:
                # Fall back to the first required property for the primary id.
                required = [r for r in (schema.get("required") or []) if r in props]
                if sem in ("page", "design", "theme") and required and required[0] not in out:
                    out[required[0]] = value
        return out

    async def _call(self, tool: str, **semantic: Any) -> Any:
        args = await self._args(tool, semantic)
        result = await self._call_tool(tool, args)
        texts = [
            b.get("text", "") for b in (result.get("content") or [])
            if isinstance(b, dict) and b.get("type", "text") == "text"
        ]
        joined = "\n".join(t for t in texts if t)
        if result.get("isError"):
            raise DesignSourceError(f"{tool} failed: {joined[:300]}")
        structured = result.get("structuredContent")
        if structured is not None:
            return structured
        try:
            return json.loads(joined)
        except (json.JSONDecodeError, TypeError):
            return joined

    # ---- scope --------------------------------------------------------------

    async def _page_context(self) -> Any:
        if self._page_ctx is None:
            self._page_ctx = await self._call("get_page_context", page=self.page_id)
        return self._page_ctx

    async def scope(self) -> DesignScope:
        if self._scope is not None:
            return self._scope
        ctx = await self._page_context()
        designs = _find_key(ctx, "designs") or []
        if not isinstance(designs, list):
            designs = []
        name = ""
        if isinstance(ctx, dict):
            page = ctx.get("page") if isinstance(ctx.get("page"), dict) else ctx
            name = _first_str(page, ("name", "title", "pageName"))

        from services.figma_route_inferer import infer_route_from_frame_name

        pages: list[DesignPage] = []
        seen: dict[str, int] = {}
        for i, d in enumerate(designs):
            if not isinstance(d, dict):
                continue
            ref = _first_str(d, ("id", "designId", "design_id", "uuid"))
            if not ref:
                continue
            prompt = _first_str(d, ("prompt", "aiContext", "ai_context", "description"))
            title = _first_str(d, ("title", "name")) or (prompt[:40] if prompt else "") or f"Design {i + 1}"
            route = infer_route_from_frame_name(title)
            if route in seen:
                seen[route] += 1
                route = f"{route}-{seen[route]}"
            else:
                seen[route] = 1
            pages.append(DesignPage(
                route=route,
                title=title,
                ref=ref,
                kind=_classify_type_from_name(title),
                prompt=prompt,
                preview_url=_first_str(d, ("previewUrl", "preview_url", "imageUrl", "url")) or None,
            ))
        if not pages:
            raise DesignSourceError(f"UX Pilot page {self.page_id!r} has no designs")

        flows: tuple[dict, ...] = ()
        try:
            diagrams = await self._call("list_diagrams", page=self.page_id)
            items = _find_key(diagrams, "diagrams") if isinstance(diagrams, dict) else diagrams
            if isinstance(items, list):
                flows = tuple(d for d in items if isinstance(d, dict))
        except DesignSourceError as exc:
            logger.info("[uxpilot] no diagrams for page %s: %s", self.page_id, exc)

        self._scope = DesignScope(
            provider="uxpilot",
            container=self.page_id,
            name=name or f"UX Pilot page {self.page_id}",
            pages=tuple(pages),
            flows=flows,
            ref=self.page_id,
        )
        return self._scope

    # ---- tokens -------------------------------------------------------------

    async def tokens(self) -> DesignTokens:
        from services.html_to_schema import tokens_from_html

        tokens = DesignTokens()
        ctx = await self._page_context()
        theme_ref = _find_key(ctx, "themeId") or _find_key(ctx, "theme_id")
        if theme_ref is None:
            theme = _find_key(ctx, "theme")
            if isinstance(theme, dict):
                theme_ref = _first_str(theme, ("id", "themeId")) or None
            elif isinstance(theme, str):
                theme_ref = theme
        if theme_ref:
            try:
                theme = await self._call("get_theme", theme=str(theme_ref))
                tokens = tokens.merged(tokens_from_theme(theme))
            except DesignSourceError as exc:
                logger.info("[uxpilot] theme %s unavailable: %s", theme_ref, exc)

        scope = await self.scope()
        for page in scope.pages[: self._max_token_pages]:
            markup = await self.markup(page.ref)
            if markup is not None:
                tokens = tokens.merged(tokens_from_html(markup.source))
        return tokens

    # ---- markup -------------------------------------------------------------

    async def markup(self, ref: str) -> DesignMarkup | None:
        from services.html_to_schema import extract_html_asset_urls

        payload = await self._call("get_design", design=ref, include_html=True)
        html = _find_html(payload)
        if not html:
            return None
        return DesignMarkup(ref=ref, kind="html", source=html,
                            asset_urls=tuple(extract_html_asset_urls(html)))

    # ---- assets -------------------------------------------------------------

    async def assets(
        self, urls: list[str], output_dir: str, project_id: str | None = None,
    ) -> dict[str, str]:
        from services.figma_asset_downloader import download_figma_assets

        return await download_figma_assets(list(urls), output_dir, project_id=project_id)
