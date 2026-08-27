"""Slice-4 encrypt-at-rest: plan-validator rules for `sensitive: true` fields.

The contract enforced here:

  * ``sensitive`` only on string-shaped columns (text/varchar/char).
  * When the entity omits ``sensitiveReaders`` AND the field omits ``mask``,
    reject as ambiguous (undeclared security posture).
  * ``mask`` (if set) must be one of the runtime-known kinds.
  * Warn (don't reject) when a reader slug isn't declared in ``plan.actors[]``.
"""
from __future__ import annotations

from services import plan_validator


def _plan(entity_extra: dict | None = None,
          field_extra: dict | None = None,
          actors: list | None = None) -> dict:
    """A minimal single-entity plan with one sensitive `accountNumber`."""
    entity = {
        "table": "accounts",
        "fields": [
            {"name": "id", "type": "uuid", "primaryKey": True, "not_null": True},
            {"name": "nickname", "type": "text", "not_null": False},
            {"name": "accountNumber", "type": "text", "sensitive": True,
             "not_null": True, **(field_extra or {})},
        ],
    }
    entity.update(entity_extra or {})
    plan: dict = {
        "entities": {"Account": entity},
    }
    if actors is not None:
        plan["actors"] = actors
    return plan


def _pick(violations: list[dict], rule: str) -> list[dict]:
    return [v for v in violations if v["rule"] == rule]


# ── acceptance ────────────────────────────────────────────────────────────


def test_sensitive_text_with_readers_accepted():
    v = plan_validator.validate_plan(_plan(
        entity_extra={"sensitiveReaders": ["bank_admin"]},
        actors=[{"name": "Bank Admin", "role": "bank_admin",
                 "onboarding": {"source": "invited_by",
                                "invited_by": "bank_admin"}}],
    ))
    for rule in ("sensitive_field_type_unsupported",
                 "sensitive_readers_or_mask_required",
                 "sensitive_mask_unknown",
                 "sensitive_readers_unknown_role"):
        assert _pick(v, rule) == [], f"{rule} unexpectedly raised"


def test_sensitive_text_with_explicit_mask_only_accepted():
    # readers omitted, but mask declared → masked-only posture; accepted.
    v = plan_validator.validate_plan(_plan(field_extra={"mask": "last4"}))
    assert _pick(v, "sensitive_readers_or_mask_required") == []


def test_sensitive_empty_readers_list_is_authored_intent_accepted():
    # readers=[] explicitly says "nobody unmasks"; NOT ambiguous.
    v = plan_validator.validate_plan(_plan(
        entity_extra={"sensitiveReaders": []},
    ))
    assert _pick(v, "sensitive_readers_or_mask_required") == []


# ── rejection ─────────────────────────────────────────────────────────────


def test_sensitive_on_uuid_rejected():
    plan = _plan()
    plan["entities"]["Account"]["fields"][-1]["type"] = "uuid"
    v = plan_validator.validate_plan(plan)
    hits = _pick(v, "sensitive_field_type_unsupported")
    assert len(hits) == 1
    assert hits[0]["severity"] == "error"
    assert "accountNumber" in hits[0]["message"]


def test_sensitive_on_numeric_rejected():
    plan = _plan()
    plan["entities"]["Account"]["fields"][-1]["type"] = "numeric"
    hits = _pick(plan_validator.validate_plan(plan),
                 "sensitive_field_type_unsupported")
    assert len(hits) == 1


def test_sensitive_on_jsonb_rejected():
    plan = _plan()
    plan["entities"]["Account"]["fields"][-1]["type"] = "jsonb"
    hits = _pick(plan_validator.validate_plan(plan),
                 "sensitive_field_type_unsupported")
    assert len(hits) == 1


def test_sensitive_missing_readers_and_mask_rejected():
    # neither readers on the entity nor a mask on the field → ambiguous.
    v = plan_validator.validate_plan(_plan())
    hits = _pick(v, "sensitive_readers_or_mask_required")
    assert len(hits) == 1
    assert hits[0]["severity"] == "error"


def test_sensitive_unknown_mask_kind_rejected():
    v = plan_validator.validate_plan(_plan(
        entity_extra={"sensitiveReaders": []},
        field_extra={"mask": "middle"},
    ))
    hits = _pick(v, "sensitive_mask_unknown")
    assert len(hits) == 1
    assert hits[0]["severity"] == "error"


def test_sensitive_mask_kinds_accepted():
    for kind in ("last4", "email", "phone", "full"):
        v = plan_validator.validate_plan(_plan(
            entity_extra={"sensitiveReaders": []},
            field_extra={"mask": kind},
        ))
        assert _pick(v, "sensitive_mask_unknown") == []


# ── warnings ──────────────────────────────────────────────────────────────


def test_sensitive_readers_unknown_role_warns():
    v = plan_validator.validate_plan(_plan(
        entity_extra={"sensitiveReaders": ["compliance"]},
        actors=[{"name": "Customer", "role": "customer",
                 "onboarding": {"source": "self_signup"}}],
    ))
    hits = _pick(v, "sensitive_readers_unknown_role")
    assert len(hits) == 1
    assert hits[0]["severity"] == "warning"
    assert "compliance" in hits[0]["message"]


def test_sensitive_readers_star_wildcard_never_warns():
    # `*` = every authenticated user; not a typo.
    v = plan_validator.validate_plan(_plan(
        entity_extra={"sensitiveReaders": ["*"]},
        actors=[{"name": "Customer", "role": "customer",
                 "onboarding": {"source": "self_signup"}}],
    ))
    assert _pick(v, "sensitive_readers_unknown_role") == []


def test_sensitive_readers_known_role_no_warning():
    v = plan_validator.validate_plan(_plan(
        entity_extra={"sensitiveReaders": ["bank_admin"]},
        actors=[{"name": "Bank Admin", "role": "bank_admin",
                 "onboarding": {"source": "invited_by",
                                "invited_by": "bank_admin"}}],
    ))
    assert _pick(v, "sensitive_readers_unknown_role") == []


# ── absence of `sensitive` on a field never triggers this rule ────────────


def test_non_sensitive_field_not_flagged():
    plan = {
        "entities": {"Account": {
            "table": "accounts",
            "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True,
                 "not_null": True},
                {"name": "nickname", "type": "text", "not_null": True},
            ],
        }},
    }
    v = plan_validator.validate_plan(plan)
    for rule in ("sensitive_field_type_unsupported",
                 "sensitive_readers_or_mask_required",
                 "sensitive_mask_unknown",
                 "sensitive_readers_unknown_role"):
        assert _pick(v, rule) == []
