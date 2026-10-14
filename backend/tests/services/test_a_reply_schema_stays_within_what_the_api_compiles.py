"""A node's reply schema is sent as strict structured output, and the API
refuses a schema with too many OPTIONAL properties ("Schema is too
complex"). Adding `appendOnly`, `mask` and `readers` took the data-model
schema from 20 to 23 and every data_model call was refused four times
over (pxf7qf3f, 2026-10-12). Measured: 20 compiles, 22 is refused. The
four field flags are required (`false` when they do not apply) to keep the
count at 19; this keeps it there."""
from __future__ import annotations

from services.blueprint.executors import DATA_MODEL_SCHEMA, SCHEMA_BY_NODE

LIMIT = 20


def _optional(schema) -> int:
    n = 0
    if isinstance(schema, dict):
        props = schema.get("properties")
        if isinstance(props, dict):
            req = set(schema.get("required") or [])
            n += len([k for k in props if k not in req])
        for v in schema.values():
            n += _optional(v)
    elif isinstance(schema, list):
        for v in schema:
            n += _optional(v)
    return n


def test_every_reply_schema_has_at_most_twenty_optional_properties():
    for node, schema in SCHEMA_BY_NODE.items():
        assert _optional(schema) <= LIMIT, f"{node}: {_optional(schema)} optional properties; the API refuses more than {LIMIT}"


def test_the_field_flags_are_required_so_the_audit_fields_fit():
    field = DATA_MODEL_SCHEMA["properties"]["entities"]["items"]["properties"]["fields"]["items"]
    assert {"required", "primaryKey", "unique", "sensitive"} <= set(field["required"])
    assert {"mask", "readers"} <= set(field["properties"])


def test_sensitive_comes_before_what_only_a_sensitive_field_has():
    """Strict output writes keys in schema order. With `mask` and `readers`
    ahead of `sensitive`, the model could not return to them after saying
    `sensitive: true` and wrote `max: 0` on text fields instead, so every
    value would have been refused (nhc0am2y, 2026-10-12)."""
    order = list(DATA_MODEL_SCHEMA["properties"]["entities"]["items"]["properties"]["fields"]["items"]["properties"])
    assert order.index("sensitive") < order.index("mask") < order.index("readers") < order.index("min")
