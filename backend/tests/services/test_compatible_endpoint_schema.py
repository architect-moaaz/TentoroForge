"""An Anthropic-compatible endpoint is not Anthropic's: what it holds to differs.

Kimi takes `output_config.format` and answers a schema with a property named
`required` with empty objects — every entity of two live apps was committed
with no columns, and every page naming a field was refused after. The
transport renames that property on the way out and back on the way in; the
schema is stated in the prompt; and an `entity_fields` reply with no fields
is refused rather than committed.
"""
from __future__ import annotations

import json

import pytest

from services.blueprint import executors as ex


def test_only_anthropics_own_endpoint_is_trusted_to_enforce_the_schema(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    assert ex._endpoint_enforces_schema()
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    assert ex._endpoint_enforces_schema()
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.moonshot.ai/anthropic")
    assert not ex._endpoint_enforces_schema()
    assert not ex.AnthropicModel().enforces_schema


def test_a_keyword_named_property_travels_under_an_alias_and_comes_back():
    schema = ex.DATA_MODEL_SCHEMA
    sent = ex._alias_keyword_properties(schema)
    field = sent["properties"]["entities"]["items"]["properties"]["fields"]["items"]
    assert "required" not in field["properties"] and "isRequiredField" in field["properties"]
    assert field["required"] == ["name", "type"], "the list of required keys is untouched"
    assert schema["properties"]["entities"]["items"]["properties"]["fields"]["items"][
        "properties"]["required"], "the caller's schema is never changed"
    reply = json.dumps({"entities": [{"name": "Task", "fields": [
        {"name": "title", "type": "text", "isRequiredField": True}]}]})
    back = json.loads(ex._unalias_keyword_properties(reply))
    assert back["entities"][0]["fields"][0] == {"name": "title", "type": "text", "required": True}
    assert ex._unalias_keyword_properties("not json") == "not json"


def test_an_entity_with_no_fields_is_refused_not_committed():
    raw = json.dumps({"entities": [{"name": "Task", "fields": [{}, {}]}]})
    with pytest.raises(ex.MalformedEnvelope, match="no fields"):
        ex.parse_envelope(raw, task_id="t", agent="data_architect", node="entity_fields")
    ok = json.dumps({"entities": [{"name": "Task", "fields": [{"name": "title", "type": "text"}]}]})
    assert ex.parse_envelope(ok, task_id="t", agent="data_architect", node="entity_fields").proposals
