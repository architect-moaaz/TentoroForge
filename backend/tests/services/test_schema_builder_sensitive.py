"""Slice-4 encrypt-at-rest: schema-builder contract for `sensitive: true`.

The deterministic schema builder rewrites every sensitive column into a
`<name>_encrypted` text column + a `<name>_mask` text sibling, and emits
`src/lib/sensitive-columns.ts` — the manifest the runtime data-engine
reads at write time (encrypt+mask) and read time (mask-vs-unmask).
"""
from __future__ import annotations

from services.schema_builder import (
    build_schema_files,
    _sensitive_encrypted_name,
    _sensitive_mask_name,
)


def _plan(fields: list[dict],
          readers: list[str] | None = None,
          entity_name: str = "Account",
          table_name: str = "accounts") -> dict:
    ent: dict = {
        "name": entity_name,
        "table": table_name,
        "fields": [
            {"name": "id", "type": "uuid", "primaryKey": True},
            *fields,
        ],
    }
    if readers is not None:
        ent["sensitiveReaders"] = readers
    return {"data_models": [ent]}


# ── unit-level: name derivations ───────────────────────────────────────────


def test_sensitive_encrypted_name_variants():
    assert _sensitive_encrypted_name("accountNumber") == "accountNumber_encrypted"
    assert _sensitive_encrypted_name("ssn") == "ssn_encrypted"
    # Idempotent — already-suffixed name is left alone.
    assert _sensitive_encrypted_name("accountNumber_encrypted") == "accountNumber_encrypted"


def test_sensitive_mask_name_variants():
    assert _sensitive_mask_name("accountNumber") == "accountNumber_mask"
    assert _sensitive_mask_name("ssn") == "ssn_mask"
    # Strip a stray `_encrypted` suffix first — the mask column is keyed to
    # the ORIGINAL name so a hand-authored plan that pre-declared the
    # encrypted name still gets the right mask column.
    assert _sensitive_mask_name("accountNumber_encrypted") == "accountNumber_mask"


# ── integration: build_schema_files against a real plan ────────────────────


def test_sensitive_column_renamed_to_encrypted(tmp_path):
    build_schema_files(_plan(
        [{"name": "accountNumber", "type": "text", "sensitive": True,
          "mask": "last4", "nullable": False}],
        readers=["bank_admin"],
    ), str(tmp_path))
    src = (tmp_path / "src" / "db" / "schema" / "accounts.ts").read_text(encoding="utf-8")
    # The plaintext column is GONE.
    # Match the drizzle column line (`  accountNumber: text(...)`) to avoid
    # false positives from comment mentions or column bodies referencing it.
    assert "\n  accountNumber:" not in src
    assert '"account_number"' not in src.replace('_encrypted"', "").replace('_mask"', "")
    # The encrypted column is present, as text.
    assert 'accountNumber_encrypted: text("account_number_encrypted")' in src
    # NOT NULL flows through (parent nullable:false → encrypted .notNull()).
    assert 'accountNumber_encrypted: text("account_number_encrypted").notNull()' in src


def test_sensitive_column_emits_mask_sibling(tmp_path):
    build_schema_files(_plan(
        [{"name": "accountNumber", "type": "text", "sensitive": True,
          "mask": "last4", "nullable": False}],
        readers=["bank_admin"],
    ), str(tmp_path))
    src = (tmp_path / "src" / "db" / "schema" / "accounts.ts").read_text(encoding="utf-8")
    # Mask sibling: text (nullable — a freshly-inserted row without a set
    # sensitive value has no mask).
    assert 'accountNumber_mask: text("account_number_mask")' in src
    assert 'accountNumber_mask: text("account_number_mask").notNull()' not in src
    # Sits immediately after the encrypted column.
    idx_enc = src.index("accountNumber_encrypted:")
    idx_mask = src.index("accountNumber_mask:")
    assert idx_mask > idx_enc
    between = src[idx_enc:idx_mask]
    # Nothing else between the encrypted line and the mask line (allowing
    # for a single line break + indent).
    assert between.count("\n") <= 2


def test_sensitive_header_comment_stamps_original_names(tmp_path):
    build_schema_files(_plan(
        [
            {"name": "accountNumber", "type": "text", "sensitive": True,
             "mask": "last4"},
            {"name": "routingNumber", "type": "text", "sensitive": True,
             "mask": "last4"},
        ],
        readers=["bank_admin"],
    ), str(tmp_path))
    src = (tmp_path / "src" / "db" / "schema" / "accounts.ts").read_text(encoding="utf-8")
    # The header should name the ORIGINAL columns, not the encrypted ones.
    header_line = next(ln for ln in src.splitlines() if "SENSITIVE COLUMNS" in ln)
    assert "accountNumber" in header_line
    assert "routingNumber" in header_line


def test_sensitive_is_idempotent_when_plan_predeclares_encrypted(tmp_path):
    # Plan already models an `accountNumber_encrypted` column of its own —
    # builder must NOT double-rename (would yield accountNumber_encrypted_encrypted).
    build_schema_files(_plan(
        [{"name": "accountNumber_encrypted", "type": "text", "sensitive": True,
          "mask": "last4"}],
        readers=["bank_admin"],
    ), str(tmp_path))
    src = (tmp_path / "src" / "db" / "schema" / "accounts.ts").read_text(encoding="utf-8")
    assert "accountNumber_encrypted_encrypted" not in src
    # And the mask column is named against the ORIGINAL (stripped) name.
    assert 'accountNumber_mask: text("account_number_mask")' in src


# ── integration: sensitive-columns.ts manifest ─────────────────────────────


def test_manifest_emitted_with_column_specs(tmp_path):
    build_schema_files(_plan(
        [
            {"name": "accountNumber", "type": "text", "sensitive": True,
             "mask": "last4"},
            {"name": "routingNumber", "type": "text", "sensitive": True,
             "mask": "last4"},
        ],
        readers=["bank_admin", "compliance"],
    ), str(tmp_path))
    manifest = (tmp_path / "src" / "lib" / "sensitive-columns.ts").read_text(encoding="utf-8")
    assert "SENSITIVE_COLUMNS" in manifest
    assert "hasSensitiveColumns" in manifest
    assert "sensitiveColumnsFor" in manifest
    # Column keys are the ORIGINAL plaintext names — the runtime never sees
    # the _encrypted / _mask names when it looks up policy.
    assert '"accountNumber": { mask: "last4"' in manifest
    assert '"routingNumber": { mask: "last4"' in manifest
    # Readers array carries both role slugs verbatim.
    assert 'readers: ["bank_admin", "compliance"]' in manifest
    # Every reachable form of the entity name resolves.
    assert '"Account":' in manifest
    assert '"account":' in manifest
    assert '"accounts":' in manifest


def test_manifest_still_emitted_when_no_sensitive_columns(tmp_path):
    # No sensitive columns → the file still exists (empty map) so the
    # runtime's static import doesn't 404.
    build_schema_files(_plan(
        [{"name": "nickname", "type": "text"}],
    ), str(tmp_path))
    manifest_path = tmp_path / "src" / "lib" / "sensitive-columns.ts"
    assert manifest_path.is_file()
    manifest = manifest_path.read_text(encoding="utf-8")
    assert "SENSITIVE_COLUMNS" in manifest
    assert "SENSITIVE_COLUMNS: Record<" in manifest
    assert '"accountNumber":' not in manifest


def test_manifest_empty_readers_are_preserved(tmp_path):
    # readers=[] = "nobody unmasks" (masked-only). Must survive as an empty
    # array — not fall back to a default.
    build_schema_files(_plan(
        [{"name": "ssn", "type": "text", "sensitive": True, "mask": "full"}],
        readers=[],
    ), str(tmp_path))
    manifest = (tmp_path / "src" / "lib" / "sensitive-columns.ts").read_text(encoding="utf-8")
    assert 'readers: []' in manifest


def test_manifest_mask_defaults_to_last4_when_field_omits_it(tmp_path):
    # Validator lets a sensitive field skip `mask` iff `sensitiveReaders`
    # is declared — the runtime still needs to know how to render the mask.
    # Default to `last4` (account-number shape).
    build_schema_files(_plan(
        [{"name": "accountNumber", "type": "text", "sensitive": True}],
        readers=["bank_admin"],
    ), str(tmp_path))
    manifest = (tmp_path / "src" / "lib" / "sensitive-columns.ts").read_text(encoding="utf-8")
    assert '"accountNumber": { mask: "last4"' in manifest


# ── coexistence with other slices ─────────────────────────────────────────


def test_sensitive_plays_nice_with_append_only(tmp_path):
    # Ledger + sensitive column: schema still omits updatedAt, still emits
    # both encrypted + mask columns, still lands in the append-only manifest.
    plan = _plan(
        [{"name": "accountNumber", "type": "text", "sensitive": True,
          "mask": "last4"}],
        readers=["bank_admin"],
    )
    plan["data_models"][0]["lifecycle"] = "append_only"
    plan["data_models"][0]["name"] = "Transaction"
    plan["data_models"][0]["table"] = "transactions"
    build_schema_files(plan, str(tmp_path))
    src = (tmp_path / "src" / "db" / "schema" / "transactions.ts").read_text(encoding="utf-8")
    assert "APPEND-ONLY LEDGER" in src
    assert "updatedAt" not in src
    assert "accountNumber_encrypted:" in src
    assert "accountNumber_mask:" in src
    ao_manifest = (tmp_path / "src" / "lib" / "append-only-entities.ts").read_text(encoding="utf-8")
    assert '"Transaction"' in ao_manifest
    s_manifest = (tmp_path / "src" / "lib" / "sensitive-columns.ts").read_text(encoding="utf-8")
    assert '"Transaction":' in s_manifest
