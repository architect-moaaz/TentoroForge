"""Tests for services.platform_integrations_crypto — HKDF-derived
AES-GCM subkey per provider, backed by FORGE_INTEGRATIONS_SECRET.

Mirror of the runtime-side crypto shape: encrypt(provider, plaintext)
returns (ct_b64, iv_b64); decrypt(provider, ct, iv) round-trips.

Cross-provider isolation is enforced by the subkey — decrypting a
"resend" ciphertext with the "anthropic" subkey MUST fail. This is
the whole point of the HKDF-per-provider design.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _master_secret(monkeypatch):
    monkeypatch.setenv(
        "FORGE_INTEGRATIONS_SECRET",
        "test-master-secret-that-is-long-enough-1234567890",
    )


def test_round_trip_preserves_plaintext():
    from services.platform_integrations_crypto import encrypt, decrypt

    ct, iv = encrypt("resend", "re_secret_abc123")
    assert isinstance(ct, str) and isinstance(iv, str)
    assert decrypt("resend", ct, iv) == "re_secret_abc123"


def test_cross_provider_decrypt_fails():
    """A ciphertext from 'resend' MUST NOT decrypt under 'anthropic'."""
    from services.platform_integrations_crypto import encrypt, decrypt, CryptoError

    ct, iv = encrypt("resend", "should not leak")
    with pytest.raises(CryptoError):
        decrypt("anthropic", ct, iv)


def test_iv_uniqueness_per_encrypt():
    """Same plaintext + same provider → different IVs, different ciphertext.
    Guards against nonce reuse (catastrophic for AES-GCM)."""
    from services.platform_integrations_crypto import encrypt

    a = encrypt("resend", "same-plaintext")
    b = encrypt("resend", "same-plaintext")
    assert a[0] != b[0], "ciphertext must differ"
    assert a[1] != b[1], "IV must differ"


def test_missing_master_secret_raises(monkeypatch):
    from services.platform_integrations_crypto import encrypt, CryptoError

    monkeypatch.delenv("FORGE_INTEGRATIONS_SECRET", raising=False)
    with pytest.raises(CryptoError, match="FORGE_INTEGRATIONS_SECRET"):
        encrypt("resend", "x")


def test_short_master_secret_raises(monkeypatch):
    from services.platform_integrations_crypto import encrypt, CryptoError

    monkeypatch.setenv("FORGE_INTEGRATIONS_SECRET", "too-short")
    with pytest.raises(CryptoError, match="too short"):
        encrypt("resend", "x")


def test_empty_string_plaintext_round_trips():
    from services.platform_integrations_crypto import encrypt, decrypt

    ct, iv = encrypt("resend", "")
    assert decrypt("resend", ct, iv) == ""


def test_unicode_plaintext_round_trips():
    from services.platform_integrations_crypto import encrypt, decrypt

    val = "café ⇄ 🔒 — тест"
    ct, iv = encrypt("anthropic", val)
    assert decrypt("anthropic", ct, iv) == val


def test_provider_required():
    from services.platform_integrations_crypto import encrypt, CryptoError

    with pytest.raises(CryptoError, match="provider"):
        encrypt("", "x")
