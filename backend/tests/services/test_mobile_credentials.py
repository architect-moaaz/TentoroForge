"""MOBILE-B tests — registry additions + credentials loader.

The registry test locks the exact ``ConfigKey`` shape for each mobile
provider so a UI drift (label rename, kind swap) is caught before it
ships. The loader tests exercise the DB → decrypt → typed-bundle path
with a fake session so no live Postgres is needed.
"""
from __future__ import annotations

import os
import uuid
from typing import Any

import pytest

from services.node_config_specs import all_providers, keys_for_provider
from services.mobile_credentials import (
    AppleAscCredentials,
    GooglePlayCredentials,
    MissingRequired,
    MobileCredentials,
    load_mobile_credentials,
)


# --------------------------------------------------------------------------- #
# Registry — provider + key shape                                              #
# --------------------------------------------------------------------------- #

class TestProviderRegistry:
    """Every mobile provider must be reachable via all_providers()."""

    def test_expo_eas_registered(self):
        assert "expo_eas" in all_providers()

    def test_apple_asc_registered(self):
        assert "apple_asc" in all_providers()

    def test_google_play_registered(self):
        assert "google_play" in all_providers()

    def test_expo_eas_has_required_token(self):
        keys = keys_for_provider("expo_eas")
        by_key = {k.key: k for k in keys}
        assert "EXPO_EAS_TOKEN" in by_key
        entry = by_key["EXPO_EAS_TOKEN"]
        # Password kind — never echoed back from GET.
        assert entry.kind == "password"
        # Required — no builds run without it.
        assert entry.required is True

    def test_apple_asc_has_four_fields(self):
        keys = {k.key for k in keys_for_provider("apple_asc")}
        assert keys == {
            "APPLE_TEAM_ID",
            "APPLE_ASC_KEY_ID",
            "APPLE_ASC_ISSUER_ID",
            "APPLE_ASC_PRIVATE_KEY",
        }

    def test_apple_asc_private_key_is_password_kind(self):
        """The .p8 blob is a secret — masked in the UI."""
        entry = next(
            k for k in keys_for_provider("apple_asc")
            if k.key == "APPLE_ASC_PRIVATE_KEY"
        )
        assert entry.kind == "password"

    def test_apple_asc_fields_are_optional(self):
        """Apple keys are optional at the registry level — an org
        that only ships Android doesn't need them. Slice C's endpoint
        gates iOS submission on `can_submit_ios`."""
        for entry in keys_for_provider("apple_asc"):
            assert entry.required is False, f"{entry.key} should be optional"

    def test_google_play_has_service_account_json(self):
        keys = {k.key for k in keys_for_provider("google_play")}
        assert keys == {"GOOGLE_PLAY_SERVICE_ACCOUNT_JSON"}


# --------------------------------------------------------------------------- #
# Bundle helpers                                                               #
# --------------------------------------------------------------------------- #

class TestBundleHelpers:
    def test_apple_incomplete_when_any_missing(self):
        assert not AppleAscCredentials().is_complete()
        assert not AppleAscCredentials(team_id="X").is_complete()
        assert not AppleAscCredentials(
            team_id="X", key_id="Y", issuer_id="Z"
        ).is_complete()

    def test_apple_complete_when_all_four_present(self):
        assert AppleAscCredentials(
            team_id="X", key_id="Y", issuer_id="Z", private_key="P",
        ).is_complete()

    def test_google_complete_only_with_json(self):
        assert not GooglePlayCredentials().is_complete()
        assert GooglePlayCredentials(service_account_json="{}").is_complete()

    def test_missing_ios_keys_lists_gaps(self):
        creds = MobileCredentials(
            expo_eas_token="tok",
            apple=AppleAscCredentials(team_id="X"),  # only 1 of 4
        )
        gaps = creds.missing_ios_keys()
        assert "APPLE_TEAM_ID" not in gaps
        assert set(gaps) == {
            "APPLE_ASC_KEY_ID", "APPLE_ASC_ISSUER_ID", "APPLE_ASC_PRIVATE_KEY",
        }

    def test_missing_android_keys(self):
        creds = MobileCredentials(expo_eas_token="tok")
        assert creds.missing_android_keys() == ["GOOGLE_PLAY_SERVICE_ACCOUNT_JSON"]

    def test_can_submit_flags(self):
        creds = MobileCredentials(
            expo_eas_token="tok",
            apple=AppleAscCredentials(
                team_id="X", key_id="Y", issuer_id="Z", private_key="P",
            ),
            google=GooglePlayCredentials(service_account_json="{}"),
        )
        assert creds.can_submit_ios()
        assert creds.can_submit_android()


# --------------------------------------------------------------------------- #
# Loader — DB → decrypt → bundle                                               #
# --------------------------------------------------------------------------- #

class _FakeSession:
    """Minimal AsyncSession stand-in that returns pre-baked rows."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    async def execute(self, stmt):  # noqa: ARG002 — stmt ignored, we return all
        rows = self._rows
        class _Scalars:
            def all(self_inner):
                return rows
        class _Result:
            def scalars(self_inner):
                return _Scalars()
        return _Result()


def _row(provider: str, key: str, ct: str | None, iv: str | None):
    """Fake PlatformIntegration row — only the attributes the loader reads."""
    class _R:
        pass
    r = _R()
    r.provider = provider
    r.key = key
    r.value_ct = ct
    r.value_iv = iv
    return r


@pytest.fixture(autouse=True)
def _crypto_secret_env(monkeypatch):
    """The crypto module refuses to work without a 16+ char master
    secret; tests need to be self-contained so we set one."""
    monkeypatch.setenv("FORGE_INTEGRATIONS_SECRET", "a" * 32)


async def _run(coro):
    return await coro


class TestLoader:
    @pytest.mark.asyncio
    async def test_missing_eas_token_raises(self):
        sess = _FakeSession(rows=[])
        with pytest.raises(MissingRequired) as ei:
            await load_mobile_credentials(uuid.uuid4(), sess)  # type: ignore[arg-type]
        assert "EXPO_EAS_TOKEN" in ei.value.keys

    @pytest.mark.asyncio
    async def test_cleared_row_treated_as_unset(self):
        """A row with value_ct=None means the user cleared the field.
        Loader must NOT try to decrypt None (which would raise); it
        must treat that row as 'not set'."""
        sess = _FakeSession(rows=[
            _row("expo_eas", "EXPO_EAS_TOKEN", None, None),
        ])
        with pytest.raises(MissingRequired):
            await load_mobile_credentials(uuid.uuid4(), sess)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_bad_ciphertext_skipped_not_fatal(self):
        """One corrupted row shouldn't nuke the whole load."""
        # Encrypt one real token so the loader has SOMETHING to return.
        from services.platform_integrations_crypto import encrypt
        good_ct, good_iv = encrypt("expo_eas", "real-token-value")
        sess = _FakeSession(rows=[
            _row("expo_eas", "EXPO_EAS_TOKEN", good_ct, good_iv),
            # Random junk — decrypt raises CryptoError, must be skipped.
            _row("apple_asc", "APPLE_ASC_KEY_ID", "junkjunkjunk", "junk"),
        ])
        creds = await load_mobile_credentials(uuid.uuid4(), sess)  # type: ignore[arg-type]
        assert creds.expo_eas_token == "real-token-value"
        assert creds.apple.key_id is None  # skipped

    @pytest.mark.asyncio
    async def test_full_bundle_round_trip(self):
        """The happy path: every credential set, all decrypt cleanly."""
        from services.platform_integrations_crypto import encrypt
        rows = []
        secrets_map = {
            ("expo_eas", "EXPO_EAS_TOKEN"): "expo-tok-xyz",
            ("apple_asc", "APPLE_TEAM_ID"): "TEAM12345X",
            ("apple_asc", "APPLE_ASC_KEY_ID"): "KEY9876543",
            ("apple_asc", "APPLE_ASC_ISSUER_ID"): "8792ac91-1234-5678-abcd-ef0123456789",
            ("apple_asc", "APPLE_ASC_PRIVATE_KEY"): "-----BEGIN PRIVATE KEY-----\nblob\n-----END PRIVATE KEY-----",
            ("google_play", "GOOGLE_PLAY_SERVICE_ACCOUNT_JSON"): '{"type":"service_account"}',
        }
        for (prov, key), val in secrets_map.items():
            ct, iv = encrypt(prov, val)
            rows.append(_row(prov, key, ct, iv))
        sess = _FakeSession(rows=rows)

        creds = await load_mobile_credentials(uuid.uuid4(), sess)  # type: ignore[arg-type]
        assert creds.expo_eas_token == "expo-tok-xyz"
        assert creds.apple.team_id == "TEAM12345X"
        assert creds.apple.key_id == "KEY9876543"
        assert creds.apple.issuer_id.startswith("8792ac91")
        assert "BEGIN PRIVATE KEY" in creds.apple.private_key
        assert creds.google.service_account_json.startswith("{")
        assert creds.can_submit_ios()
        assert creds.can_submit_android()

    @pytest.mark.asyncio
    async def test_eas_only_still_returns_bundle(self):
        """The common preview-build case: only EAS token set, no
        Apple/Google. Loader returns successfully; UI decides what
        builds to offer based on can_submit_* flags."""
        from services.platform_integrations_crypto import encrypt
        ct, iv = encrypt("expo_eas", "just-the-token")
        sess = _FakeSession(rows=[_row("expo_eas", "EXPO_EAS_TOKEN", ct, iv)])
        creds = await load_mobile_credentials(uuid.uuid4(), sess)  # type: ignore[arg-type]
        assert creds.expo_eas_token == "just-the-token"
        assert not creds.can_submit_ios()
        assert not creds.can_submit_android()
        assert creds.missing_ios_keys()
        assert creds.missing_android_keys() == ["GOOGLE_PLAY_SERVICE_ACCOUNT_JSON"]
