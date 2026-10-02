"""A reference many rows share is never unique by itself.

HippieKit's rebuild (2026-09-22) spent three of its nine entity_fields repairs
on `unique` flags that could not be true: `ProductIngredient.productId` and
`RecentSearch.shopperId` — while the data model said a product has many
ingredients and a shopper many searches — and `Subscription.creditsRemaining`.
The first two contradict a relationship the Blueprint already states, so the
author is refused in the same attempt; the third is a question of meaning,
and the task now asks it.
"""
import pytest

from services.blueprint.agent_contract import (
    AgentResult, ArtifactProposal, InvalidEntityFields, check_entity_fields,
)
from services.blueprint.executors import NODE_TASKS

DOC = {"data": {
    "entities": [{"id": "ENTITY-001", "name": "Product"}, {"id": "ENTITY-002", "name": "Ingredient"},
                 {"id": "ENTITY-003", "name": "ProductIngredient"}],
    "relationships": [
        {"from": "ENTITY-001", "to": "ENTITY-003", "kind": "one_to_many", "fromField": "id", "toField": "productId"},
        {"from": "ENTITY-002", "to": "ENTITY-003", "kind": "one_to_many", "fromField": "id", "toField": "ingredientId"},
    ]}}


def _fields(*fields, constraints=()):
    proposals = [ArtifactProposal(section="data.entities", natural_key="ProductIngredient",
                                  body={"name": "ProductIngredient", "fields": [
                                      {"name": "id", "type": "uuid", "primaryKey": True, "unique": True},
                                      *fields]})]
    proposals += [ArtifactProposal(section="data.constraints", natural_key=f"c{i}", body=c)
                  for i, c in enumerate(constraints)]
    return AgentResult(task_id="T", agent="data_model", confidence=0.9, proposals=proposals)


def test_a_unique_reference_on_the_many_side_is_refused_naming_both():
    with pytest.raises(InvalidEntityFields) as e:
        check_entity_fields(_fields({"name": "productId", "type": "uuid", "unique": True},
                                    {"name": "ingredientId", "type": "uuid"}), DOC)
    said = str(e.value)
    assert "ProductIngredient.productId" in said and "one Product has many ProductIngredient" in said
    assert "constraint over both columns" in said
    assert "ingredientId" not in said


def test_the_same_references_without_the_flag_pass():
    check_entity_fields(_fields({"name": "productId", "type": "uuid"},
                                {"name": "ingredientId", "type": "uuid"},
                                constraints=[{"entity": "ProductIngredient", "kind": "unique",
                                              "expression": "(productId, ingredientId)"}]), DOC)


def test_a_unique_field_that_is_no_shared_reference_is_left_alone():
    check_entity_fields(_fields({"name": "code", "type": "string", "unique": True}), DOC)


def test_a_one_to_one_reference_may_be_unique():
    doc = {"data": {**DOC["data"], "relationships": [
        {"from": "ENTITY-001", "to": "ENTITY-003", "kind": "one_to_one", "fromField": "id", "toField": "productId"}]}}
    check_entity_fields(_fields({"name": "productId", "type": "uuid", "unique": True}), doc)


def test_the_author_is_asked_whether_two_records_could_share_the_value():
    task = NODE_TASKS["entity_fields"]
    assert "could two records legitimately share this value" in task
    assert "one per pair" in task
