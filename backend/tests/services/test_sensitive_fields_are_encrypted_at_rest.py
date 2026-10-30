"""Sensitive fields are encrypted at rest on every Blueprint-built app
(60v142ju, 2026-10-12): the table carries `<field>_encrypted` and
`<field>_mask` beside each sealed field; assembly keeps the app's encryption
key (and push keys) across rebuilds; process steps seal before they write;
every start seals what is still in plain text; a publish ships the key."""
from __future__ import annotations

import re
from pathlib import Path

from services.blueprint.assembly import _SECRET_KEYS
from services.blueprint.projection import emit_entity_module

ROOT = Path(__file__).resolve().parents[2]
ENTITY = {"id": "ENTITY-001", "name": "Submission", "table": "submissions", "fields": [
    {"name": "id", "type": "uuid", "primaryKey": True},
    {"name": "fullName", "type": "string", "required": True, "sensitive": True, "mask": "full"},
    {"name": "identificationNumber", "type": "string", "unique": True, "sensitive": True, "mask": "last4"},
    {"name": "status", "type": "string", "required": True}]}
DOC = {"data": {"entities": [ENTITY]}, "roles": []}


def test_the_table_carries_the_seal_beside_each_sealed_field():
    src = emit_entity_module(ENTITY, DOC)
    assert 'fullName: text("full_name"),' in src, "the plain column is optional: the engine never writes it"
    assert 'fullName_encrypted: text("full_name_encrypted"),' in src and 'fullName_mask: text("full_name_mask"),' in src
    assert 'identificationNumber: text("identification_number"),' in src, "no unique on a value sealed under a fresh nonce"
    assert 'status: text("status").notNull(),' in src and "status_encrypted" not in src


def test_assembly_keeps_the_encryption_and_push_keys():
    assert "SENSITIVE_ENCRYPTION_KEY" in _SECRET_KEYS
    src = (ROOT / "services/blueprint/assembly.py").read_text()
    assert "SENSITIVE_ENCRYPTION_KEY={kept.get('SENSITIVE_ENCRYPTION_KEY') or base64.b64encode(secrets.token_bytes(32))" in src
    assert 'for k in VAPID_KEYS)' in src


def test_process_steps_seal_before_they_write():
    src = (ROOT / "templates/runtime/workflows/index.ts").read_text()
    assert src.count("await _seal(table,") >= 3 and "const plain = await _seal(table, values);" in src
    assert "export async function sealSensitive(" in (ROOT / "templates/runtime/data-engine.ts").read_text()
    # every insert of an app table seals first
    for m in re.finditer(r"await \(db as any\)\.(insert|update)\(table\)", src):
        before = src[max(0, m.start() - 400):m.start()]
        if "forgeNotifications" in before or "schema as any" in before:
            continue
        assert "_seal(table" in before, src[m.start() - 200:m.start() + 60]


def test_every_start_seals_what_is_still_plain_and_a_publish_ships_the_key():
    seed = (ROOT / "templates/runtime/seed.ts").read_text()
    assert "async function sealPlainSensitive()" in seed and "await sealPlainSensitive();" in seed
    assert "_loadEncryptionKey()" in seed
    deploy = (ROOT / "services/deploy/vercel_provider.py").read_text()
    assert '(*VAPID_KEYS, "SENSITIVE_ENCRYPTION_KEY")' in deploy


def test_columns_rows_are_found_by_are_never_sealed():
    users = {"id": "ENTITY-009", "name": "User", "table": "users", "fields": [
        {"name": "id", "type": "uuid", "primaryKey": True},
        {"name": "email", "type": "email", "required": True, "unique": True, "sensitive": True, "mask": "email"},
        {"name": "phone", "type": "string", "sensitive": True, "mask": "phone"}]}
    src = emit_entity_module(users, {"data": {"entities": [users]}, "roles": []})
    assert "email_encrypted" not in src and ".notNull()" in src.split("email:")[1].split("\n")[0], "sign-in looks people up by email"
    assert "phone_encrypted" in src
    owned = {**ENTITY, "fields": ENTITY["fields"] + [{"name": "ownerToken", "type": "string", "sensitive": True, "mask": "full"}]}
    doc = {"data": {"entities": [owned]}, "roles": [],
           "security": {"ownershipRules": [{"entity": "Submission", "kind": "scope", "column": "ownerToken"}]}}
    assert "ownerToken_encrypted" not in emit_entity_module(owned, doc), "an ownership rule filters by it"
    looked_up = {"data": {"entities": [ENTITY]}, "roles": [], "workflows": [{"steps": [
        {"type": "action", "config": {"actionType": "db_query", "table": "submissions",
                                      "where": {"identificationNumber": "{{number}}"}}}]}]}
    src = emit_entity_module(ENTITY, looked_up)
    assert "identificationNumber_encrypted" not in src, "a workflow finds rows by it"
    assert "fullName_encrypted" in src


def test_the_engine_seals_only_where_the_table_holds_the_seal():
    src = (ROOT / "templates/runtime/data-engine.ts").read_text()
    assert "if (tbl && !(`${col}_encrypted` in tbl)) continue;" in src
