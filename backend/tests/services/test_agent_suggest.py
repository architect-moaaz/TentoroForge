"""An agent is drawn from the app's own Blueprint (services/agent_suggest.py).

The builder used to start from generic templates; a hand-drawn Movie Review agent offered "create a
rating" as a direct write the app refuses (a workflow does it, with the rules). These tests pin the
suggestion on a Movie-Review-shaped Blueprint: reads for what may be read, workflows for what the
app writes through a workflow, the rules on the tools they belong to, never a tool nobody may use,
and never a delete.
"""
from __future__ import annotations

import copy
import json
import uuid
from types import SimpleNamespace

import pytest

from services.agent_access import reconcile_agent
from services.agent_runtime_config import compile_agent
from services.agent_suggest import AGENT_ID, suggest_agent


def blueprint() -> dict:
    return {
        "application": {"id": "APP-1", "name": "Movie Review", "domain": "media",
                        "description": "A simple movie review app. An admin can add movies. Any signed-in user can "
                                       "rate movies. Design direction: Silver Screen — cool platinum."},
        "product": {"objectives": ["Admins keep a catalog", "Users rate and comment"]},
        "roles": [{"id": "ROLE-001", "name": "Admin", "description": "Manages the catalog."},
                  {"id": "ROLE-002", "name": "Reviewer", "description": "Rates and comments."}],
        "data": {
            "entities": [
                {"id": "ENTITY-001", "name": "User", "table": "users",
                 "fields": [{"name": "id", "type": "uuid"}, {"name": "email", "type": "string"},
                            {"name": "passwordHash", "type": "string"}]},
                {"id": "ENTITY-002", "name": "Movie", "table": "movies",
                 "fields": [{"name": "id", "type": "uuid"}, {"name": "title", "type": "string"},
                            {"name": "posterEmbedding", "type": "vector"}, {"name": "addedById", "type": "uuid"}]},
                {"id": "ENTITY-003", "name": "Rating", "table": "ratings",
                 "fields": [{"name": "id", "type": "uuid"}, {"name": "stars", "type": "integer"},
                            {"name": "movieId", "type": "uuid"}]},
                {"id": "ENTITY-004", "name": "Comment", "table": "comments",
                 "fields": [{"name": "id", "type": "uuid"}, {"name": "body", "type": "text"},
                            {"name": "movieId", "type": "uuid"}]},
                {"id": "ENTITY-005", "name": "Note", "table": "notes",
                 "fields": [{"name": "id", "type": "uuid"}, {"name": "text", "type": "text"}]},
            ],
            "relationships": [{"from": "ENTITY-003", "fromField": "movieId", "to": "ENTITY-002", "toField": "id"},
                              {"from": "ENTITY-002", "fromField": "addedById", "to": "ENTITY-001", "toField": "id"}],
        },
        "pages": [
            {"id": "PAGE-1", "name": "Movies", "users": ["ROLE-001", "ROLE-002"], "access": "authenticated",
             "data": {"primaryEntity": "ENTITY-002", "supportingEntities": ["ENTITY-003", "ENTITY-004"]}},
            {"id": "PAGE-2", "name": "Add Movie", "users": ["ROLE-001"], "access": "authenticated",
             "data": {"primaryEntity": "ENTITY-002"}},
            {"id": "PAGE-3", "name": "Notes", "users": ["ROLE-001", "ROLE-002"], "access": "authenticated",
             "data": {"primaryEntity": "ENTITY-005"}},
        ],
        "pageLayouts": [],
        "workflows": [
            {"id": "FLOW-001", "name": "AddMovie", "purpose": "Let an admin add a new movie to the catalog.",
             "trigger": {"kind": "manual"},
             "inputs": [{"kind": "field", "name": "title", "required": True, "type": "string"},
                        {"kind": "field", "name": "releaseYear", "required": True, "type": "integer"},
                        {"kind": "field", "name": "posterImage", "required": False, "type": "image"}],
             "steps": [{"key": "ins", "type": "action", "config": {"actionType": "db_insert", "table": "movies"}}]},
            {"id": "FLOW-002", "name": "SubmitRating", "purpose": "Let a signed-in user rate a movie.",
             "trigger": {"kind": "manual"},
             "inputs": [{"kind": "record", "entity": "ENTITY-002", "name": "movie", "required": True},
                        {"kind": "field", "name": "stars", "required": True, "type": "integer"}],
             "steps": [{"key": "q", "type": "action", "config": {"actionType": "db_query", "table": "ratings"}},
                       {"key": "ins", "type": "action", "config": {"actionType": "db_insert", "table": "ratings"}},
                       {"key": "upd", "type": "action", "config": {"actionType": "db_update", "table": "ratings"}}]},
            {"id": "FLOW-003", "name": "PostComment", "purpose": "Let a signed-in user post one comment.",
             "trigger": {"kind": "manual"},
             "inputs": [{"kind": "record", "entity": "ENTITY-002", "name": "movie", "required": True},
                        {"kind": "field", "name": "body", "required": True, "type": "text"}],
             "steps": [{"key": "ins", "type": "action", "config": {"actionType": "db_insert", "table": "comments"}}]},
            {"id": "FLOW-004", "name": "NightlyCleanup", "purpose": "Tidy up.", "trigger": {"kind": "schedule"},
             "inputs": [], "steps": [{"key": "d", "type": "action",
                                      "config": {"actionType": "db_delete", "table": "notes"}}]},
        ],
        "businessRules": [
            {"id": "RULE-001", "name": "AdminOnly", "statement": "Only an admin may add a movie.",
             "appliesTo": ["FLOW-001", "ENTITY-002"]},
            {"id": "RULE-002", "name": "OneRating", "statement": "A user has one rating per movie.",
             "appliesTo": ["FLOW-002", "ENTITY-003"]},
            {"id": "RULE-003", "name": "Permanent", "statement": "A comment is permanent once posted.",
             "appliesTo": ["FLOW-003", "ENTITY-004"]},
            {"id": "RULE-004", "name": "Retired", "statement": "Old rule.", "appliesTo": ["FLOW-002"],
             "status": "DEPRECATED"},
        ],
    }


def tools_of(agent: dict) -> dict[str, dict]:
    return {n["data"]["config"]["tool_name"]: n["data"]["config"] for n in agent["nodes"] if n["type"] == "tool"}


def test_the_agent_gets_reads_for_what_may_be_read_and_nothing_for_users():
    t = tools_of(suggest_agent(blueprint()))
    assert {"list_movies", "get_movie", "list_ratings", "get_rating", "list_comments", "get_comment"} <= set(t)
    assert not any("user" in name for name in t), "a table nobody may read is never offered"


def test_a_table_a_workflow_writes_is_written_through_the_workflow_only():
    t = tools_of(suggest_agent(blueprint()))
    for direct in ("add_movie_2", "add_rating", "update_rating", "add_comment", "update_comment", "update_movie"):
        assert direct not in t, f"{direct}: a direct write to a table a workflow owns"
    assert t["submit_rating"]["tool_type"] == "workflow" and t["submit_rating"]["workflow_id"] == "submit-rating"
    assert t["post_comment"]["workflow_id"] == "post-comment"
    assert t["add_movie"]["tool_type"] == "workflow" and t["add_movie"]["workflow_id"] == "add-movie"


def test_a_writable_table_no_workflow_writes_gets_a_direct_create_and_update():
    t = tools_of(suggest_agent(blueprint()))
    assert t["add_note"]["operation"] == "create" and t["update_note"]["operation"] == "update"


def test_there_is_never_a_delete_tool_and_a_scheduled_workflow_is_not_a_tool():
    agent = suggest_agent(blueprint())
    t = tools_of(agent)
    assert not any(c.get("operation") == "delete" or "delete" in name for name, c in t.items())
    assert "nightly_cleanup" not in t


def test_workflow_inputs_are_the_workflows_own_and_files_are_left_out():
    t = tools_of(suggest_agent(blueprint()))
    movie = {p["name"]: p for p in t["add_movie"]["parameters"]}
    assert set(movie) == {"title", "releaseYear"} and movie["releaseYear"]["type"] == "integer"
    assert movie["title"]["required"] is True
    rating = {p["name"]: p for p in t["submit_rating"]["parameters"]}
    assert rating["movie"]["type"] == "object" and rating["stars"]["type"] == "integer"


def test_a_rule_lands_only_on_the_tool_it_is_about():
    t = tools_of(suggest_agent(blueprint()))
    assert "one rating per movie" in t["submit_rating"]["description"]
    assert "admin may add a movie" not in t["submit_rating"]["description"]
    assert "admin may add a movie" in t["add_movie"]["description"]
    assert "permanent" in t["post_comment"]["description"]
    assert "Old rule" not in json.dumps(t), "a deprecated rule is not carried"


def test_the_fields_a_model_may_ask_for_exclude_secrets_and_vectors():
    t = tools_of(suggest_agent(blueprint()))
    assert "posterEmbedding" not in t["list_movies"]["description"]
    assert "title" in t["list_movies"]["description"]
    assert "movieId is the id of a movie" in t["list_ratings"]["description"]


def test_the_prompt_says_what_the_app_is_its_rules_and_that_it_cannot_hand_off():
    agent = suggest_agent(blueprint())
    prompt = next(n for n in agent["nodes"] if n["type"] == "system_prompt")["data"]["config"]["prompt"]
    assert prompt.startswith("You are the assistant for Movie Review.")
    assert "Silver Screen" not in prompt, "the design brief is not the assistant's business"
    assert "A comment is permanent once posted." in prompt and "Old rule" not in prompt
    assert "wait for a clear yes" in prompt
    assert "cannot transfer anyone to a person" in prompt
    assert "- Admin: Manages the catalog." in prompt


def test_no_box_that_does_nothing_is_drawn():
    kinds = {n["type"] for n in suggest_agent(blueprint())["nodes"]}
    assert kinds == {"system_prompt", "tool", "guardrail", "memory"}


def test_every_node_is_wired_to_the_prompt_and_ids_are_unique():
    agent = suggest_agent(blueprint())
    ids = [n["id"] for n in agent["nodes"]]
    assert len(ids) == len(set(ids))
    assert {e["target"] for e in agent["edges"]} == set(ids) - {"sp_1"}
    assert agent["id"] == AGENT_ID and agent["name"] == "Movie Review Assistant"


def test_the_same_app_always_gives_the_same_agent():
    assert suggest_agent(blueprint()) == suggest_agent(copy.deepcopy(blueprint()))


def test_the_suggestion_compiles_clean_and_needs_no_repair_at_install(tmp_path):
    """It must survive the install-time check untouched: no tool the app would refuse."""
    c = compile_agent(suggest_agent(blueprint()))
    assert c.warnings == [], c.warnings
    app = tmp_path / "app"
    (app / "src" / "lib").mkdir(parents=True)
    from services.blueprint.projection import project_entity_access
    project_entity_access(blueprint(), app)
    assert reconcile_agent(c.config, app) == []
    kinds = {t["name"]: t["kind"] for t in c.config["tools"]}
    assert kinds["submit_rating"] == "workflow" and kinds["list_movies"] == "data"


def test_an_app_with_no_entities_still_gets_a_usable_agent():
    agent = suggest_agent({"application": {"name": "Empty"}})
    assert agent["name"] == "Empty Assistant" and tools_of(agent) == {}
    assert compile_agent(agent).config["systemPrompt"].startswith("You are the assistant for Empty.")


# ---- the endpoint -------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_endpoint_returns_the_suggestion_and_saves_nothing(tmp_path, monkeypatch):
    from routers.agent_builder import suggest_agent_definition

    (tmp_path / ".forge" / "blueprint").mkdir(parents=True)
    (tmp_path / ".forge" / "blueprint" / "current.json").write_text(json.dumps(blueprint()), encoding="utf-8")
    proj = SimpleNamespace(id=uuid.uuid4(), output_dir=str(tmp_path))

    async def fake_get(project_id, user, db):
        return proj

    monkeypatch.setattr("routers.agent_builder.get_project_with_auth", fake_get)
    out = await suggest_agent_definition(proj.id, SimpleNamespace(id="u"), None)
    assert out["name"] == "Movie Review Assistant" and "submit_rating" in tools_of(out)
    assert not (tmp_path / "agent-definitions").exists(), "a suggestion is not saved until the person saves it"


@pytest.mark.asyncio
async def test_a_project_with_no_blueprint_is_told_to_build_first(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from routers.agent_builder import suggest_agent_definition

    proj = SimpleNamespace(id=uuid.uuid4(), output_dir=str(tmp_path))

    async def fake_get(project_id, user, db):
        return proj

    monkeypatch.setattr("routers.agent_builder.get_project_with_auth", fake_get)
    with pytest.raises(HTTPException) as e:
        await suggest_agent_definition(proj.id, SimpleNamespace(id="u"), None)
    assert e.value.status_code == 409 and "build the app first" in e.value.detail
