"""Tests for payment_feature — detect + emit surface for saved payment methods.

The pipeline already emits the `payment_methods` DB table + Create/Update/Delete
CRUD workflows whenever a PaymentMethod entity is planned. What's missing is the
user-facing surface: a list page, an add-card form, and a nav entry. This
module fills that gap deterministically.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.payment_feature import (
    detect_payment_intent,
    ensure_payment_surface,
)


# ────────────────────────────────────────────────────────────
# detect_payment_intent
# ────────────────────────────────────────────────────────────


def test_detect_matches_paymentmethod_entity():
    plan = {"entities": {"PaymentMethod": {"fields": {"id": {}, "cardLast4": {}}}}}
    r = detect_payment_intent(plan)
    assert r["needs_payment_methods"] is True
    assert r["reason"].startswith("entity:")


def test_detect_matches_case_and_snake():
    # Structural literal matches — the entity name variants the planner uses.
    for name in ("payment_method", "PAYMENT_METHOD", "PaymentMethods"):
        plan = {"entities": {name: {"fields": {"id": {}}}}}
        assert detect_payment_intent(plan)["needs_payment_methods"] is True


def test_detect_matches_commerce_flag_on_any_entity():
    # Plans that flew through commerce_flag pass have commerce=true — those
    # apps need a payment surface too.
    plan = {
        "entities": {
            "Product": {"commerce": True, "fields": {"id": {}, "price": {}}}
        }
    }
    r = detect_payment_intent(plan)
    assert r["needs_payment_methods"] is True
    assert "commerce" in r["reason"]


def test_detect_ignores_amount_on_non_transactional_entity():
    # Spec D W2 — the regex-based transactional-amount fallback is gone; the
    # detector no longer fires on a stray amount column on any entity.
    plan = {
        "entities": {
            "User": {"fields": {"id": {}, "budget": {"type": "numeric"}}}
        }
    }
    r = detect_payment_intent(plan)
    assert r["needs_payment_methods"] is False


def test_detect_no_transactional_regex_fallback():
    # A Booking with a totalAmount column used to fire the regex fallback.
    # Under planner-precedence-only, it must not fire without an explicit
    # planner signal or a PaymentMethod entity.
    plan = {
        "entities": {
            "Booking": {"fields": {"id": {}, "totalAmount": {"type": "numeric"}}},
            "User": {"fields": {"id": {}}},
        }
    }
    assert detect_payment_intent(plan)["needs_payment_methods"] is False


def test_detect_no_signals_returns_false():
    plan = {"entities": {"Note": {"fields": {"id": {}, "content": {}}}}}
    r = detect_payment_intent(plan)
    assert r["needs_payment_methods"] is False


def test_detect_empty_plan_is_safe():
    assert detect_payment_intent({}) == {"needs_payment_methods": False, "reason": "no signal"}
    assert detect_payment_intent({"entities": {}})["needs_payment_methods"] is False


# ────────────────────────────────────────────────────────────
# ensure_payment_surface — file emission
# ────────────────────────────────────────────────────────────


def _fixture_project(tmp_path: Path, *, needs_payment: bool = True) -> Path:
    """Build a minimal output dir with a plan that triggers the detector."""
    (tmp_path / "src" / "schemas" / "settings").mkdir(parents=True)
    (tmp_path / "src" / "contracts").mkdir(parents=True)
    entities = (
        {"PaymentMethod": {"table": "payment_methods", "fields": {
            "id": {"type": "uuid"},
            "cardBrand": {"type": "varchar"},
            "cardLast4": {"type": "varchar"},
            "isDefault": {"type": "boolean"},
        }}}
        if needs_payment else
        {"Note": {"fields": {"id": {}}}}
    )
    plan = {"entities": entities}
    (tmp_path / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    # Minimal nav-flow so ensure_payment_surface has something to update.
    (tmp_path / "src" / "contracts" / "nav-flow.json").write_text(json.dumps({
        "pages": [{"id": "home", "route": "/"}],
    }), encoding="utf-8")
    return tmp_path


def test_emits_list_page_when_detector_positive(tmp_path):
    _fixture_project(tmp_path)
    r = ensure_payment_surface(str(tmp_path))
    list_path = tmp_path / "src" / "schemas" / "settings" / "payment-methods.json"
    assert list_path.exists()
    schema = json.loads(list_path.read_text(encoding="utf-8"))
    # dataSource must bind to the real entity
    assert schema["dataSources"][0]["entity"] == "PaymentMethod"
    assert schema["dataSources"][0]["op"] == "list"
    # An "Add Payment Method" button that navigates to the new-page route
    root_text = json.dumps(schema["root"])
    assert "/settings/payment-methods/new" in root_text
    assert r["surfaces_emitted"] >= 1


def test_emits_add_card_form_page(tmp_path):
    _fixture_project(tmp_path)
    ensure_payment_surface(str(tmp_path))
    add_path = tmp_path / "src" / "schemas" / "settings" / "payment-methods" / "new.json"
    assert add_path.exists()
    schema = json.loads(add_path.read_text(encoding="utf-8"))
    root_text = json.dumps(schema["root"])
    # Form must dispatch the CreatePaymentMethod workflow (the CRUD gen emits it).
    assert "CreatePaymentMethod" in root_text


def test_registers_route_in_nav_flow(tmp_path):
    _fixture_project(tmp_path)
    ensure_payment_surface(str(tmp_path))
    nav = json.loads((tmp_path / "src" / "contracts" / "nav-flow.json").read_text(encoding="utf-8"))
    routes = [p.get("route") for p in nav.get("pages", [])]
    assert "/settings/payment-methods" in routes
    entry = next(p for p in nav["pages"] if p["route"] == "/settings/payment-methods")
    # Should be shell-wrapped so nav appears; auth-gated by default (settings).
    assert entry.get("shell") is True


def test_noop_when_detector_negative(tmp_path):
    _fixture_project(tmp_path, needs_payment=False)
    r = ensure_payment_surface(str(tmp_path))
    assert r["surfaces_emitted"] == 0
    assert not (tmp_path / "src" / "schemas" / "settings" / "payment-methods.json").exists()


def test_idempotent_when_already_emitted(tmp_path):
    _fixture_project(tmp_path)
    ensure_payment_surface(str(tmp_path))
    first_mtime = (
        tmp_path / "src" / "schemas" / "settings" / "payment-methods.json"
    ).stat().st_mtime_ns
    r = ensure_payment_surface(str(tmp_path))
    # Second run reports no NEW emission and never rewrites the file.
    assert r["surfaces_emitted"] == 0
    second_mtime = (
        tmp_path / "src" / "schemas" / "settings" / "payment-methods.json"
    ).stat().st_mtime_ns
    assert first_mtime == second_mtime


def test_does_not_stomp_existing_llm_authored_pages(tmp_path):
    _fixture_project(tmp_path)
    # Pretend the LLM already emitted a richer page.
    settings_dir = tmp_path / "src" / "schemas" / "settings"
    settings_dir.mkdir(exist_ok=True)
    settings_dir.joinpath("payment-methods.json").write_text(json.dumps(
        {"root": {"type": "Text", "props": {"text": "custom LLM-authored"}}}
    ), encoding="utf-8")
    ensure_payment_surface(str(tmp_path))
    kept = json.loads(
        (settings_dir / "payment-methods.json").read_text(encoding="utf-8")
    )
    assert kept["root"]["type"] == "Text"


def test_handles_missing_nav_flow_gracefully(tmp_path):
    (tmp_path / "plan.json").write_text(json.dumps({"entities": {"PaymentMethod": {"fields": {}}}}), encoding="utf-8")
    (tmp_path / "src" / "schemas" / "settings").mkdir(parents=True)
    # No nav-flow.json — surface should still emit the schema pages.
    r = ensure_payment_surface(str(tmp_path))
    assert (tmp_path / "src" / "schemas" / "settings" / "payment-methods.json").exists()
    assert r["surfaces_emitted"] >= 1
