"""Tests for services.humanize — Sprint 5 of Forge Great Again.

Covers the pluralizer (irregular table + suffix rules + case preservation),
the general humanizer (snake/camel/kebab → Title Case), and the chart-
series-label variant (drops meta suffixes like ``_count`` before
humanizing).

The whole point of this module is to eliminate the "Propertys" /
"Maintenance_request" class of copy bug. Tests target real observed
failures from the field.
"""
from __future__ import annotations

import pytest

from services.humanize import (
    humanize,
    humanize_series_label,
    pluralize,
)


# ── Pluralize — irregulars, suffix rules, case preservation ─────────────

@pytest.mark.parametrize("singular,expected", [
    # Regular +s
    ("Room", "Rooms"),
    ("Unit", "Units"),
    ("Lease", "Leases"),

    # The bug that started it all: naive `+ "s"` produced "Propertys".
    ("Property", "Properties"),
    ("Company", "Companies"),
    ("Category", "Categories"),
    ("Family", "Families"),
    ("City", "Cities"),

    # -y after a vowel stays as -ys (never -ies).
    ("Day", "Days"),
    ("Boy", "Boys"),
    ("Key", "Keys"),

    # Suffixes needing -es.
    ("Box", "Boxes"),
    ("Batch", "Batches"),
    ("Class", "Classes"),
    ("Bus", "Buses"),
    ("Status", "Statuses"),
    ("Address", "Addresses"),
    ("Church", "Churches"),
    ("Dish", "Dishes"),

    # Irregulars.
    ("Person", "People"),
    ("Man", "Men"),
    ("Woman", "Women"),
    ("Child", "Children"),
    ("Mouse", "Mice"),
    ("Datum", "Data"),
    ("Criterion", "Criteria"),

    # Uncountables / unchanged.
    ("Sheep", "Sheep"),
    ("Series", "Series"),
    ("Species", "Species"),
    ("News", "News"),
    ("Equipment", "Equipment"),
    ("Software", "Software"),
])
def test_pluralize_common_cases(singular, expected):
    assert pluralize(singular) == expected


def test_pluralize_preserves_lowercase():
    assert pluralize("property") == "properties"
    assert pluralize("person") == "people"
    assert pluralize("box") == "boxes"


def test_pluralize_preserves_uppercase_acronym():
    assert pluralize("URL") == "URLS"
    assert pluralize("API") == "APIS"


def test_pluralize_idempotent_on_common_plurals():
    # Already-plural inputs shouldn't get double-pluralized.
    assert pluralize("Properties") == "Properties"
    assert pluralize("boxes") == "boxes"
    assert pluralize("Batches") == "Batches"


def test_pluralize_edge_cases_return_gracefully():
    assert pluralize("") == ""
    assert pluralize("   ") == ""
    assert pluralize(None) is None  # type: ignore[arg-type]
    # Numeric-looking strings pass through +s (no crash).
    assert pluralize("abc") == "abcs"


# ── Humanize — snake / camel / kebab → Title Case ───────────────────────

@pytest.mark.parametrize("raw,expected", [
    # snake_case
    ("full_name", "Full Name"),
    ("user_full_name", "User Full Name"),
    ("maintenance_request", "Maintenance Request"),
    ("payment_status", "Payment Status"),

    # camelCase
    ("fullName", "Full Name"),
    ("userFullName", "User Full Name"),
    ("propertyId", "Property Id"),
    ("createdAt", "Created At"),

    # kebab-case
    ("full-name", "Full Name"),
    ("user-full-name", "User Full Name"),

    # dotted
    ("user.full_name", "User Full Name"),

    # already-human (idempotent-ish)
    ("Already Human", "Already Human"),
    ("Full Name", "Full Name"),
])
def test_humanize_common_cases(raw, expected):
    assert humanize(raw) == expected


def test_humanize_preserves_all_caps_acronyms():
    assert humanize("HVAC") == "HVAC"
    assert humanize("HVAC_unit") == "HVAC Unit"
    assert humanize("user_URL") == "User URL"


def test_humanize_handles_bad_input():
    assert humanize("") == ""
    assert humanize(None) == ""  # type: ignore[arg-type]
    assert humanize("   ") == ""


# ── humanize_series_label — chart legend specifically ──────────────────

@pytest.mark.parametrize("raw,expected", [
    # The real bug from qzdvdmje: raw column name as chart legend.
    ("maintenance_request", "Maintenance Request"),

    # Meta suffixes commonly appended to aggregated column names.
    ("payment_count",         "Payment"),
    ("request_count",         "Request"),
    ("total_sum",             "Total"),
    ("revenue_sum",           "Revenue"),
    ("session_avg",           "Session"),
    ("visit_max",             "Visit"),
    ("visit_min",             "Visit"),

    # ID / reference suffixes dropped too.
    ("customer_id",   "Customer"),
    ("user_ids",      "User"),
    ("owner_ref",     "Owner"),

    # Date suffixes dropped.
    ("created_at",  "Created"),
    ("updated_on",  "Updated"),
    ("modified_by", "Modified"),

    # No suffix → normal humanize.
    ("payments",  "Payments"),
    ("Revenue",   "Revenue"),
])
def test_humanize_series_label_strips_meta_suffix(raw, expected):
    assert humanize_series_label(raw) == expected


def test_humanize_series_label_edge_cases():
    assert humanize_series_label("") == ""
    assert humanize_series_label(None) == ""  # type: ignore[arg-type]
    # Bare suffix returns empty (there's nothing left after stripping).
    assert humanize_series_label("_id") == ""
