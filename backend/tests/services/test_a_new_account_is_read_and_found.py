"""A new account's sensitive fields are read, found and counted (DITANS QA, 2026-11-02).

Every new professional's CV builder crashed on `fullName.split`: sign-up wrote
the name in the clear, the engine read only the sealed column, and the SDK
typed the empty value `string`. 207 of 249 masked fields had no reader, so an
agency's own fees summed "••••" into "USD NaN". Pages found members by a sealed
email, matched nobody, and fell back to every organisation's rows.
"""
from __future__ import annotations

import re
from pathlib import Path

from services.blueprint import app_sdk
from services.blueprint.projection import _page_lookups, _sealed_fields, sensitive_columns

ROOT = Path(__file__).resolve().parents[2]


def _doc(load: str = "") -> dict:
    return {
        "roles": [{"id": "ROLE-1", "name": "Member"}, {"id": "ROLE-2", "name": "Admin"}],
        "permissions": [],
        "data": {"entities": [{
            "id": "ENTITY-1", "name": "Member", "table": "members",
            "fields": [{"name": "id", "type": "uuid", "primaryKey": True},
                       {"name": "fullName", "type": "string", "required": True, "sensitive": True, "mask": "full"},
                       {"name": "email", "type": "string", "required": True, "sensitive": True, "mask": "email"},
                       {"name": "fee", "type": "money", "sensitive": True, "mask": "full"}]}],
            "relationships": []},
        "pages": [{"id": "PAGE-1", "route": "/team", "users": ["ROLE-1"], "access": "authenticated",
                   "data": {"primaryEntity": "ENTITY-1"}}],
        "pageCode": [{"page": "PAGE-1", "load": load, "view": ""}],
        "security": {},
    }


def test_who_may_read_the_record_may_read_its_masked_fields():
    spec = sensitive_columns(_doc())["Member"]
    assert spec["fullName"]["readers"] == ["Member"]
    assert "*" not in spec["fee"]["readers"]


def test_a_column_a_page_finds_rows_by_is_never_sealed():
    load = 'const [m] = await list("Member", { where: { email: user.email }, limit: 1 });'
    doc = _doc(load)
    assert _page_lookups(doc, "Member") == {"email"}
    sealed = _sealed_fields(doc["data"]["entities"][0], doc)
    assert "email" not in sealed and "fullName" in sealed


def test_a_sealed_field_is_typed_as_possibly_empty():
    doc = _doc()
    for e in doc["data"]["entities"]:
        for f in e["fields"]:
            f.pop("mask", None) if f["name"] == "id" else None
    text = app_sdk.emit_schema(doc)
    body = re.search(r"export interface Member \{(.*?)\n\}", text, re.S).group(1)
    assert "fullName: string | null;" in body


def test_an_unsealed_value_is_read_and_sign_up_seals_as_it_writes():
    engine = (ROOT / "templates/runtime/data-engine.ts").read_text()
    assert "const unsealed = record[encKey] == null && record[col] != null" in engine
    signup = (ROOT / "templates/app-foundation/src/app/api/auth/signup/route.ts").read_text()
    assert "await sealSensitive(ACCOUNT.entity, values)" in signup
    sdk = (ROOT / "templates/app-foundation/src/sdk/server.ts").read_text()
    assert 'else if (numeric.has(k) && typeof v === "string") out[k] = null;' in sdk
