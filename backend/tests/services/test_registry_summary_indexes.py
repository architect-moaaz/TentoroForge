from services.registry import registry_summary_for_agent


def test_summary_handles_composite_indexes_without_crashing():
    # A composite index is a nested list (e.g. a multi-column index). The old code
    # did ', '.join(idxs) which raised TypeError when an element was itself a list.
    registry = {
        "entities": {
            "Booking": {
                "fields": {"id": {"type": "uuid", "primaryKey": True}},
                "indexes": ["status", ["userId", "createdAt"]],
            }
        }
    }
    out = registry_summary_for_agent(registry, ["entities"])
    assert "Booking" in out
    assert "userId" in out and "createdAt" in out  # composite rendered, not crashed


def test_summary_handles_plain_string_indexes():
    registry = {
        "entities": {
            "User": {"fields": {"id": {"type": "uuid"}}, "indexes": ["email"]}
        }
    }
    out = registry_summary_for_agent(registry, ["entities"])
    assert "indexes: email" in out
