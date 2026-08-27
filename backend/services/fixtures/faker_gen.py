"""Layer 2 fixture generator — uses Faker to produce realistic per-field values
based on the field name + type. Domain-aware enums (department, status) come
from the optional `domain` parameter; without it, generic lists are used."""
from __future__ import annotations

from typing import Any

from faker import Faker

from .fallback import fallback_value
from .types import FieldHint

_faker = Faker()


_DOMAIN_DEPARTMENTS = {
    "healthcare": ["Cardiology", "Oncology", "Pediatrics", "Emergency", "Radiology"],
    "fintech":    ["Trading", "Compliance", "Operations", "Risk", "Engineering"],
    "hr":         ["Engineering", "Marketing", "Sales", "Operations", "People"],
    "general":    ["Engineering", "Sales", "Operations", "Support", "Marketing"],
}

_STATUS_VALUES = ["active", "pending", "approved", "rejected", "archived"]


def _by_field_name(name: str, domain: str) -> Any | None:
    """Return a value for well-known field names, or None to fall through."""
    n = name.lower()
    if n == "id" or n.endswith("id"):
        return _faker.uuid4()
    if n in ("email", "emailaddress"):
        return _faker.email()
    if n in ("name", "fullname"):
        return _faker.name()
    if n in ("firstname",):
        return _faker.first_name()
    if n in ("lastname",):
        return _faker.last_name()
    if n in ("phone", "phonenumber"):
        return _faker.phone_number()
    if n in ("address",):
        return _faker.street_address()
    if n in ("city",):
        return _faker.city()
    if n in ("country",):
        return _faker.country()
    if n in ("company", "companyname"):
        return _faker.company()
    if n in ("amount", "balance", "price", "total"):
        return float(_faker.pydecimal(left_digits=4, right_digits=2, positive=True))
    if n in ("department", "dept"):
        return _faker.random_element(_DOMAIN_DEPARTMENTS.get(domain, _DOMAIN_DEPARTMENTS["general"]))
    if n in ("status", "state"):
        return _faker.random_element(_STATUS_VALUES)
    if n in ("createdat", "created", "updatedat", "timestamp"):
        return _faker.date_time_this_year().isoformat()
    if n in ("description", "notes", "summary", "bio"):
        return _faker.sentence(nb_words=12)
    if n in ("title",):
        return _faker.catch_phrase()
    if n in ("url", "website"):
        return _faker.url()
    if n in ("avatar", "avatarurl", "photo", "image"):
        return _faker.image_url()
    return None


def generate_record(entity_name: str, fields: list[FieldHint], domain: str = "general") -> dict[str, Any]:
    """Generate a single record from the field list."""
    record: dict[str, Any] = {}
    for field in fields:
        value = _by_field_name(field.name, domain)
        if value is None:
            value = fallback_value(field.name, field.type)
        record[field.name] = value
    return record


def generate_records(entity_name: str, fields: list[FieldHint], count: int = 10, domain: str = "general") -> list[dict[str, Any]]:
    """Generate `count` records. Each call gets a different seed for variety."""
    return [generate_record(entity_name, fields, domain) for _ in range(count)]
