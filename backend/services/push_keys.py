"""The application's own push keys (VAPID): generated once per project,
kept across rebuilds, shipped with a publish.

A Web Push message is signed with an EC P-256 key pair the application
holds; a device subscribes against the PUBLIC half, so a rotated pair
orphans every subscription a device has made. The pair is therefore made
when the project is first assembled (`runtime_injector`), written to the
app's `.env.local` beside its other secrets, carried over a rebuild by
`assembly.existing_secrets`, and pushed to the deployment when the
deployment lacks it. The private key reaches nobody but the app.
"""
from __future__ import annotations

import base64

VAPID_KEYS = ("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT")


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate_vapid(subject: str = "mailto:notifications@example.com") -> dict[str, str]:
    """A fresh pair: the public key as the uncompressed P-256 point (65
    bytes, base64url), the private as its 32-byte scalar — the shapes
    `web-push` reads."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    scalar = private.private_numbers().private_value.to_bytes(32, "big")
    return {"VAPID_PUBLIC_KEY": _b64url(public), "VAPID_PRIVATE_KEY": _b64url(scalar), "VAPID_SUBJECT": subject}


def is_public_key(value: str) -> bool:
    """A base64url uncompressed P-256 point: 65 bytes starting 0x04."""
    try:
        pad = "=" * (-len(value) % 4)
        raw = base64.urlsafe_b64decode(value + pad)
    except Exception:  # noqa: BLE001
        return False
    return len(raw) == 65 and raw[0] == 4


__all__ = ["VAPID_KEYS", "generate_vapid", "is_public_key"]
