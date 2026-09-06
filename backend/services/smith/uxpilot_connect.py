"""Connect a UX Pilot page to the application, from a sentence.

The twin of :mod:`services.smith.figma_connect` for the second design tool.
Same rule (§42): Smith asks for the page and the NAME of the variable holding
the API key, never the key. Same output: a ``designSources`` record for
``figma_intelligence`` to fan out over, and the run that follows is the
ordinary DAG.
"""
from __future__ import annotations

import re
from typing import Any

from services.smith.figma_connect import _run, summarise

FIELDS = ("uxpilot_ref", "key_env")
DEFAULT_KEY_ENV = "UXPILOT_API_KEY"


class UxPilotConnectError(RuntimeError):
    """Carries no secret. The gateway redacts its own detail."""


def connect(output_dir: Any, *, uxpilot_ref: str, key_env: str,
            treat_as: str = "evidence", max_screens: int = 40,
            with_images: bool = True) -> dict[str, Any]:
    """Extract the page and attach it to the Blueprint.

    Returns ``{"record": <designSources entry>, "summary": <text>}``.
    """
    from services.uxpilot.credentials import (
        EnvKeyResolver, UxPilotCredential, UxPilotCredentialError,
    )
    from services.uxpilot.gateway import UxPilotGateway, UxPilotGatewayError
    from services.uxpilot.reference import extract
    from services.uxpilot.url import parse
    from services.figma.store import connect as attach, next_source_id

    target = parse(uxpilot_ref)
    if target is None:
        raise UxPilotConnectError(
            f"That does not look like a UX Pilot page: {uxpilot_ref!r}. I need "
            f"the page id, or the page's URL from UX Pilot."
        )
    ref_name = (key_env or "").strip()
    if not ref_name:
        raise UxPilotConnectError(
            "I need the NAME of the environment variable holding your UX Pilot "
            "API key — for example UXPILOT_API_KEY. Never paste the key itself: "
            "it would be written to the conversation log (§42)."
        )

    from services.blueprint.service import BlueprintService

    svc = BlueprintService.load(output_dir=str(output_dir))

    # The store first, the environment as fallback — the same seam Figma uses
    # (`services.figma.integrations`), read for the `uxpilot` provider.
    from services.figma.integrations import MappingResolver, config_for

    values = config_for(output_dir, provider="uxpilot")
    resolver = MappingResolver(values) if values.get(ref_name) else EnvKeyResolver()
    endpoint = (values.get("UXPILOT_MCP_URL") or "").strip()

    try:
        credential = UxPilotCredential(ref=ref_name)
    except UxPilotCredentialError as exc:
        raise UxPilotConnectError(str(exc)) from exc
    gateway = UxPilotGateway(credential=credential, resolver=resolver,
                             **({"endpoint": endpoint} if endpoint else {}))
    try:
        ref = _run(extract(gateway, target, source_id=next_source_id(svc.doc, "uxpilot"),
                           max_screens=max_screens, with_images=with_images))
    except UxPilotCredentialError as exc:
        raise UxPilotConnectError(
            f"I could not read a UX Pilot API key from {ref_name}: {exc}. Add it "
            f"under Settings → Integrations → UX Pilot, or export it in the "
            f"environment the backend runs in, then ask me again."
        ) from exc
    except UxPilotGatewayError as exc:
        raise UxPilotConnectError(f"UX Pilot {exc.kind}: {exc.detail}") from exc

    name = ref.screens[0].canvas if ref.screens else ""
    record = attach(svc, ref, name=name, treat_as=treat_as)
    return {"record": record, "summary": summarise(ref, record)}


_URL_RE = re.compile(r"https?://(?:[a-z0-9-]+\.)*uxpilot\.(?:ai|net)/[^\s<>\"')]+", re.I)
_PAGE_RE = re.compile(r"\bux\s*pilot\s+page\s+([A-Za-z0-9_-]{4,64})", re.I)
_ENV_NAME_RE = re.compile(r"\b([A-Z][A-Z0-9_]*(?:KEY|TOKEN)[A-Z0-9_]*)\b")


def find_in(text: str) -> dict | None:
    """The UX Pilot page a brief names, or None.

    Returns ``{"provider", "uxpilot_ref", "key_env", "treat_as"}``. The key is
    named, never held (§42): an environment variable NAME in the text wins,
    else ``UXPILOT_API_KEY``.
    """
    from services.uxpilot.url import parse as _parse

    m = _URL_RE.search(text or "") or _PAGE_RE.search(text or "")
    if not m:
        return None
    ref = m.group(0) if m.re is _URL_RE else m.group(1)
    if _parse(ref) is None:
        return None
    env = _ENV_NAME_RE.search(text or "")
    lower = (text or "").lower()
    treat_as = "reference" if ("as a reference" in lower or "as reference" in lower) else "specification"
    return {"provider": "uxpilot", "uxpilot_ref": ref,
            "key_env": env.group(1) if env else DEFAULT_KEY_ENV,
            "treat_as": treat_as}
