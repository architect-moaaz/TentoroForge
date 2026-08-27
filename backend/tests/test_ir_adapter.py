"""Tests for the IR adapter — plan JSON → AppSpec conversion."""

import pytest
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.ir_adapter import plan_to_app_spec


# ---------------------------------------------------------------------------
# Sample plan (matches what the planner agent outputs)
# ---------------------------------------------------------------------------

SAMPLE_PLAN = {
    "module_name": "TaskFlow",
    "description": "A project management tool for engineering teams",
    "data_models": [
        {
            "name": "Task",
            "fields": [
                {"name": "id", "type": "String", "primaryKey": True},
                {"name": "title", "type": "String", "nullable": False},
                {"name": "description", "type": "Text"},
                {"name": "status", "type": "Enum", "enum_values": ["todo", "in_progress", "review", "done"]},
                {"name": "priority", "type": "Enum", "enum_values": ["low", "medium", "high"]},
                {"name": "assigneeId", "type": "String"},
                {"name": "dueDate", "type": "DateTime"},
                {"name": "createdAt", "type": "DateTime"},
            ],
            "indexes": ["title", "status"],
        },
        {
            "name": "User",
            "fields": [
                {"name": "id", "type": "String", "primaryKey": True},
                {"name": "name", "type": "String", "nullable": False},
                {"name": "email", "type": "String", "nullable": False},
                {"name": "avatar", "type": "String"},
                {"name": "role", "type": "Enum", "enum_values": ["admin", "member"]},
            ],
        },
    ],
    "relations": [
        {"from": "Task", "to": "User", "type": "many-to-one", "foreignKey": "assigneeId"},
    ],
    "api_routes": [
        {"method": "GET", "path": "/api/tasks", "entity": "Task"},
        {"method": "POST", "path": "/api/tasks", "entity": "Task"},
        {"method": "GET", "path": "/api/tasks/{id}", "entity": "Task"},
        {"method": "PUT", "path": "/api/tasks/{id}", "entity": "Task"},
        {"method": "DELETE", "path": "/api/tasks/{id}", "entity": "Task"},
        {"method": "GET", "path": "/api/users", "entity": "User"},
        {"method": "POST", "path": "/api/users", "entity": "User"},
    ],
    "pages": [
        {"route": "/tasks", "name": "Task List", "description": "Browse and manage tasks"},
        {"route": "/tasks/new", "name": "Create Task", "description": "Create a new task"},
        {"route": "/tasks/:id", "name": "Task Detail", "description": "View task details"},
        {"route": "/users", "name": "User List", "description": "Manage team members"},
    ],
}


class TestPlanToAppSpec:
    """Test plan_to_app_spec conversion."""

    def test_basic_conversion(self):
        spec = plan_to_app_spec(SAMPLE_PLAN)
        assert spec["name"] == "TaskFlow"
        assert spec["description"] == "A project management tool for engineering teams"

    def test_entities_extracted(self):
        spec = plan_to_app_spec(SAMPLE_PLAN)
        entities = spec["entities"]
        assert len(entities) == 2

        task = next(e for e in entities if e["name"] == "Task")
        user = next(e for e in entities if e["name"] == "User")

        assert task is not None
        assert user is not None

    def test_fields_converted(self):
        spec = plan_to_app_spec(SAMPLE_PLAN)
        task = next(e for e in spec["entities"] if e["name"] == "Task")

        field_names = [f["name"] for f in task["fields"]]
        # Primary key (id) should be excluded
        assert "id" not in field_names
        # Regular fields should be included
        assert "title" in field_names
        assert "description" in field_names
        assert "status" in field_names

    def test_field_types_mapped(self):
        spec = plan_to_app_spec(SAMPLE_PLAN)
        task = next(e for e in spec["entities"] if e["name"] == "Task")
        fields = {f["name"]: f for f in task["fields"]}

        assert fields["title"]["type"] == "string"
        assert fields["title"]["required"] is True
        assert fields["description"]["type"] == "text"  # Text → text (long text)
        assert fields["status"]["type"] == "enum"
        assert fields["status"]["values"] == ["todo", "in_progress", "review", "done"]
        assert fields["dueDate"]["type"] == "datetime"

    def test_relation_fields_detected(self):
        spec = plan_to_app_spec(SAMPLE_PLAN)
        task = next(e for e in spec["entities"] if e["name"] == "Task")
        fields = {f["name"]: f for f in task["fields"]}

        assert fields["assigneeId"]["type"] == "relation"
        assert fields["assigneeId"]["relationTo"] == "Assignee"

    def test_capabilities_inferred_from_routes(self):
        spec = plan_to_app_spec(SAMPLE_PLAN)
        task = next(e for e in spec["entities"] if e["name"] == "Task")

        caps = task["capabilities"]
        assert "list" in caps
        assert "search" in caps
        assert "create" in caps
        assert "detail" in caps
        assert "edit" in caps
        assert "delete" in caps

    def test_avatar_field_detection(self):
        spec = plan_to_app_spec(SAMPLE_PLAN)
        user = next(e for e in spec["entities"] if e["name"] == "User")
        fields = {f["name"]: f for f in user["fields"]}

        assert fields["avatar"]["type"] == "avatar"
        assert fields["avatar"]["isIdentityImage"] is True

    def test_email_field_detection(self):
        spec = plan_to_app_spec(SAMPLE_PLAN)
        user = next(e for e in spec["entities"] if e["name"] == "User")
        fields = {f["name"]: f for f in user["fields"]}

        assert fields["email"]["type"] == "email"

    def test_relationships_converted(self):
        spec = plan_to_app_spec(SAMPLE_PLAN)
        rels = spec["relationships"]
        assert len(rels) == 1
        assert rels[0]["to"] == "User"
        assert rels[0]["type"] == "many-to-one"

    def test_custom_app_name(self):
        spec = plan_to_app_spec(SAMPLE_PLAN, app_name="Custom Name")
        assert spec["name"] == "Custom Name"

    def test_empty_plan(self):
        spec = plan_to_app_spec({})
        assert spec["name"] == "My App"
        assert spec["entities"] == []
        assert spec["relationships"] == []

    def test_minimal_entity(self):
        plan = {
            "module_name": "Tags",
            "data_models": [
                {
                    "name": "Tag",
                    "fields": [
                        {"name": "id", "type": "String", "primaryKey": True},
                        {"name": "name", "type": "String", "nullable": False},
                    ],
                }
            ],
            "api_routes": [
                {"method": "GET", "path": "/api/tags", "entity": "Tag"},
                {"method": "POST", "path": "/api/tags", "entity": "Tag"},
            ],
            "pages": [],
            "relations": [],
        }
        spec = plan_to_app_spec(plan)
        assert len(spec["entities"]) == 1
        tag = spec["entities"][0]
        assert tag["name"] == "Tag"
        assert len(tag["fields"]) == 1  # id excluded
        assert "list" in tag["capabilities"]
        assert "create" in tag["capabilities"]
