"""A field is masked when its name SAYS it holds an email, a phone, an
account number or a credential — a whole word, never a substring.

`businessName` contains the letters "ssn"; matched as a substring it was
masked to its last four letters for everyone, so every vendor on ECom L4's
storefront read "••••arel" (7ttp60zi, 2026-10-11)."""
from __future__ import annotations

import pytest

from services.blueprint.projection import _mask_hint, sensitive_columns


@pytest.mark.parametrize("name,mask", [
    ("businessName", None), ("assignee", None), ("lesson", None), ("hotel", None), ("displayName", None),
    ("email", "email"), ("contactEmail", "email"), ("emailAddress", "email"),
    ("phone", "phone"), ("contactPhone", "phone"), ("mobile", "phone"), ("telephone", "phone"),
    ("ssn", "last4"), ("taxId", "last4"), ("cardNumber", "last4"), ("iban", "last4"), ("nationalIdNumber", "last4"),
    ("passwordHash", "full"), ("apiKey", "full"), ("accessToken", "full"), ("clientSecret", "full"),
])
def test_a_hint_matches_a_whole_word(name, mask):
    assert _mask_hint(name) == mask


def test_a_vendors_business_name_is_not_a_masked_column():
    doc = {"roles": [], "permissions": [], "data": {"entities": [
        {"id": "ENTITY-002", "name": "VendorAccount", "table": "vendor_accounts",
         "fields": [{"name": "businessName", "type": "string"}, {"name": "contactEmail", "type": "string"}]}]}}
    cols = sensitive_columns(doc)["VendorAccount"]
    assert "businessName" not in cols and cols["contactEmail"]["mask"] == "email"
