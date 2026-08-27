from services.fixtures.fallback import fallback_value


def test_uuid_field_returns_a_uuid_string():
    v = fallback_value("id", "uuid")
    assert isinstance(v, str) and len(v) == 36


def test_string_field_returns_lorem():
    v = fallback_value("description", "varchar(255)")
    assert isinstance(v, str) and len(v) > 0


def test_number_field_returns_zero():
    v = fallback_value("amount", "numeric")
    assert v == 0


def test_boolean_field_returns_false():
    v = fallback_value("isActive", "boolean")
    assert v is False


def test_unknown_type_returns_none():
    v = fallback_value("mystery", "made_up_type")
    assert v is None
