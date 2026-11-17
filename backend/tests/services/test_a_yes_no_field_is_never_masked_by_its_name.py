"""A field's mask is guessed from its name only when it holds text.

`TeamInvite.personalEmail` is a yes/no ("the invite went to a personal
address"); masked as an email it read "••••" for everyone (DITANS, 2026-11-12).
"""
from services.blueprint.projection import sensitive_columns


def _doc(fields):
    return {"roles": [], "pages": [], "data": {"entities": [
        {"id": "ENTITY-001", "name": "TeamInvite", "table": "team_invites", "fields": fields}]}}


def test_a_boolean_named_like_an_email_is_not_masked():
    out = sensitive_columns(_doc([{"name": "personalEmail", "type": "boolean"}]))
    assert "personalEmail" not in out.get("team_invites", out.get("TeamInvite", {}))


def test_a_text_email_is_still_masked():
    out = sensitive_columns(_doc([{"name": "email", "type": "string"}]))
    cols = out.get("TeamInvite") or out.get("team_invites") or {}
    assert cols.get("email", {}).get("mask") == "email"


def test_a_declared_mask_wins_whatever_the_type():
    out = sensitive_columns(_doc([{"name": "pin", "type": "number", "mask": "full"}]))
    cols = out.get("TeamInvite") or out.get("team_invites") or {}
    assert cols.get("pin", {}).get("mask") == "full"
