"""Tests for the sensitive-column guard.

Every test pins one behaviour so a real-app regression reads as a
single failure with a legible message. The 4noe2jyh reference app
surfaced ``Password Hash`` in the Members list — the
``test_password_hash_dropped_from_members_table`` case is that bug
in miniature.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.sensitive_column_guard import (
    is_sensitive_column,
    strip_sensitive_columns,
)


# ── policy helper ───────────────────────────────────────────────────


class TestIsSensitiveColumn:
    def test_password_hash_variants_all_match(self):
        for key in (
            "passwordHash", "password_hash", "password-hash",
            "PasswordHash", "PASSWORD_HASH", "pwdHash", "pwd_hash",
        ):
            assert is_sensitive_column(key), key

    def test_reset_and_verify_tokens_match(self):
        for key in (
            "resetToken", "reset_token", "verifyToken",
            "verificationToken", "sessionToken", "refreshToken",
            "accessToken",
        ):
            assert is_sensitive_column(key), key

    def test_mfa_and_totp_secrets_match(self):
        for key in ("mfaSecret", "mfa_secret", "totpSecret", "twoFactorSecret"):
            assert is_sensitive_column(key), key

    def test_generic_secret_kinds_match(self):
        for key in (
            "apiSecret", "clientSecret", "privateKey",
            "encryptionKey", "webhookSecret",
        ):
            assert is_sensitive_column(key), key

    def test_ordinary_columns_never_match(self):
        # These are the false-positive cases the guard MUST NOT trip.
        # Bare ``token`` / ``secret`` are legitimate columns in many
        # domains (a payment token surfaces as *last-4 in the UI).
        #
        # Deliberate policy choice: any column whose name CONTAINS
        # "password" IS flagged, even edge cases like ``password_hint``
        # (see the paired ``test_password_containing_names_flagged``
        # below). The far-worse failure mode is a real
        # ``passwordHash`` column leaking into UI, so we accept
        # stripping the occasional legit ``password_hint`` list column
        # over risking that leak.
        for key in (
            "email", "fullName", "phone", "avatarUrl", "role",
            "token",           # bare — display-worthy in commerce
            "secret",          # bare — could be a menu-item name
            "keyType",         # a category, not a key
            "resetInstructions",
            "instructions",
            "notes",
        ):
            assert not is_sensitive_column(key), (
                f"false positive: {key} should NOT be flagged sensitive"
            )

    def test_password_containing_names_flagged(self):
        # Deliberate: ANY column with "password" in the name is
        # treated as sensitive. Documented trade-off — we'd rather
        # over-strip a rare ``password_hint`` column than under-strip
        # ``passwordHash`` because someone named it creatively.
        for key in ("password", "passwordHint", "password_hint",
                    "userPassword", "oldPassword"):
            assert is_sensitive_column(key), (
                f"expected {key} to be flagged sensitive"
            )

    def test_none_and_empty_return_false(self):
        assert is_sensitive_column(None) is False  # type: ignore
        assert is_sensitive_column("") is False


# ── strip_sensitive_columns walker ──────────────────────────────────


def _write_schema(root: Path, name: str, schema: dict) -> Path:
    p = root / "src" / "schemas" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    return p


class TestStripSensitiveColumns:
    def test_no_schemas_dir_no_ops(self, tmp_path):
        result = strip_sensitive_columns(tmp_path)
        assert result == {
            "scanned": 0,
            "changed": [],
            "table_columns_dropped": 0,
            "description_items_dropped": 0,
        }

    def test_password_hash_dropped_from_members_table(self, tmp_path):
        # Miniature of the 4noe2jyh bug: a Members list rendered
        # Password Hash. After the guard runs, only display-worthy
        # columns remain.
        _write_schema(tmp_path, "members.json", {
            "schemaVersion": "2",
            "id": "members",
            "route": "/members",
            "root": {
                "type": "Stack",
                "children": [
                    {
                        "type": "Table",
                        "props": {
                            "columns": [
                                {"key": "fullName", "label": "Full Name"},
                                {"key": "email", "label": "Email"},
                                {"key": "passwordHash", "label": "Password Hash"},
                                {"key": "phone", "label": "Phone"},
                                {"key": "role", "label": "Role"},
                            ],
                            "rows": "{{members}}",
                        },
                    },
                ],
            },
        })

        result = strip_sensitive_columns(tmp_path)
        assert result["table_columns_dropped"] == 1
        assert "members.json" in result["changed"]

        data = json.loads((tmp_path / "src" / "schemas" / "members.json").read_text(encoding="utf-8"))
        cols = data["root"]["children"][0]["props"]["columns"]
        keys = [c["key"] for c in cols]
        assert "passwordHash" not in keys
        assert keys == ["fullName", "email", "phone", "role"]

    def test_multiple_sensitive_columns_all_dropped(self, tmp_path):
        _write_schema(tmp_path, "users.json", {
            "root": {"type": "Table", "props": {"columns": [
                {"key": "email"},
                {"key": "passwordHash"},
                {"key": "verifyToken"},
                {"key": "mfaSecret"},
                {"key": "resetToken"},
            ]}},
        })
        result = strip_sensitive_columns(tmp_path)
        assert result["table_columns_dropped"] == 4

    def test_string_columns_also_dropped(self, tmp_path):
        # Some Tables use bare string keys instead of {key,label}.
        # The walker must handle both shapes.
        _write_schema(tmp_path, "users.json", {
            "root": {"type": "Table", "props": {
                "columns": ["email", "passwordHash", "role"],
            }},
        })
        result = strip_sensitive_columns(tmp_path)
        assert result["table_columns_dropped"] == 1
        data = json.loads((tmp_path / "src" / "schemas" / "users.json").read_text(encoding="utf-8"))
        assert data["root"]["props"]["columns"] == ["email", "role"]

    def test_nested_table_inside_card_inside_stack(self, tmp_path):
        # Real pages nest Tables 3–4 layers deep inside Card / Section
        # / Stack containers. The walker recurses through arbitrary
        # container types.
        _write_schema(tmp_path, "users.json", {
            "root": {"type": "Stack", "children": [
                {"type": "Section", "children": [
                    {"type": "Card", "children": [
                        {"type": "Table", "props": {"columns": [
                            {"key": "email"},
                            {"key": "passwordHash"},
                        ]}},
                    ]},
                ]},
            ]},
        })
        result = strip_sensitive_columns(tmp_path)
        assert result["table_columns_dropped"] == 1

    def test_description_list_items_dropped(self, tmp_path):
        # Detail-page DescriptionList — sensitive fields shouldn't
        # render there either.
        _write_schema(tmp_path, "user-detail.json", {
            "root": {"type": "DescriptionList", "props": {
                "items": [
                    {"key": "email", "label": "Email"},
                    {"key": "passwordHash", "label": "Password Hash"},
                    {"key": "role", "label": "Role"},
                ],
            }},
        })
        result = strip_sensitive_columns(tmp_path)
        assert result["description_items_dropped"] == 1
        data = json.loads(
            (tmp_path / "src" / "schemas" / "user-detail.json").read_text(encoding="utf-8")
        )
        keys = [it["key"] for it in data["root"]["props"]["items"]]
        assert "passwordHash" not in keys

    def test_description_item_children_dropped(self, tmp_path):
        # Some detail pages express fields as DescriptionItem children
        # instead of an items array — prune those too.
        _write_schema(tmp_path, "user-detail.json", {
            "root": {"type": "DescriptionList", "children": [
                {"type": "DescriptionItem", "props": {"field": "email"}},
                {"type": "DescriptionItem", "props": {"field": "passwordHash"}},
                {"type": "DescriptionItem", "props": {"field": "role"}},
            ]},
        })
        result = strip_sensitive_columns(tmp_path)
        assert result["description_items_dropped"] == 1
        data = json.loads(
            (tmp_path / "src" / "schemas" / "user-detail.json").read_text(encoding="utf-8")
        )
        kids = data["root"]["children"]
        fields = [c["props"]["field"] for c in kids]
        assert "passwordHash" not in fields

    def test_idempotent_second_run_finds_nothing(self, tmp_path):
        _write_schema(tmp_path, "users.json", {
            "root": {"type": "Table", "props": {"columns": [
                {"key": "email"}, {"key": "passwordHash"},
            ]}},
        })
        first = strip_sensitive_columns(tmp_path)
        assert first["table_columns_dropped"] == 1
        second = strip_sensitive_columns(tmp_path)
        # No sensitive columns remain — nothing to drop, no writes.
        assert second["table_columns_dropped"] == 0
        assert second["changed"] == []

    def test_non_table_nodes_ignored(self, tmp_path):
        # A Form field named ``passwordHash`` is NOT this guard's
        # concern (form scaffolder handles password fields explicitly).
        # This test pins that Form fields survive the sweep.
        _write_schema(tmp_path, "signup.json", {
            "root": {"type": "Form", "props": {
                "fields": [
                    {"name": "email", "type": "text"},
                    {"name": "password", "type": "password"},
                ],
            }},
        })
        result = strip_sensitive_columns(tmp_path)
        assert result["table_columns_dropped"] == 0
        # Form untouched
        data = json.loads((tmp_path / "src" / "schemas" / "signup.json").read_text(encoding="utf-8"))
        names = [f["name"] for f in data["root"]["props"]["fields"]]
        assert names == ["email", "password"]

    def test_ordinary_columns_never_dropped(self, tmp_path):
        _write_schema(tmp_path, "orders.json", {
            "root": {"type": "Table", "props": {"columns": [
                {"key": "id"}, {"key": "customerName"},
                {"key": "token"},     # bare token — display-worthy in commerce
                {"key": "amount"},
            ]}},
        })
        result = strip_sensitive_columns(tmp_path)
        assert result["table_columns_dropped"] == 0
        assert result["changed"] == []

    def test_malformed_schema_json_skipped_not_raised(self, tmp_path):
        # A broken JSON file must not stop the sweep — log + continue.
        (tmp_path / "src" / "schemas").mkdir(parents=True)
        (tmp_path / "src" / "schemas" / "broken.json").write_text(
            "{ not json", encoding="utf-8"
        )
        _write_schema(tmp_path, "users.json", {
            "root": {"type": "Table", "props": {"columns": [
                {"key": "email"}, {"key": "passwordHash"},
            ]}},
        })
        # Must not raise
        result = strip_sensitive_columns(tmp_path)
        # users.json still processed even though broken.json failed
        assert result["table_columns_dropped"] == 1
        assert "users.json" in result["changed"]


class TestStripSensitiveFromRegistry:
    """The composers' input must be clean, so their output can't be dirty.

    This is what retired the second post-composer sweep: the guard ran
    twice because the registry handed the composer a password hash, not
    because one pass was insufficient.
    """

    def test_drops_sensitive_from_list_shaped_fields(self):
        from services.sensitive_column_guard import strip_sensitive_from_registry

        reg = {"entities": {"User": {"fields": [
            {"name": "id"}, {"name": "passwordHash"},
            {"name": "email"}, {"name": "resetToken"},
        ]}}}
        cleaned, dropped = strip_sensitive_from_registry(reg)

        assert dropped == 2
        assert [f["name"] for f in cleaned["entities"]["User"]["fields"]] == ["id", "email"]

    def test_drops_sensitive_from_map_shaped_columns(self):
        from services.sensitive_column_guard import strip_sensitive_from_registry

        reg = {"entities": {"User": {"columns": {
            "id": "uuid", "password_hash": "text", "name": "text",
        }}}}
        cleaned, dropped = strip_sensitive_from_registry(reg)

        assert dropped == 1
        assert set(cleaned["entities"]["User"]["columns"]) == {"id", "name"}

    def test_does_not_mutate_the_input(self):
        from services.sensitive_column_guard import strip_sensitive_from_registry

        reg = {"entities": {"User": {"fields": [{"name": "id"}, {"name": "mfaSecret"}]}}}
        strip_sensitive_from_registry(reg)

        assert len(reg["entities"]["User"]["fields"]) == 2

    def test_bare_string_fields_are_handled(self):
        from services.sensitive_column_guard import strip_sensitive_from_registry

        reg = {"entities": {"User": {"fields": ["id", "clientSecret", "email"]}}}
        cleaned, dropped = strip_sensitive_from_registry(reg)

        assert dropped == 1
        assert cleaned["entities"]["User"]["fields"] == ["id", "email"]

    def test_benign_token_columns_survive(self):
        """``token`` alone is legitimate domain vocabulary (payment tokens
        shown as *last-4). Only compound forms are stripped."""
        from services.sensitive_column_guard import strip_sensitive_from_registry

        reg = {"entities": {"Payment": {"fields": [
            {"name": "token"}, {"name": "secret"}, {"name": "refreshToken"},
        ]}}}
        cleaned, dropped = strip_sensitive_from_registry(reg)

        assert dropped == 1
        assert [f["name"] for f in cleaned["entities"]["Payment"]["fields"]] == ["token", "secret"]

    @pytest.mark.parametrize("junk", [None, [], "nope", {}, {"entities": []}])
    def test_unrecognised_shapes_pass_through(self, junk):
        """Dropping a column the composer needs is worse than one extra
        output sweep — unknown shapes are returned untouched."""
        from services.sensitive_column_guard import strip_sensitive_from_registry

        cleaned, dropped = strip_sensitive_from_registry(junk)

        assert cleaned == junk and dropped == 0
