"""Tests for services.blueprint_builder — the pure Markdown builder."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.blueprint_builder import (
    BLUEPRINT_VERSION,
    build_blueprint,
    _mermaid_id,
    _resolve_fk_target,
    _extract_entities,
    _Sources,
)


# --------------------------------------------------------------------------- #
# Fixture builder — writes just the contract files each test needs
# --------------------------------------------------------------------------- #

def _write(root: Path, rel: str, content: dict | str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        p.write_text(content, encoding="utf-8")
    else:
        p.write_text(json.dumps(content, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Header + degradation
# --------------------------------------------------------------------------- #

class TestEmptyDir:
    def test_empty_dir_still_renders(self, tmp_path):
        md = build_blueprint(tmp_path)
        assert md.startswith("# Untitled App")
        assert f"Blueprint version {BLUEPRINT_VERSION}" in md
        # Architecture is fixed even when no package.json.
        assert "## Architecture" in md

    def test_no_data_model_when_no_entities(self, tmp_path):
        md = build_blueprint(tmp_path)
        assert "_No entities on record yet._" in md
        # And no ER mermaid block.
        assert "erDiagram" not in md

    def test_no_workflows_section_when_none(self, tmp_path):
        md = build_blueprint(tmp_path)
        assert "## Workflows" not in md


class TestHeader:
    def test_app_name_from_plan(self, tmp_path):
        _write(tmp_path, "contracts/plan.json", {"name": "My Great App"})
        md = build_blueprint(tmp_path)
        assert md.startswith("# My Great App")

    def test_app_name_falls_back_to_package(self, tmp_path):
        _write(tmp_path, "package.json", {"name": "pkg-name"})
        md = build_blueprint(tmp_path)
        assert md.startswith("# pkg-name")

    def test_description_from_dossier(self, tmp_path):
        _write(tmp_path, "contracts/generation-dossier.json", {
            "prompt": "A property manager app",
        })
        md = build_blueprint(tmp_path)
        assert "> A property manager app" in md


class TestArchitecture:
    def test_default_versions(self, tmp_path):
        md = build_blueprint(tmp_path)
        assert "Frontend: Next.js" in md
        assert "Auth: NextAuth" in md

    def test_versions_from_package_json(self, tmp_path):
        _write(tmp_path, "package.json", {
            "dependencies": {"next": "^14.2.0", "react": "^18.3.0"},
        })
        md = build_blueprint(tmp_path)
        assert "Next.js ^14.2.0" in md
        assert "React ^18.3.0" in md


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #

class TestDataModel:
    def test_entities_from_resource_registry(self, tmp_path):
        _write(tmp_path, "contracts/resource-registry.json", {
            "entities": {
                "User": {
                    "columns": [
                        {"name": "id", "type": "uuid",
                         "primaryKey": True, "notNull": True},
                        {"name": "email", "type": "text", "notNull": True},
                    ],
                },
                "Post": {
                    "columns": [
                        {"name": "id", "type": "uuid", "primaryKey": True},
                        {"name": "authorId", "type": "uuid", "fk": "user"},
                    ],
                },
            },
        })
        md = build_blueprint(tmp_path)
        assert "## Data Model" in md
        assert "erDiagram" in md
        assert "User {" in md
        assert "Post {" in md
        # FK relationship
        assert 'Post }o--|| User : "authorId"' in md
        # Table row
        assert "**User**" in md
        assert "**Post**" in md

    def test_entities_from_flat_registry(self, tmp_path):
        _write(tmp_path, "registry.json", {
            "entities": {
                "Widget": {
                    "fields": {
                        "id": {"type": "uuid", "primaryKey": True,
                               "nullable": False},
                        "name": {"type": "text", "nullable": True},
                    },
                },
            },
        })
        md = build_blueprint(tmp_path)
        assert "**Widget**" in md
        assert "erDiagram" in md

    def test_entities_from_plan_only(self, tmp_path):
        _write(tmp_path, "contracts/plan.json", {
            "entities": {
                "Task": {"purpose": "a unit of work", "fields": [
                    {"name": "title", "type": "text"},
                ]},
            },
        })
        md = build_blueprint(tmp_path)
        assert "**Task**" in md
        assert "a unit of work" in md

    def test_resource_registry_wins_over_plan(self, tmp_path):
        """When both sources have the same entity, resource-registry
        wins (richer column info)."""
        _write(tmp_path, "contracts/resource-registry.json", {
            "entities": {"User": {"columns": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "email", "type": "text"},
            ]}},
        })
        _write(tmp_path, "contracts/plan.json", {
            "entities": {"User": {"fields": [{"name": "different"}]}},
        })
        entities = _extract_entities(_Sources(tmp_path))
        users = [e for e in entities if e["name"] == "User"]
        assert len(users) == 1
        col_names = [c["name"] for c in users[0]["columns"]]
        assert "email" in col_names
        assert "different" not in col_names


class TestERDiagram:
    def test_fk_target_case_insensitive(self):
        ids = {"Unit": "Unit", "Property": "Property"}
        assert _resolve_fk_target("unit", ids) == "Unit"
        assert _resolve_fk_target("UNIT", ids) == "Unit"

    def test_fk_target_kebab_to_camel(self):
        ids = {"RecruitmentDrive": "RecruitmentDrive"}
        assert _resolve_fk_target("recruitment-drive", ids) == "RecruitmentDrive"

    def test_fk_target_missing_returns_none(self):
        assert _resolve_fk_target("nope", {"User": "User"}) is None


class TestMermaidIds:
    def test_alphanumeric_pass_through(self):
        assert _mermaid_id("dashboard") == "dashboard"
        assert _mermaid_id("user_page") == "user_page"

    def test_slashes_and_dashes_replaced(self):
        assert _mermaid_id("candidates/[id]") == "candidates__id_"
        assert _mermaid_id("with-dashes") == "with_dashes"

    def test_digit_prefix_padded(self):
        assert _mermaid_id("123abc").startswith("n_")

    def test_reserved_words_padded(self):
        # `end` breaks flowcharts — regression guard for the fix.
        assert _mermaid_id("end") == "n_end"
        assert _mermaid_id("subgraph") == "n_subgraph"


# --------------------------------------------------------------------------- #
# Pages + navigation
# --------------------------------------------------------------------------- #

class TestPages:
    def test_pages_from_nav_flow(self, tmp_path):
        _write(tmp_path, "contracts/nav-flow.json", {
            "pages": [
                {"id": "home", "route": "/", "title": "Home",
                 "schemaFile": "src/schemas/home.json"},
                {"id": "u", "route": "/users", "title": "Users"},
            ],
            "transitions": [
                {"from": "home", "to": "u", "trigger": "link"},
            ],
        })
        md = build_blueprint(tmp_path)
        assert "## Pages" in md
        assert "| `/`" in md
        assert "| `/users`" in md
        # Nav flowchart
        assert "## Navigation" in md
        assert "flowchart LR" in md

    def test_pages_from_schemas_fallback(self, tmp_path):
        _write(tmp_path, "src/schemas/dashboard.json", {
            "route": "/dashboard", "id": "dashboard",
            "dataSources": [{"name": "u", "entity": "User", "op": "list"}],
        })
        md = build_blueprint(tmp_path)
        assert "/dashboard" in md
        # Page detail should render component / data-source summary
        assert "Data sources" in md
        assert "list User" in md


class TestNavigation:
    def test_screen_graph_fallback(self, tmp_path):
        _write(tmp_path, "navigation.json", {
            "screens": [
                {"id": "s1", "data": {"label": "One", "route": "/one"}},
                {"id": "s2", "data": {"label": "Two", "route": "/two"}},
            ],
            "edges": [{"source": "s1", "target": "s2", "label": "next"}],
        })
        md = build_blueprint(tmp_path)
        assert "## Navigation" in md
        assert "flowchart LR" in md
        assert "-->|next|" in md


# --------------------------------------------------------------------------- #
# Workflows
# --------------------------------------------------------------------------- #

class TestWorkflows:
    def test_workflow_summary_and_diagram(self, tmp_path):
        _write(tmp_path, "workflows/CreateUser.json", {
            "name": "CreateUser",
            "description": "Insert a user record.",
            "processVariables": [{"name": "email", "type": "string"}],
            "definition": {
                "trigger": {"type": "manual"},
                "nodes": [
                    {"id": "trigger", "type": "trigger",
                     "data": {"label": "Start"}},
                    {"id": "insert", "type": "action",
                     "data": {"label": "Insert"}},
                    {"id": "end", "type": "end", "data": {"label": "Done"}},
                ],
                "edges": [
                    {"source": "trigger", "target": "insert"},
                    {"source": "insert", "target": "end"},
                ],
            },
        })
        md = build_blueprint(tmp_path)
        assert "## Workflows" in md
        assert "**CreateUser**" in md
        assert "### CreateUser" in md
        assert "flowchart TD" in md
        # 'end' must be padded so Mermaid doesn't parse it as a keyword
        assert "n_end" in md
        assert "Insert a user record." in md

    def test_workflow_straight_line_fallback_without_edges(self, tmp_path):
        _write(tmp_path, "workflows/Simple.json", {
            "name": "Simple",
            "definition": {
                "nodes": [
                    {"id": "a", "type": "trigger", "data": {"label": "A"}},
                    {"id": "b", "type": "action", "data": {"label": "B"}},
                ],
            },
        })
        md = build_blueprint(tmp_path)
        assert "a --> b" in md


# --------------------------------------------------------------------------- #
# Design
# --------------------------------------------------------------------------- #

class TestDesign:
    def test_palette_and_typography_from_brief(self, tmp_path):
        _write(tmp_path, "contracts/brief.json", {
            "palette": {"brand": "#123456", "accent": "#ABCDEF"},
            "typography": {"display_family": "DM Sans",
                           "body_family": "Inter"},
            "layout": {"density": "compact"},
            "identity": {"visual_stance": {"temperature": "cool"}},
        })
        md = build_blueprint(tmp_path)
        assert "### Palette" in md
        assert "#123456" in md
        assert "DM Sans" in md
        assert "compact" in md
        assert "Visual stance" in md
        # SVG swatch included.
        assert "data:image/svg+xml" in md

    def test_palette_from_design_spec_fallback(self, tmp_path):
        _write(tmp_path, "contracts/design-spec.json", {
            "colorPalette": {"primary": "#000", "background": "#FFF"},
        })
        md = build_blueprint(tmp_path)
        assert "### Palette" in md
        assert "#000" in md


class TestContentBank:
    def test_content_bank_rendered(self, tmp_path):
        _write(tmp_path, "contracts/brief.json", {
            "content_bank": {
                "taglines": ["The best.", "The only."],
                "cta_verbs": ["Ship", "Send"],
            },
        })
        md = build_blueprint(tmp_path)
        assert "## Content Bank" in md
        assert "Taglines" in md
        assert "The best." in md
        assert "CTA verbs" in md

    def test_content_bank_absent(self, tmp_path):
        md = build_blueprint(tmp_path)
        assert "## Content Bank" not in md


# --------------------------------------------------------------------------- #
# Actors
# --------------------------------------------------------------------------- #

class TestActors:
    def test_actors_from_plan(self, tmp_path):
        _write(tmp_path, "contracts/plan.json", {
            "actors": [
                {"name": "Manager", "permissions": ["read", "write"]},
                "Tenant",
            ],
        })
        md = build_blueprint(tmp_path)
        assert "## Actors & Roles" in md
        assert "**Manager**" in md
        assert "read, write" in md
        assert "**Tenant**" in md

    def test_actors_from_access_model_roles(self, tmp_path):
        _write(tmp_path, "contracts/resource-registry.json", {
            "accessModel": {
                "roles": [{"name": "admin"}, {"name": "viewer"}],
            },
            "entities": {},
        })
        md = build_blueprint(tmp_path)
        assert "## Actors & Roles" in md
        assert "**admin**" in md


# --------------------------------------------------------------------------- #
# Forms
# --------------------------------------------------------------------------- #

class TestForms:
    def test_form_table_from_schemas(self, tmp_path):
        _write(tmp_path, "src/schemas/users/new.json", {
            "route": "/users/new",
            "components": [{
                "component": "Form",
                "props": {
                    "resource": "User",
                    "fields": [
                        {"name": "email"}, {"name": "password"},
                    ],
                    "submit": {"kind": "create"},
                },
            }],
        })
        md = build_blueprint(tmp_path)
        assert "## Forms" in md
        assert "/users/new" in md
        assert "email, password" in md
        assert "create" in md


# --------------------------------------------------------------------------- #
# Generation log
# --------------------------------------------------------------------------- #

class TestGenerationLog:
    def test_log_reads_hidden_jsonl(self, tmp_path):
        (tmp_path / ".blueprint-log.jsonl").write_text(
            '{"ts": "2026-08-09 00:00:00 UTC", "source": "generation", '
            '"summary": "first"}\n'
            '{"ts": "2026-08-09 01:00:00 UTC", "source": "smith", '
            '"summary": "edit"}\n',
            encoding="utf-8",
        )
        md = build_blueprint(tmp_path)
        assert "## Generation Log" in md
        # Newest first.
        idx_smith = md.find("edit")
        idx_first = md.find("first")
        assert 0 <= idx_smith < idx_first

    def test_log_absent_when_no_file(self, tmp_path):
        md = build_blueprint(tmp_path)
        assert "## Generation Log" not in md


# --------------------------------------------------------------------------- #
# Robustness
# --------------------------------------------------------------------------- #

class TestRobustness:
    def test_malformed_json_does_not_raise(self, tmp_path):
        _write(tmp_path, "contracts/plan.json", "not-json{{{")
        # Should not crash.
        md = build_blueprint(tmp_path)
        assert "# Untitled App" in md  # falls back gracefully

    def test_unexpected_types_do_not_raise(self, tmp_path):
        # `pages` as a string instead of a list.
        _write(tmp_path, "contracts/plan.json", {"pages": "oops"})
        md = build_blueprint(tmp_path)
        assert "Blueprint version" in md

    def test_deterministic_body(self, tmp_path):
        _write(tmp_path, "contracts/plan.json", {"name": "A", "entities": {}})
        md1 = build_blueprint(tmp_path)
        md2 = build_blueprint(tmp_path)
        # Timestamps differ, but the body below the header should not.
        import re
        strip = lambda s: re.sub(r"^_Last built:.*_$", "", s, flags=re.MULTILINE)
        assert strip(md1) == strip(md2)
