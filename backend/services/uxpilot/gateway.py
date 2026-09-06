"""The one controlled hop to UX Pilot (PRD §43, §98, §102, §103).

The same object :mod:`services.figma.gateway` is for Figma: every call goes
through here, and here is where authentication, the allowed operations,
request logging, rate limits and error classification live.

Read-only, deliberately
-----------------------
UX Pilot's server can generate, import, review and publish — every one of
those spends the user's credits. None is in :data:`ALLOWED_TOOLS`; the tools
here read a page and its designs and cost nothing.

Argument names come from the server
-----------------------------------
UX Pilot documents its tool names, not their parameters, and its toolset
revision moves independently of this code. So the gateway reads each tool's
input schema once per session and maps the semantic arguments the extraction
uses (``page``, ``design``, ``theme``, ``include_html``) onto whatever the
schema calls them. A rename on their side is a cache refresh, not a release.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from services.figma.gateway import _blocks_of, _text_of
from services.uxpilot.credentials import (
    SecretResolver,
    UxPilotCredential,
    UxPilotCredentialError,
    redact,
)

log = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "https://mcp.uxpilot.net/mcp"

#: The read tools. Anything that spends credits is absent on purpose.
ALLOWED_TOOLS = frozenset({
    "list_workstreams", "list_pages", "get_page_context",
    "get_design", "get_design_preview", "get_design_versions",
    "list_design_collections", "get_design_collection",
    "list_themes", "get_theme", "list_symbols", "get_symbol",
    "list_diagrams",
})

#: Semantic argument → the property names a tool schema might use for it.
_ARG_ALIASES: dict[str, tuple[str, ...]] = {
    "page": ("pageid", "page_id", "page", "pageuuid"),
    "design": ("designid", "design_id", "design", "designuuid", "id"),
    "theme": ("themeid", "theme_id", "theme", "id"),
    "include_html": ("includehtml", "include_html", "withhtml", "with_html", "html"),
}

UxPilotErrorKind = Literal[
    "config", "auth", "unreachable", "timeout", "not_allowed",
    "tool_error", "protocol", "unavailable",
]


class UxPilotGatewayError(RuntimeError):
    def __init__(self, kind: UxPilotErrorKind, detail: str) -> None:
        self.kind = kind
        self.detail = redact(detail)
        super().__init__(f"[{kind}] {self.detail}")


@dataclass
class CallRecord:
    tool: str
    duration_ms: int
    ok: bool
    error_kind: str = ""


@dataclass
class UxPilotGateway:
    """Controlled access to the UX Pilot MCP for one credential."""

    credential: UxPilotCredential
    resolver: SecretResolver
    endpoint: str = DEFAULT_ENDPOINT
    timeout_s: float = 60.0
    max_attempts: int = 3
    min_interval_s: float = 0.2

    calls: list[CallRecord] = field(default_factory=list)
    _last_call_at: float = field(default=0.0, repr=False)
    _schemas: dict[str, dict] | None = field(default=None, repr=False)

    # -- §98 authentication -------------------------------------------------

    def _headers(self) -> dict[str, str]:
        try:
            key = self.resolver.resolve(self.credential.ref)
        except UxPilotCredentialError as exc:
            raise UxPilotGatewayError("auth", str(exc)) from exc
        return {"Authorization": f"Bearer {key}"}

    # -- the call -------------------------------------------------------------

    async def call(self, tool: str, **semantic: Any) -> list[dict[str, Any]]:
        """Invoke one read tool and return its content blocks."""
        if tool not in ALLOWED_TOOLS:
            raise UxPilotGatewayError(
                "not_allowed",
                f"{tool!r} is not an allowed UX Pilot operation; "
                f"allowed: {', '.join(sorted(ALLOWED_TOOLS))}",
            )
        last: UxPilotGatewayError | None = None
        for attempt in range(1, self.max_attempts + 1):
            await self._respect_rate_limit()
            started = time.monotonic()
            try:
                args = await self._arguments(tool, semantic)
                blocks = await self._invoke(tool, args)
            except UxPilotGatewayError as exc:
                self._record(tool, started, ok=False, error_kind=exc.kind)
                if exc.kind in ("auth", "not_allowed", "config", "unavailable"):
                    raise
                last = exc
                if attempt < self.max_attempts:
                    await asyncio.sleep(self.min_interval_s * attempt * 5)
                continue
            self._record(tool, started, ok=True)
            return blocks
        assert last is not None
        raise last

    async def _arguments(self, tool: str, semantic: dict[str, Any]) -> dict[str, Any]:
        schemas = await self._tool_schemas()
        schema = schemas.get(tool)
        if schema is None:
            raise UxPilotGatewayError("protocol", f"the server does not expose {tool!r}")
        props = {str(k): v for k, v in (schema.get("properties") or {}).items()}
        lowered = {k.lower().replace("_", "").replace("-", ""): k for k in props}
        out: dict[str, Any] = {}
        for sem, value in semantic.items():
            for alias in _ARG_ALIASES.get(sem, (sem,)):
                key = lowered.get(alias.replace("_", ""))
                if key is not None:
                    out[key] = value
                    break
            else:
                required = [r for r in (schema.get("required") or []) if r in props]
                if sem in ("page", "design", "theme") and required and required[0] not in out:
                    out[required[0]] = value
        return out

    async def _tool_schemas(self) -> dict[str, dict]:
        if self._schemas is not None:
            return self._schemas
        async with self._session() as session:
            result = await session.list_tools()
        self._schemas = {
            t.name: dict(t.inputSchema or {}) for t in (result.tools or [])
        }
        return self._schemas

    def _session(self):
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client
        except ImportError as exc:
            raise UxPilotGatewayError(
                "unavailable", f"the mcp client library is not installed: {exc}"
            ) from exc
        from contextlib import asynccontextmanager

        headers = self._headers()
        endpoint = self.endpoint
        timeout_s = self.timeout_s

        @asynccontextmanager
        async def _open():
            try:
                async with asyncio.timeout(timeout_s):
                    async with streamablehttp_client(endpoint, headers=headers) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            yield session
            except UxPilotGatewayError:
                raise
            except TimeoutError as exc:
                raise UxPilotGatewayError("timeout", f"session exceeded {timeout_s}s") from exc
            except Exception as exc:  # noqa: BLE001 — mapped, not swallowed
                text = f"{type(exc).__name__}: {exc}"
                kind: UxPilotErrorKind = "auth" if "401" in text or "403" in text else "unreachable"
                raise UxPilotGatewayError(kind, text) from exc

        return _open()

    async def _invoke(self, tool: str, args: dict[str, Any]) -> list[dict[str, Any]]:
        async with self._session() as session:
            try:
                result = await session.call_tool(tool, arguments=args)
            except Exception as exc:  # noqa: BLE001
                raise UxPilotGatewayError("protocol", f"{type(exc).__name__}: {exc}") from exc
        if getattr(result, "isError", False):
            raise UxPilotGatewayError("tool_error", _text_of(result)[:400] or tool)
        return _blocks_of(result)

    # -- §98 rate limits and logging ---------------------------------------

    async def _respect_rate_limit(self) -> None:
        if self.min_interval_s <= 0:
            return
        gap = time.monotonic() - self._last_call_at
        if self._last_call_at and gap < self.min_interval_s:
            await asyncio.sleep(self.min_interval_s - gap)
        self._last_call_at = time.monotonic()

    def _record(self, tool: str, started: float, *, ok: bool, error_kind: str = "") -> None:
        record = CallRecord(tool=tool, duration_ms=int((time.monotonic() - started) * 1000),
                            ok=ok, error_kind=error_kind)
        self.calls.append(record)
        log.info("[uxpilot] %s %sms %s%s", tool, record.duration_ms,
                 "ok" if ok else "FAILED", f" ({error_kind})" if error_kind else "")
