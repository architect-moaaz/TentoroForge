"""Entry-point helpers for a design import: resolve the credential, build
the adapter, and turn the design into a plan plus a design context.

The routers call this once when a project is created from a design; the
pipeline later receives a :class:`PlanSource` carrying only what it needs
(the ref, the row id, and the key for this one run).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from services.design_source import DesignSource, DesignSourceError
from services.pipeline.source import PlanSource

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedDesign:
    source: DesignSource
    plan_source: PlanSource
    #: What to persist in plan metadata: never the secret.
    metadata: dict[str, Any]


#: Which MCP-server rows belong to which design provider, by host. Figma's
#: hosted MCP takes the same personal access token as its REST API, so one
#: row serves both clients.
_PROVIDER_HOST = {"uxpilot": "uxpilot", "figma": "figma.com"}
_PROVIDER_SERVER_URL = {"uxpilot": "https://mcp.uxpilot.net/mcp", "figma": "https://mcp.figma.com/mcp"}
_PROVIDER_LABEL = {"uxpilot": "UX Pilot", "figma": "Figma"}


def _provider_matches(provider: str, server_url: str) -> bool:
    return _PROVIDER_HOST.get(provider, provider) in (server_url or "").lower()


async def resolve_design_credential(
    db: Any, org_id: Any, provider: str, credential_id: str | None,
) -> tuple[str, str, str]:
    """(row id, server url, decrypted key) for the org's MCP-server row for
    ``provider``. With no id given, the org's only enabled row whose URL
    names the provider is used."""
    from sqlalchemy import select
    from models.platform_mcp_server import PlatformMcpServer
    from services.mcp_client import _decode_secret

    label = _PROVIDER_LABEL.get(provider, provider)
    row = None
    if credential_id:
        try:
            row_id = uuid.UUID(str(credential_id))
        except ValueError as exc:
            raise DesignSourceError(f"credential_id is not an id: {credential_id!r}") from exc
        row = await db.get(PlatformMcpServer, row_id)
        if row is None or str(row.org_id) != str(org_id):
            raise DesignSourceError("that MCP server is not registered for this organization")
        if not _provider_matches(provider, row.server_url):
            raise DesignSourceError(f"MCP server {row.name!r} is not a {label} server")
    else:
        result = await db.execute(
            select(PlatformMcpServer).where(
                PlatformMcpServer.org_id == org_id,
                PlatformMcpServer.enabled.is_(True),
            )
        )
        candidates = [r for r in result.scalars().all() if _provider_matches(provider, r.server_url)]
        if len(candidates) == 1:
            row = candidates[0]
        elif not candidates:
            raise DesignSourceError(
                f"no {label} MCP server is registered for this organization — add "
                f"{_PROVIDER_SERVER_URL.get(provider, '')} under Settings → MCP Servers"
            )
        else:
            raise DesignSourceError(f"several {label} MCP servers are registered — pick one")
    if not row.enabled:
        raise DesignSourceError(f"MCP server {row.name!r} is disabled")
    secret = _decode_secret(row) or ""
    if row.auth_kind != "none" and not secret:
        raise DesignSourceError(f"MCP server {row.name!r} has no key stored")
    return str(row.id), row.server_url, secret


async def resolve_uxpilot_credential(db: Any, org_id: Any, credential_id: str | None) -> tuple[str, str, str]:
    return await resolve_design_credential(db, org_id, "uxpilot", credential_id)


async def figma_token_for(
    design_meta: dict[str, Any] | None, *, db: Any = None, org_id: Any = None,
    legacy_token: str | None = None,
) -> tuple[str, str | None]:
    """(token, credential row id) for a Figma project.

    Order: the org's Figma MCP-server row named by ``design_meta.credential_id``
    (or the org's only one); then the ``FIGMA_TOKEN`` environment; then a
    token a pre-store plan persisted, for projects created before the row
    existed. An empty token means no Figma access.
    """
    import os

    meta = design_meta or {}
    credential_id = meta.get("credential_id")
    if db is not None and org_id is not None:
        try:
            row_id, _url, secret = await resolve_design_credential(db, org_id, "figma", credential_id)
            if secret:
                return secret, row_id
        except DesignSourceError as exc:
            if credential_id:
                # The plan names a row that no longer serves — say so rather
                # than silently building with a different token.
                raise
            logger.info("[design] no Figma MCP-server row for this org: %s", exc)
    env_token = os.environ.get("FIGMA_TOKEN", "").strip()
    if env_token:
        return env_token, None
    if legacy_token:
        return legacy_token.strip(), None
    return "", None


async def resolve_design(
    *, provider: str, ref: str, db: Any = None, org_id: Any = None,
    credential_id: str | None = None, token: str | None = None,
) -> ResolvedDesign:
    """Build the adapter and the PlanSource for one import request."""
    if provider == "figma":
        from services.design_source.figma import FigmaSource

        row_id: str | None = None
        secret = (token or "").strip()
        if not secret:
            # A pasted token is used once and never stored; otherwise the
            # org's Figma row (or FIGMA_TOKEN) supplies it.
            secret, row_id = await figma_token_for(
                {"credential_id": credential_id}, db=db, org_id=org_id,
            )
        if not secret:
            raise DesignSourceError(
                "no Figma access token: register Figma under Settings → MCP Servers "
                "or paste a personal access token"
            )
        source = FigmaSource(ref, secret)
        metadata: dict[str, Any] = {"provider": "figma", "ref": ref, "container": source.container}
        if row_id:
            metadata["credential_id"] = row_id
        return ResolvedDesign(
            source=source,
            plan_source=PlanSource.figma(url=ref, token=secret),
            metadata=metadata,
        )
    if provider == "uxpilot":
        from services.design_source.uxpilot import UxPilotSource, parse_uxpilot_ref

        row_id, url, secret = await resolve_design_credential(db, org_id, "uxpilot", credential_id)
        page_id = parse_uxpilot_ref(ref)
        source = UxPilotSource.from_credentials(page_id, secret, url=url)
        return ResolvedDesign(
            source=source,
            plan_source=PlanSource.uxpilot(page_id=page_id, credential_id=row_id, secret=secret),
            metadata={"provider": "uxpilot", "ref": page_id, "container": page_id, "credential_id": row_id},
        )
    raise DesignSourceError(f"unknown design provider: {provider!r}")


async def plan_source_from_metadata(
    design_meta: dict[str, Any], *, db: Any = None, org_id: Any = None,
) -> PlanSource:
    """Rebuild the PlanSource for an approved plan from what was persisted
    (provider, ref, credential row); the key is resolved again, never read
    from metadata."""
    provider = design_meta.get("provider")
    ref = design_meta.get("ref") or ""
    if provider == "uxpilot":
        row_id, _url, secret = await resolve_design_credential(db, org_id, "uxpilot", design_meta.get("credential_id"))
        return PlanSource.uxpilot(page_id=ref, credential_id=row_id, secret=secret)
    if provider == "figma":
        token, row_id = await figma_token_for(
            design_meta, db=db, org_id=org_id, legacy_token=design_meta.get("token"),
        )
        return PlanSource.figma(url=ref, token=token or None, credential_id=row_id)
    raise DesignSourceError(f"unknown design provider in plan metadata: {provider!r}")


async def import_design_plan(
    source: DesignSource, output_dir: str, description: str = "",
) -> dict[str, Any]:
    """Scope → plan, tokens → design-context.json. Returns the plan.

    The plan is the design's page list with the user's description
    attached; requirements beyond the pages (entities, workflows) come from
    the binding enrichment and the planner downstream.
    """
    from services.design_context import write_design_context

    scope = await source.scope()
    plan = scope.to_plan()
    if description:
        plan["description"] = description
    try:
        tokens = await source.tokens()
    except DesignSourceError as exc:
        logger.warning("[design_import] tokens unavailable for %s: %s", source.provider, exc)
        tokens = None
    if tokens is not None and not tokens.is_empty:
        write_design_context(
            output_dir,
            provider=source.provider,
            design_ref=scope.ref or scope.container,
            tokens=tokens.as_dict(),
        )
    else:
        logger.info("[design_import] %s supplied no tokens; the brief will be authored", source.provider)
    return plan


async def page_texts(source: DesignSource, plan: dict) -> dict[str, list[str]]:
    """Visible text per route, for the text-only binding enrichment. Best
    effort: a page whose markup cannot be fetched contributes nothing."""
    from services.html_to_schema import parse_html_tree
    from services.jsx_to_schema import JSXElement, _descendant_text, parse_jsx_tree
    from services.pipeline.phase_design_import import design_pages, page_ref

    out: dict[str, list[str]] = {}
    for page in design_pages(plan):
        try:
            markup = await source.markup(page_ref(page))
        except Exception as exc:  # noqa: BLE001
            logger.info("[design_import] text for %s skipped: %s", page.get("route"), exc)
            continue
        if markup is None:
            continue
        try:
            root = parse_html_tree(markup.source)[0] if markup.kind == "html" else parse_jsx_tree(markup.source)
        except Exception:  # noqa: BLE001
            continue
        texts: list[str] = []

        def _walk(node: Any) -> None:
            if isinstance(node, str):
                t = node.strip()
                if t:
                    texts.append(t)
            elif isinstance(node, JSXElement):
                for c in node.children:
                    _walk(c)

        _walk(root)
        out[page.get("route") or ""] = texts[:200]
    return out
