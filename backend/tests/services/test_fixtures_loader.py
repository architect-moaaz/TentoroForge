import pytest
from services.fixtures.loader import load_domain_bank, available_domains


def test_general_user_bank_has_10_records():
    records = load_domain_bank("general", "User")
    assert records is not None
    assert len(records) == 10
    assert all("id" in r for r in records)


def test_unknown_domain_returns_none():
    assert load_domain_bank("nonexistent_domain", "User") is None


def test_unknown_entity_in_known_domain_returns_none():
    assert load_domain_bank("general", "NoSuchEntity") is None


def test_available_domains_lists_seeded_ones():
    domains = available_domains()
    assert "general" in domains
    assert "healthcare" in domains
    assert "fintech" in domains
    assert "hr" in domains
