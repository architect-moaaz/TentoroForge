"""What Forge can build today, as data, for a draft to be checked against.

A draft line that needs something names the kind it needs (the composer
picks from this list); the check reads the kind, never the words of the
line. `proven` is built and seen working on a live app; `unproven` is built
and not yet seen working end to end; `not_yet` is not built. Each entry
says what proved it, so the list can be corrected when a build does.
"""
from __future__ import annotations

STATUSES = ("proven", "unproven", "not_yet")

#: kind → (status, what it is, what proved it)
MAP: dict[str, tuple[str, str, str]] = {
    "roles": ("proven", "roles with their own screens and access", "every build"),
    "workflows": ("proven", "processes with steps, guards and refusals", "every build"),
    "analytics": ("proven", "charts and tiles as queries", "Data Collector 4, AquaTrack (2026-10-13)"),
    "file_upload": ("proven", "files and pictures on records", "kids apps, F&B (2026-10)"),
    "email": ("proven", "outbound email on events", "wired end to end (2026-09)"),
    "audit": ("proven", "every change on the record, hash-chained", "six-gap plan (2026-10-12)"),
    "encryption": ("proven", "sensitive fields sealed at rest", "368824cf (2026-10-12)"),
    "scheduling": ("proven", "clock-driven work", "six-gap plan (2026-10-12)"),
    "public_pages": ("proven", "pages without sign-in", "shops (2026-10)"),
    "guest": ("proven", "signed-out visitors owning rows (a cart)", "TCommerce (2026-10-06)"),
    "mobile_pwa": ("proven", "installs on a phone as a web app", "six-gap plan (2026-10-12)"),
    "push": ("unproven", "web push to installed apps", "built with per-app keys; not seen live"),
    "sso": ("unproven", "company sign-in (OIDC, SAML, magic link)", "proven on a bench against the mock issuer only"),
    "tenancy": ("unproven", "organisations with their own data", "six-gap plan; not seen live"),
    "payments": ("unproven", "card payments", "Stripe test mode only; no live charge"),
    "other_integration": ("unproven", "a second outside system beyond email", "declared, adapters per system"),
    "realtime": ("unproven", "live updates without reload", "useLive in the kit; not deployed"),
    "maps": ("unproven", "maps and places", "MapView in the kit; not deployed"),
    "image_search": ("unproven", "find pictures like this one", "pgvector + CLIP sidecar; uncommitted branch"),
    "ai_extraction": ("unproven", "reading documents into records", "aiExtractMany (2026-09-29)"),
    "i18n": ("unproven", "more than one language", "switch exists; not measured"),
    "offline": ("not_yet", "working without a connection", "shell-only worker"),
    "collaboration": ("not_yet", "several people editing the same thing live", "not built"),
    "store_app": ("not_yet", "an app in the App Store or Play Store", "Expo wrapper not built"),
    "video": ("not_yet", "video or voice calls", "not built"),
    "native_desktop": ("not_yet", "a desktop application", "not built"),
}
KINDS = tuple(MAP)


def check(needs: list[str]) -> list[dict]:
    out = []
    for kind in needs or []:
        status, what, proof = MAP.get(kind, ("not_yet", kind, "not a capability Forge knows"))
        out.append({"kind": kind, "status": status, "what": what, "proof": proof})
    return out


def cannot_yet(needs: list[str]) -> list[dict]:
    """The lines a person must know about before choosing: not built, or
    built and not yet seen working."""
    return [c for c in check(needs) if c["status"] != "proven"]


__all__ = ["MAP", "KINDS", "STATUSES", "check", "cannot_yet"]
