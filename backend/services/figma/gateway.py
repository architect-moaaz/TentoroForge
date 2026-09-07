"""The one controlled hop to Figma (PRD §43, §98, §101, §102, §103).

§98 states the rule and the reason together: *"External MCP capabilities
should not be accessed in an uncontrolled way by every agent."* Every Figma
call in the platform goes through this object, and this object owns the six
things §98 lists — authentication, permissions, allowed operations, request
logging, rate limits, error handling — plus the secret isolation §42 demands.

Read-only, deliberately
-----------------------
The Figma MCP can write: it creates files, generates designs, uploads assets.
None of that is in :data:`ALLOWED_TOOLS`, and an attempt to call one raises
rather than being filtered out silently.

This is not defensive padding. The user connects a Figma file as the *visual
reference* for an app being built — the same role the file plays for a human
developer reading it. A platform that could write back to that file could
damage the reference it was asked to work from, and no requirement anywhere in
the PRD asks it to. §101 puts the boundary in the agent's own terms: the Figma
Intelligence Agent gets ``Figma MCP → design extraction → Blueprint evidence
creation``. Extraction and evidence. Not authorship.

Failure is a value, not an exception to swallow
-----------------------------------------------
§102 requires the system to distinguish a *Figma connection failure* from an
agent failure or an MCP failure, so :class:`FigmaGatewayError` carries a
``kind`` the orchestrator can act on. The legacy client returned ``None`` for
all of them, which made "your token is wrong" and "that frame has no content"
the same event, and neither reached the user.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from services.figma.credentials import (
    FigmaCredential,
    FigmaCredentialError,
    SecretResolver,
    redact,
)
from services.mcp_client import tool_result_is_error

log = logging.getLogger(__name__)


#: Figma's hosted MCP. The Dev Mode server on ``http://127.0.0.1:3845/mcp``
#: is the alternative, and it needs the desktop app running with the file
#: open — fine for a developer, not something a hosted platform can require
#: of a user. Overridable for local work; the default is what a real user hits.
DEFAULT_ENDPOINT = os.environ.get("FIGMA_MCP_URL", "https://mcp.figma.com/mcp")

#: §98 "allowed operations" / §101 "each agent receives only required tools".
#: Every entry is read-only and maps to something §44/§47/§53/§55 asks for.
ALLOWED_TOOLS: frozenset[str] = frozenset({
    # §44 — the file's pages, frames, sections and their geometry.
    "get_metadata",
    # §44/§53 — structure, hierarchy, Auto Layout, text, component instances.
    "get_design_context",
    # §47 — the design system as Figma itself records it: variables and styles.
    "get_variable_defs",
    # §53 — the visual reference a developer would look at. This is what makes
    # "does the build match the design" a checkable question rather than a
    # claim, so it is a first-class extraction input, not a debugging aid.
    "get_screenshot",
    # §46 — components already mapped to code, when the file carries them.
    "get_code_connect_map",
})

FigmaErrorKind = Literal[
    "config",       # no endpoint, malformed target
    "auth",         # token rejected or absent
    "unreachable",  # transport failed
    "timeout",
    "not_allowed",  # a tool outside ALLOWED_TOOLS
    "tool_error",   # Figma ran the tool and reported failure
    "protocol",     # response was not the shape the SDK promises
    "unavailable",  # the MCP SDK is not installed
]


class FigmaGatewayError(RuntimeError):
    """A Figma call failed, classified per §102 and carrying no secret."""

    def __init__(self, kind: FigmaErrorKind, detail: str) -> None:
        self.kind = kind
        self.detail = redact(detail)
        super().__init__(f"{kind}: {self.detail}")


@dataclass
class CallRecord:
    """§98 request logging. Holds the reference, never the token."""

    tool: str
    file_key: str
    node_id: str | None
    duration_ms: int
    ok: bool
    error_kind: str = ""


@dataclass
class FigmaGateway:
    """Controlled access to the Figma MCP for one credential.

    Constructed per extraction run, not shared: the credential it resolves
    belongs to one user, and a process-wide gateway would be a place for one
    user's token to be used for another user's file.
    """

    credential: FigmaCredential
    resolver: SecretResolver
    endpoint: str = DEFAULT_ENDPOINT
    timeout_s: float = 60.0
    #: §103 "tasks must be retryable". Transport and timeout failures retry;
    #: auth and not_allowed do not, because retrying a rejected token just
    #: rejects it again and counts against the rate limit.
    max_attempts: int = 3
    #: §98 rate limits. Minimum wall-clock gap between calls to Figma.
    min_interval_s: float = 0.2

    calls: list[CallRecord] = field(default_factory=list)
    _last_call_at: float = field(default=0.0, repr=False)

    # -- §98 authentication -------------------------------------------------

    def _headers(self) -> dict[str, str]:
        """Resolve the secret and build the auth header.

        The raw token exists only inside this frame and the ``headers`` dict
        handed to the transport. Nothing returns it, and nothing stores it.
        """
        try:
            token = self.resolver.resolve(self.credential.ref)
        except FigmaCredentialError as exc:
            raise FigmaGatewayError("auth", str(exc)) from exc

        if self._is_local:
            # The Dev Mode server authenticates by virtue of running as the
            # signed-in user; sending a bearer token to localhost would put a
            # credential on the wire for no benefit.
            return {}
        return {"Authorization": f"Bearer {token}"}

    @property
    def _is_local(self) -> bool:
        return "127.0.0.1" in self.endpoint or "localhost" in self.endpoint

    # -- §98 the call ------------------------------------------------------

    async def call(
        self,
        tool: str,
        *,
        file_key: str,
        node_id: str | None = None,
        **arguments: Any,
    ) -> list[dict[str, Any]]:
        """Invoke one Figma MCP tool and return its content blocks.

        Raises :class:`FigmaGatewayError` on every failure path, classified so
        the caller can tell "reconnect Figma" from "that frame is empty".
        """
        if tool not in ALLOWED_TOOLS:
            # §98: the gateway decides what may be called, and says so. A
            # silently-dropped call would look to the caller like a design
            # with nothing in it.
            raise FigmaGatewayError(
                "not_allowed",
                f"{tool!r} is not an allowed Figma operation; "
                f"allowed: {', '.join(sorted(ALLOWED_TOOLS))}",
            )
        if not file_key:
            raise FigmaGatewayError("config", "no Figma file key")

        args: dict[str, Any] = {"fileKey": file_key, **arguments}
        if node_id:
            args["nodeId"] = node_id

        last: FigmaGatewayError | None = None
        for attempt in range(1, self.max_attempts + 1):
            await self._respect_rate_limit()
            started = time.monotonic()
            try:
                blocks = await self._invoke(tool, args)
            except FigmaGatewayError as exc:
                self._record(tool, file_key, node_id, started, ok=False,
                             error_kind=exc.kind)
                if exc.kind in ("auth", "not_allowed", "config", "unavailable"):
                    raise
                last = exc
                if attempt < self.max_attempts:
                    # Linear backoff. Figma's limits are per-minute, so an
                    # exponential curve would idle far longer than it needs to.
                    await asyncio.sleep(self.min_interval_s * attempt * 5)
                continue
            self._record(tool, file_key, node_id, started, ok=True)
            return blocks

        assert last is not None
        raise last

    async def _invoke(self, tool: str, args: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client
        except ImportError as exc:
            raise FigmaGatewayError(
                "unavailable", f"the mcp client library is not installed: {exc}"
            ) from exc

        try:
            async with asyncio.timeout(self.timeout_s):
                async with streamablehttp_client(
                    self.endpoint, headers=self._headers()
                ) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.call_tool(tool, arguments=args)
        except FigmaGatewayError:
            raise
        except TimeoutError as exc:
            raise FigmaGatewayError(
                "timeout", f"{tool} exceeded {self.timeout_s}s"
            ) from exc
        except Exception as exc:  # noqa: BLE001 — mapped, not swallowed
            raise FigmaGatewayError("unreachable", f"{type(exc).__name__}: {exc}") from exc

        # `is_error`, not `isError` — under mcp 2.0 the camelCase name survives
        # only as a serialisation alias, so this raise had never fired and every
        # Figma tool error fell through to `_blocks_of` and was parsed as design
        # data. See `mcp_client.tool_result_is_error`.
        if tool_result_is_error(result):
            raise FigmaGatewayError("tool_error", _text_of(result)[:400] or tool)

        return _blocks_of(result)

    # -- §98 rate limits and logging ---------------------------------------

    async def _respect_rate_limit(self) -> None:
        if self.min_interval_s <= 0:
            return
        gap = time.monotonic() - self._last_call_at
        if self._last_call_at and gap < self.min_interval_s:
            await asyncio.sleep(self.min_interval_s - gap)
        self._last_call_at = time.monotonic()

    def _record(self, tool, file_key, node_id, started, *, ok, error_kind="") -> None:
        record = CallRecord(
            tool=tool,
            file_key=file_key,
            node_id=node_id,
            duration_ms=int((time.monotonic() - started) * 1000),
            ok=ok,
            error_kind=error_kind,
        )
        self.calls.append(record)
        log.info(
            "[figma] %s %s/%s %sms %s%s",
            tool, file_key, node_id or "-", record.duration_ms,
            "ok" if ok else "FAILED", f" ({error_kind})" if error_kind else "",
        )


# ---------------------------------------------------------------------------
# Result shaping
# ---------------------------------------------------------------------------

def _blocks_of(result: Any) -> list[dict[str, Any]]:
    """Normalise a ``CallToolResult`` into plain dicts.

    The SDK returns typed content objects; every consumer downstream wants
    dicts it can read without importing the SDK. Structured content, when the
    server sends it, is preferred over re-parsing text.
    """
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict) and structured:
        return [{"type": "structured", "data": structured}]

    blocks: list[dict[str, Any]] = []
    for item in getattr(result, "content", None) or []:
        kind = getattr(item, "type", None) or "text"
        if kind == "text":
            blocks.append({"type": "text", "text": getattr(item, "text", "") or ""})
        elif kind == "image":
            blocks.append({
                "type": "image",
                "mimeType": getattr(item, "mimeType", "") or "",
                "data": getattr(item, "data", "") or "",
            })
        else:
            blocks.append({"type": str(kind)})
    return blocks


def _text_of(result: Any) -> str:
    return "\n".join(
        b.get("text", "") for b in _blocks_of(result) if b.get("type") == "text"
    )
