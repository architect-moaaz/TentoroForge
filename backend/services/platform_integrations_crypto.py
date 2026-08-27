"""Symmetric encryption for platform_integrations rows.

Mirrors the runtime-side crypto shape (HKDF → AES-GCM) but sits on the
platform, so credentials are decrypted only where the API + gen pipeline
need them.

  ct, iv = encrypt(provider, plaintext)
  plaintext = decrypt(provider, ct, iv)

Master secret: ``FORGE_INTEGRATIONS_SECRET`` env var. Distinct from
NEXTAUTH_SECRET on purpose — different context (platform DB, not
generated-app DB) so key rotation for one doesn't invalidate the other.

Per-provider subkey via HKDF-SHA256 with a versioned salt so we can
migrate to v2 later without invalidating rows.

Spec: docs/superpowers/specs/2026-07-22-integrations-settings.md.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


_HKDF_SALT = b"forge-platform-integrations-v1"
_KEY_LEN = 32  # AES-256


class CryptoError(RuntimeError):
    """Raised on missing/short master secret or decrypt failure."""


def _master_secret() -> bytes:
    s = os.environ.get("FORGE_INTEGRATIONS_SECRET", "")
    if len(s) < 16:
        raise CryptoError(
            "FORGE_INTEGRATIONS_SECRET missing or too short (need ≥16 chars). "
            "Set it in the platform's environment before configuring "
            "integrations; rotating it invalidates every stored value."
        )
    return s.encode("utf-8")


def _hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, length: int) -> bytes:
    """Minimal RFC-5869 HKDF-SHA256. Extract + expand (one L=32 block is enough
    for AES-256). Avoids adding a new dependency; `cryptography` provides the
    AES-GCM primitive but its HKDF import path is more clutter."""
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    okm = b""
    prev = b""
    counter = 1
    while len(okm) < length:
        prev = hmac.new(prk, prev + info + bytes([counter]), hashlib.sha256).digest()
        okm += prev
        counter += 1
    return okm[:length]


def _subkey(provider: str) -> bytes:
    return _hkdf_sha256(
        _master_secret(),
        salt=_HKDF_SALT,
        info=provider.encode("utf-8"),
        length=_KEY_LEN,
    )


def encrypt(provider: str, plaintext: str) -> tuple[str, str]:
    """Return (ciphertext_b64, iv_b64). Fresh 96-bit IV per encrypt."""
    if not isinstance(provider, str) or not provider:
        raise CryptoError("provider must be a non-empty string")
    if not isinstance(plaintext, str):
        raise CryptoError("plaintext must be a string")
    key = _subkey(provider)
    iv = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(iv, plaintext.encode("utf-8"), None)
    return (
        base64.b64encode(ct).decode("ascii"),
        base64.b64encode(iv).decode("ascii"),
    )


def decrypt(provider: str, ct_b64: str, iv_b64: str) -> str:
    """Return the decrypted plaintext. Raises CryptoError on any failure."""
    if not (isinstance(ct_b64, str) and isinstance(iv_b64, str)):
        raise CryptoError("ct and iv must be strings")
    key = _subkey(provider)
    try:
        pt = AESGCM(key).decrypt(
            base64.b64decode(iv_b64),
            base64.b64decode(ct_b64),
            None,
        )
    except Exception as exc:
        raise CryptoError(f"decrypt failed: {exc!r}") from exc
    return pt.decode("utf-8")
