"""The user's Figma token, held where it cannot leak (PRD §42, §97, §99).

§42 is a list of places the raw credential must never come to rest::

    chat history · Blueprint · generated source · export · application logs

Four of those five are things this platform writes on purpose, and the fifth
is the one that leaks by accident. A token passed around as a plain string
eventually reaches all of them — it gets attached to a run record "for
debugging", interpolated into an error message, or serialised into a Blueprint
field because the field accepted a string.

So the token is never a value this system holds. What it holds is a
:class:`FigmaCredential` — a *reference* — and the raw secret is resolved from
the secrets service (§97) at the moment of the call, inside the gateway, and
discarded when the call returns.

The resolver seam
-----------------
:class:`SecretResolver` is a protocol, not a class to inherit. The platform's
real secrets service implements it; :class:`EnvSecretResolver` implements it
against the environment so a developer can drive a live extraction without a
secrets backend existing yet. Both satisfy §42, because neither lets the raw
value reach a caller that isn't the gateway.

This is a seam, not a fallback: there is no code path that tries one and
silently degrades to the other. The application chooses its resolver once, at
construction.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Protocol


#: Figma personal access tokens. The modern form is ``figd_`` followed by a
#: URL-safe blob; older tokens are a bare UUID-ish string. Both are matched so
#: :func:`redact` catches a token that reached a log by any route.
_TOKEN_SHAPES = (
    re.compile(r"figd_[A-Za-z0-9_-]{20,}"),
    re.compile(r"figu_[A-Za-z0-9_-]{20,}"),
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"),
)

REDACTED = "[figma-token-redacted]"


class FigmaCredentialError(RuntimeError):
    """The credential could not be resolved. Never carries the secret."""


@dataclass(frozen=True)
class FigmaCredential:
    """A handle to a token, not the token.

    This is the only credential shape allowed to cross a module boundary, and
    the only one safe to attach to a run record: ``ref`` names a secret, and
    naming a secret is not disclosing it.
    """

    #: Opaque key into the secrets service.
    ref: str
    #: Which Figma account/workspace this belongs to, for display only.
    label: str = ""

    def __post_init__(self) -> None:
        if not self.ref or not self.ref.strip():
            raise FigmaCredentialError("credential ref is empty")
        if looks_like_token(self.ref):
            # Someone passed the raw token where the reference belongs. Failing
            # loudly here is the whole point: accepted quietly, this value goes
            # on to be stored in exactly the five places §42 forbids.
            raise FigmaCredentialError(
                "credential ref looks like a raw Figma token; pass a secrets "
                "reference, not the token itself (§42)"
            )

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"FigmaCredential(ref={self.ref!r})"


class SecretResolver(Protocol):
    """§97's Secrets Service, narrowed to the one operation Figma needs."""

    def resolve(self, ref: str) -> str:
        """Return the raw secret for ``ref``, or raise FigmaCredentialError."""
        ...


class EnvSecretResolver:
    """Reads secrets from the environment.

    For local development and live verification before the platform secrets
    service exists. ``ref`` is the environment variable name, so a developer
    exports ``FIGMA_PAT`` and passes ``FigmaCredential(ref="FIGMA_PAT")``.

    The value is read on every call rather than cached, so rotating the export
    and re-running picks up the new token without a restart.
    """

    def __init__(self, prefix: str = "") -> None:
        self._prefix = prefix

    def resolve(self, ref: str) -> str:
        name = f"{self._prefix}{ref}"
        value = os.environ.get(name, "").strip()
        if not value:
            raise FigmaCredentialError(
                f"no Figma token in environment variable {name!r}"
            )
        return value


def looks_like_token(text: str) -> bool:
    """True when ``text`` has the shape of a Figma access token."""
    return any(shape.search(text or "") for shape in _TOKEN_SHAPES)


def redact(text: str) -> str:
    """Replace anything token-shaped in ``text``.

    Applied to every string this package logs or raises. It is a backstop, not
    the control — the control is that the raw token only exists inside a
    gateway call frame. A backstop is still worth having, because the failure
    it prevents is unrecoverable: a token in a log is a token to rotate.
    """
    out = text or ""
    for shape in _TOKEN_SHAPES:
        out = shape.sub(REDACTED, out)
    return out
