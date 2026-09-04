"""An agent's reply schema must carry every section its capability grants.

`data_model` may write four sections:

    data.entities  data.relationships  data.constraints  database

`DATA_MODEL_SCHEMA` carried `entities` alone. Three of the four had no channel,
so the agent could not declare a single foreign key however clearly it saw one.
It said so itself, twice, in its own `change_requests` on a real build:

    "Response schema for this agent has no channel for relationship artifacts;
     needs to be addable before foreign keys such as StockMovement->Item,
     PurchaseOrderLine->PurchaseOrder and SupplierPayment->SupplierInvoice can
     be declared with cardinality."

An agent that knows it cannot express what it owns reports low confidence for
it, which is how an EMR build blocked at 0.10 on a data model the same agent
described perfectly well when asked directly.

Two properties: the channel exists, and something drains it. A schema that
accepts relationships while `expand_data_model` ignores them is the same
silent loss wearing a different hat.

`database` is deliberately absent — it is engine and provider defaults
(postgres/neon), not something the agent discovers from requirements.
"""
import pytest

from services.blueprint.executors import (
    DAG, DATA_MODEL_SCHEMA, expand_data_model, writable_shapes,
)

#: Sections the reply must be able to carry, keyed by the schema property that
#: carries them. `database` is excluded — see the module docstring.
CHANNELS = {
    "data.entities": "entities",
    "data.relationships": "relationships",
    "data.constraints": "constraints",
}


@pytest.mark.parametrize("section,prop", sorted(CHANNELS.items()))
def test_every_writable_section_has_a_reply_channel(section, prop):
    agent = DAG["data_model"].agent
    assert section in writable_shapes(agent), f"{section} is no longer writable"
    assert prop in DATA_MODEL_SCHEMA["properties"], (
        f"{agent} may write {section} and its reply schema cannot carry it"
    )


def _reply(**over):
    base = {
        "entities": [
            {"name": "Item", "table": "items",
             "fields": [{"name": "code", "type": "string"}]},
            {"name": "StockMovement", "table": "stock_movements",
             "fields": [{"name": "quantity", "type": "integer"}]},
        ],
        "relationships": [{"from": "StockMovement", "to": "Item",
                           "kind": "one_to_many", "fromField": "itemId"}],
        "constraints": [{"entity": "StockMovement", "kind": "check",
                         "expression": "quantity <> 0"}],
        "confidence": 0.8, "assumptions": [], "issues": [], "change_requests": [],
    }
    base.update(over)
    return base


def _sections(props):
    return [p.section for p in props]


def test_a_declared_relationship_becomes_a_proposal():
    """Accepting it in the schema and dropping it here would be the same
    silent loss the channel was added to end."""
    props = expand_data_model(_reply())
    assert "data.relationships" in _sections(props)


def test_a_declared_constraint_becomes_a_proposal():
    props = expand_data_model(_reply())
    assert "data.constraints" in _sections(props)


def test_entities_are_unaffected():
    """The existing path must be untouched — every consumer downstream reads
    these proposals exactly as before."""
    props = expand_data_model(_reply())
    assert _sections(props).count("data.entities") == 2


def test_relationships_are_cited_by_name_not_id():
    """`DATA_MODEL_REPLY_RULES` forbids inventing ids; the contract types these
    as ENTITY-nnn. The reply names the entity and `resolve_batch_references`
    closes the gap at commit."""
    body = next(p.body for p in expand_data_model(_reply())
                if p.section == "data.relationships")
    assert body["from"] == "StockMovement" and body["to"] == "Item"


@pytest.mark.parametrize("bad", [
    {"relationships": [{"from": "", "to": "Item", "kind": "one_to_many"}]},
    {"relationships": [{"to": "Item", "kind": "one_to_many"}]},
    {"constraints": [{"entity": "Item", "kind": "check", "expression": ""}]},
    {"relationships": ["not an object"]},
])
def test_an_unusable_entry_is_skipped_not_fatal(bad):
    """One malformed entry must not cost the entities beside it."""
    props = expand_data_model(_reply(**bad))
    assert _sections(props).count("data.entities") == 2


def test_absent_channels_are_normal():
    """Most replies declare neither, and that is not a defect."""
    props = expand_data_model(_reply(relationships=[], constraints=[]))
    assert _sections(props) == ["data.entities", "data.entities"]
