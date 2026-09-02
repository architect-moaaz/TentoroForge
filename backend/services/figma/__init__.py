"""Figma as a creation mode (PRD §4.3, §41-55).

The order things happen in, and where each lives::

    user pastes a link + connects a token
        url.parse            -> FigmaTarget           §41
        credentials          -> FigmaCredential       §42
        gateway.FigmaGateway -> the one hop to Figma  §43, §98
        reference.extract    -> DesignReference       §44, §47, §53, §55

What comes out is a *reference*, not an application. §48: Figma is strong
design evidence, not complete requirements. Smith reads the reference,
describes what it implies, asks about what it cannot show (§50), and the
Blueprint — not the Figma file — is what the DAG builds from. The design's job
downstream is to be the thing every page is composed against (§40, §52, §53).
"""
from __future__ import annotations

from services.figma.credentials import (
    EnvSecretResolver,
    FigmaCredential,
    FigmaCredentialError,
    SecretResolver,
    redact,
)
from services.figma.gateway import (
    ALLOWED_TOOLS,
    DEFAULT_ENDPOINT,
    FigmaGateway,
    FigmaGatewayError,
)
from services.figma.reference import (
    ComponentRef,
    DesignReference,
    DesignTokens,
    InteractionRef,
    ScreenRef,
    extract,
)
from services.figma.url import FigmaTarget, parse

__all__ = [
    "ALLOWED_TOOLS",
    "ComponentRef",
    "DEFAULT_ENDPOINT",
    "DesignReference",
    "DesignTokens",
    "EnvSecretResolver",
    "FigmaCredential",
    "FigmaCredentialError",
    "FigmaGateway",
    "FigmaGatewayError",
    "FigmaTarget",
    "InteractionRef",
    "ScreenRef",
    "SecretResolver",
    "extract",
    "parse",
    "redact",
]
