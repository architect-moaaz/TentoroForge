"""Tests for the banking-platform archetype vocabulary.

Pins the contract downstream composers rely on: the vocabulary is
registered, the persona map covers the four canonical banking roles,
transactions splits into the industry-standard three-way lifecycle,
component shapes read as expected, and status badges carry the
banking colour semantics (posted=success, disputed=danger).
"""
from __future__ import annotations

from services.archetype_vocabulary import (
    clear_cache,
    known_archetypes,
    load_vocabulary,
)


class TestBankingPlatformRegistered:
    def setup_method(self):
        clear_cache()

    def test_vocab_registered(self):
        assert "banking-platform" in known_archetypes()

    def test_vocab_loads_via_registry(self):
        v = load_vocabulary("banking-platform")
        assert v is not None
        assert v.id == "banking-platform"

    def test_load_normalises_input(self):
        for raw in ("Banking Platform", "banking_platform",
                    "banking-platform", "BANKING-PLATFORM"):
            v = load_vocabulary(raw)
            assert v is not None, raw
            assert v.id == "banking-platform", raw


class TestBankingPersonas:
    """The four canonical banking personas — customer, officer,
    compliance, admin — must all be represented in the per-persona
    screen map, otherwise their sub-nav row is empty at runtime."""

    def setup_method(self):
        clear_cache()

    def _vocab(self):
        v = load_vocabulary("banking-platform")
        assert v is not None
        return v

    def test_customer_role_has_screens(self):
        v = self._vocab()
        # Any of the three customer aliases the planner might emit.
        keys = v.primary_screens_per_persona.keys()
        assert any(k in keys for k in ("customer", "member", "client"))

    def test_officer_role_has_screens(self):
        v = self._vocab()
        keys = v.primary_screens_per_persona.keys()
        assert any(k in keys for k in ("officer", "banker", "loan_officer"))

    def test_compliance_role_has_screens(self):
        v = self._vocab()
        keys = v.primary_screens_per_persona.keys()
        assert any(k in keys for k in ("compliance", "compliance_officer"))

    def test_admin_role_has_screens(self):
        v = self._vocab()
        keys = v.primary_screens_per_persona.keys()
        assert any(k in keys for k in ("admin", "manager", "bank_admin"))

    def test_customer_screens_cover_core_banking_surfaces(self):
        v = self._vocab()
        # Whichever alias is present, the surface set should be the same.
        for alias in ("customer", "member", "client"):
            if alias in v.primary_screens_per_persona:
                screens = v.primary_screens_per_persona[alias]
                assert "accounts" in screens
                assert "transactions" in screens
                assert "cards" in screens
                break


class TestBankingSectionRecipes:
    def setup_method(self):
        clear_cache()

    def _vocab(self):
        v = load_vocabulary("banking-platform")
        assert v is not None
        return v

    def test_transactions_splits_pending_posted_disputed(self):
        v = self._vocab()
        assert v.section_recipes.get("transactions") == [
            "pending", "posted", "disputed",
        ]

    def test_applications_splits_new_in_review_decisioned(self):
        v = self._vocab()
        assert v.section_recipes.get("applications") == [
            "new", "in-review", "decisioned",
        ]

    def test_cards_splits_active_expired_blocked(self):
        v = self._vocab()
        assert v.section_recipes.get("cards") == [
            "active", "expired", "blocked",
        ]

    def test_kyc_queue_declared(self):
        v = self._vocab()
        assert "kyc-queue" in v.section_recipes
        assert v.section_recipes["kyc-queue"]  # non-empty


class TestBankingComponentPreferences:
    def setup_method(self):
        clear_cache()

    def _vocab(self):
        v = load_vocabulary("banking-platform")
        assert v is not None
        return v

    def test_accounts_shape_is_card_grid(self):
        v = self._vocab()
        pref = v.component_preferences.get("accounts")
        assert pref is not None
        assert pref.shape == "card-grid"

    def test_transactions_shape_is_ledger_list(self):
        # Slice-3 promoted ``ledger-list`` into KNOWN_SHAPES + the collection
        # composer. Transactions bind to it verbatim now — no more card-list
        # fallback.
        v = self._vocab()
        pref = v.component_preferences.get("transactions")
        assert pref is not None
        assert pref.shape == "ledger-list"

    def test_applications_shape_is_kanban(self):
        # Slice-3: kanban is now in KNOWN_SHAPES, so ``applications`` binds
        # to it (was falling through to Table via unknown-shape guard).
        v = self._vocab()
        pref = v.component_preferences.get("applications")
        assert pref is not None
        assert pref.shape == "kanban"

    def test_no_todo_promote_comments_left(self):
        # Any leftover ``# TODO: promote to`` in the vocab file means a
        # shape the composer can't reach; Slice-3 should have cleared
        # them. Fail loudly so we notice a regression on the next slice.
        import services.archetype_vocabulary.banking_platform as _bp
        src = open(_bp.__file__, encoding="utf-8").read()
        assert "TODO: promote to" not in src

    def test_cards_shape_is_card_grid(self):
        v = self._vocab()
        pref = v.component_preferences.get("cards")
        assert pref is not None
        assert pref.shape == "card-grid"
        assert pref.primary_field == "last4"

    def test_customers_is_officer_scoped(self):
        v = self._vocab()
        pref = v.component_preferences.get("customers")
        assert pref is not None
        assert pref.context.lower() in ("officer", "banker", "loan_officer")


class TestBankingStatusBadges:
    def setup_method(self):
        clear_cache()

    def _vocab(self):
        v = load_vocabulary("banking-platform")
        assert v is not None
        return v

    def test_posted_is_success(self):
        v = self._vocab()
        assert v.status_badges["posted"]["variant"] == "success"

    def test_disputed_is_danger(self):
        v = self._vocab()
        assert v.status_badges["disputed"]["variant"] == "danger"

    def test_pending_is_warning(self):
        v = self._vocab()
        assert v.status_badges["pending"]["variant"] == "warning"

    def test_approved_is_success(self):
        v = self._vocab()
        assert v.status_badges["approved"]["variant"] == "success"

    def test_blocked_is_danger(self):
        v = self._vocab()
        assert v.status_badges["blocked"]["variant"] == "danger"


class TestBankingSignatureStates:
    def setup_method(self):
        clear_cache()

    def _vocab(self):
        v = load_vocabulary("banking-platform")
        assert v is not None
        return v

    def test_empty_transactions_is_populated(self):
        v = self._vocab()
        assert v.signature_states.get("empty_transactions"), (
            "empty_transactions copy is missing"
        )

    def test_empty_kyc_queue_is_populated(self):
        v = self._vocab()
        assert v.signature_states.get("empty_kyc_queue")

    def test_no_results_is_populated(self):
        v = self._vocab()
        assert v.signature_states.get("no_results")
