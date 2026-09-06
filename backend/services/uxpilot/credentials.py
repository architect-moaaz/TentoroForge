"""The UX Pilot API key as a reference, never a value (PRD §42).

Same shape as :mod:`services.figma.credentials`: what crosses a module
boundary, sits in a run record or is said in a Smith turn is the NAME of the
variable holding the key. The gateway resolves the value at the moment of the
call and discards it.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from services.figma.credentials import SecretResolver  # noqa: F401 — re-exported seam

#: UX Pilot keys are prefixed ``ep_``.
_KEY_SHAPES = (re.compile(r"ep_[A-Za-z0-9_-]{12,}"),)

REDACTED = "[uxpilot-key-redacted]"


class UxPilotCredentialError(RuntimeError):
    """The credential could not be resolved. Never carries the secret."""


@dataclass(frozen=True)
class UxPilotCredential:
    """A handle to a key, not the key."""

    #: Opaque key into the secrets service — the environment variable name.
    ref: str
    label: str = ""

    def __post_init__(self) -> None:
        if not self.ref or not self.ref.strip():
            raise UxPilotCredentialError("credential ref is empty")
        if looks_like_key(self.ref):
            raise UxPilotCredentialError(
                "credential ref looks like a raw UX Pilot key; pass a secrets "
                "reference, not the key itself (§42)"
            )

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"UxPilotCredential(ref={self.ref!r})"


class EnvKeyResolver:
    """Reads the key from the environment. ``ref`` is the variable name."""

    def __init__(self, prefix: str = "") -> None:
        self._prefix = prefix

    def resolve(self, ref: str) -> str:
        name = f"{self._prefix}{ref}"
        value = os.environ.get(name, "").strip()
        if not value:
            raise UxPilotCredentialError(
                f"no UX Pilot API key in environment variable {name!r}"
            )
        return value


def looks_like_key(text: str) -> bool:
    return any(shape.search(text or "") for shape in _KEY_SHAPES)


def redact(text: str) -> str:
    out = text or ""
    for shape in _KEY_SHAPES:
        out = shape.sub(REDACTED, out)
    return out
