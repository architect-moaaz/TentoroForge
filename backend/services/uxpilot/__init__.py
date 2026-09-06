"""UX Pilot as a creation mode, on the same seams as Figma (PRD §41-55).

The order things happen in, and where each lives::

    user names a page + the NAME of the variable holding the key
        url.parse              -> a target (the page id)          §41
        credentials            -> UxPilotCredential (a reference) §42
        gateway.UxPilotGateway -> the one hop to UX Pilot         §43, §98
        reference.extract      -> DesignReference                 §44, §47, §53

What comes out is the same :class:`services.figma.reference.DesignReference`
a Figma extraction produces — a UX Pilot design is a screen, the page is the
file — so the store, the intelligence brief, the design-system projection and
the layout projection read one shape whichever tool the design lives in.
Figma named those seams first; this package fills them.
"""
from __future__ import annotations

from services.uxpilot.credentials import (
    EnvKeyResolver,
    UxPilotCredential,
    UxPilotCredentialError,
    looks_like_key,
    redact,
)
from services.uxpilot.gateway import (
    ALLOWED_TOOLS,
    DEFAULT_ENDPOINT,
    UxPilotGateway,
    UxPilotGatewayError,
)
from services.uxpilot.reference import extract
from services.uxpilot.url import parse

__all__ = [
    "ALLOWED_TOOLS",
    "DEFAULT_ENDPOINT",
    "EnvKeyResolver",
    "UxPilotCredential",
    "UxPilotCredentialError",
    "UxPilotGateway",
    "UxPilotGatewayError",
    "extract",
    "looks_like_key",
    "parse",
    "redact",
]
