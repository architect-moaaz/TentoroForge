from services.fixtures.faker_gen import generate_record, generate_records
from services.fixtures.types import FieldHint


def fields(*pairs):
    return [FieldHint(name=n, type=t) for n, t in pairs]


def test_email_field_gets_a_real_email():
    r = generate_record("User", fields(("id", "uuid"), ("email", "varchar(255)")))
    assert "@" in r["email"]


def test_name_field_gets_a_full_name():
    r = generate_record("User", fields(("name", "varchar(255)")))
    assert " " in r["name"]


def test_unmapped_field_uses_fallback():
    r = generate_record("Foo", fields(("frobnicator", "made_up_type")))
    assert r["frobnicator"] is None


def test_generate_records_produces_count_distinct_records():
    rs = generate_records("User", fields(("id", "uuid"), ("email", "varchar(255)")), count=5)
    assert len(rs) == 5
    assert len({r["id"] for r in rs}) == 5
