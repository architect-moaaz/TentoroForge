"""MOBILE-B — decrypted-credentials loader for the mobile-build endpoint.

Reads the org's ``platform_integrations`` rows for the three mobile
providers (``expo_eas``, ``apple_asc``, ``google_play``), decrypts them
using the platform crypto, and returns a typed :class:`MobileCredentials`
bundle.

Slice C consumes this to call the EAS Build REST API + optionally submit
to App Store Connect / Google Play. This module is deliberately narrow:
no network I/O, no side effects — just DB lookup + decrypt + shape.

The one hard-required credential is ``EXPO_EAS_TOKEN``. Without it the
platform can't call EAS at all, so we raise :class:`MissingRequired`.
The Apple / Google credentials are OPTIONAL — a preview APK build only
needs the EAS token; store submission needs the platform-specific keys.
Slice D's UI will surface which builds are available given the
credentials on file.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.platform_integration import PlatformIntegration
from services.platform_integrations_crypto import CryptoError, decrypt


class MissingRequired(ValueError):
    """Raised when the caller needs a credential that isn't configured.

    ``keys`` is the list of missing ``platform_integrations.key`` values
    so the API can surface exactly which fields the user still needs to
    fill in Settings → Integrations."""

    def __init__(self, message: str, keys: list[str]) -> None:
        super().__init__(message)
        self.keys = keys


# --------------------------------------------------------------------------- #
# Bundle                                                                       #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class AppleAscCredentials:
    """Apple App Store Connect credentials.

    All four fields must be present to submit to the App Store; a
    preview / device-only build only needs EAS. When any of these is
    missing, ``is_complete()`` returns False and the caller should
    refuse a production iOS build with a clear error.
    """
    team_id: Optional[str] = None
    key_id: Optional[str] = None
    issuer_id: Optional[str] = None
    private_key: Optional[str] = None

    def is_complete(self) -> bool:
        return all([self.team_id, self.key_id, self.issuer_id, self.private_key])


@dataclass(frozen=True)
class GooglePlayCredentials:
    """Google Play service account JSON blob."""
    service_account_json: Optional[str] = None

    def is_complete(self) -> bool:
        return bool(self.service_account_json)


@dataclass(frozen=True)
class MobileCredentials:
    """All the decrypted secrets Slice C needs to run an EAS build."""
    expo_eas_token: str
    apple: AppleAscCredentials = field(default_factory=AppleAscCredentials)
    google: GooglePlayCredentials = field(default_factory=GooglePlayCredentials)

    def can_submit_ios(self) -> bool:
        return self.apple.is_complete()

    def can_submit_android(self) -> bool:
        return self.google.is_complete()

    def missing_ios_keys(self) -> list[str]:
        gaps = []
        if not self.apple.team_id:
            gaps.append("APPLE_TEAM_ID")
        if not self.apple.key_id:
            gaps.append("APPLE_ASC_KEY_ID")
        if not self.apple.issuer_id:
            gaps.append("APPLE_ASC_ISSUER_ID")
        if not self.apple.private_key:
            gaps.append("APPLE_ASC_PRIVATE_KEY")
        return gaps

    def missing_android_keys(self) -> list[str]:
        return ["GOOGLE_PLAY_SERVICE_ACCOUNT_JSON"] if not self.google.is_complete() else []


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #

_MOBILE_PROVIDERS = ("expo_eas", "apple_asc", "google_play")


async def load_mobile_credentials(
    org_id: uuid.UUID,
    db: AsyncSession,
) -> MobileCredentials:
    """Fetch + decrypt all mobile-build credentials for ``org_id``.

    Returns a :class:`MobileCredentials` bundle. The EAS token is
    required — raises :class:`MissingRequired` when it's absent so the
    caller can surface "please add your EAS token to
    Settings → Integrations" in a single 400 response. Apple / Google
    credentials are optional; the caller checks ``can_submit_ios`` /
    ``can_submit_android`` before offering those builds in the UI.

    Rows with ``value_ct=None`` (cleared but not deleted) count as
    "not set" — same semantics as the settings API.
    """
    stmt = select(PlatformIntegration).where(
        PlatformIntegration.org_id == org_id,
        PlatformIntegration.provider.in_(_MOBILE_PROVIDERS),
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    values: dict[str, str] = {}
    for row in rows:
        if not row.value_ct or not row.value_iv:
            continue
        try:
            values[row.key] = decrypt(row.provider, row.value_ct, row.value_iv)
        except CryptoError:
            # Skip individual bad rows rather than fail the whole load.
            # The UI would show these as "not set" and the user can re-enter.
            continue

    eas_token = values.get("EXPO_EAS_TOKEN")
    if not eas_token:
        raise MissingRequired(
            "This org hasn't configured an Expo EAS access token — mobile "
            "builds can't run without it. Add EXPO_EAS_TOKEN in "
            "Settings → Integrations, then try again.",
            keys=["EXPO_EAS_TOKEN"],
        )

    return MobileCredentials(
        expo_eas_token=eas_token,
        apple=AppleAscCredentials(
            team_id=values.get("APPLE_TEAM_ID"),
            key_id=values.get("APPLE_ASC_KEY_ID"),
            issuer_id=values.get("APPLE_ASC_ISSUER_ID"),
            private_key=values.get("APPLE_ASC_PRIVATE_KEY"),
        ),
        google=GooglePlayCredentials(
            service_account_json=values.get("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON"),
        ),
    )
