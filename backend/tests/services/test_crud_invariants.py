"""Tests for services.crud_invariants — the "New X" button invariant.

Guarantees the reliability contract in one sweep: every LIST page over
a registered entity gets a header button navigating to that entity's
create route. Same-shape as the other post-gen guards.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.crud_invariants import (
    _find_header_row,
    _find_primary_entity,
    _has_create_button,
    _slug_for_entity,
    ensure_list_pages_have_create_action,
)


# --------------------------------------------------------------------------- #
# Fixture builders                                                             #
# --------------------------------------------------------------------------- #

def _write_entity(tmp_path: Path, name: str) -> None:
    d = tmp_path / "src" / "db" / "schema"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.ts").write_text(
        f'import {{ pgTable }} from "drizzle-orm/pg-core";\n'
        f'export const {name} = pgTable("{name}", {{}});\n'
    )


def _write_schema(tmp_path: Path, name: str, schema: dict) -> Path:
    d = tmp_path / "src" / "schemas"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.json"
    p.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    return p


def _list_page(*, entity: str, route: str, ds_name: str | None = None,
               with_button: bool = False, wrap_header: bool = True) -> dict:
    ds_name = ds_name or entity
    header_children: list[dict] = [
        {"type": "Heading", "props": {"content": entity + "s", "level": 1}},
    ]
    if with_button:
        header_children.append({
            "type": "Row", "props": {"gap": "tokens.spacing.2"},
            "children": [{
                "type": "Button", "props": {
                    "label": f"New {entity}", "variant": "primary",
                    "navigate": f"/{ds_name}/new",
                },
            }],
        })
    header_row = {
        "type": "Row", "props": {"justify": "between", "align": "center"},
        "children": header_children,
    }
    return {
        "name": entity + "List",
        "route": route,
        "dataSources": [{"name": ds_name, "entity": entity, "op": "list"}],
        "children": ([header_row] if wrap_header else []) + [
            {"type": "Table", "props": {
                "columns": [{"header": "Name", "value": "{{name}}"}],
                "rows": f"{{{{{ds_name}}}}}",
            }},
        ],
    }


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

class TestFindPrimaryEntity:
    def test_table_binding_names_entity(self):
        page = _list_page(entity="Applicant", route="/applicants")
        primary = _find_primary_entity(page)
        assert primary == ("Applicant", "Applicant")

    def test_no_list_component_returns_none(self):
        page = {
            "dataSources": [{"name": "x", "entity": "X", "op": "list"}],
            "children": [{"type": "Heading",
                          "props": {"content": "Hi", "level": 1}}],
        }
        assert _find_primary_entity(page) is None

    def test_no_data_source_returns_none(self):
        assert _find_primary_entity({"children": []}) is None


class TestHasCreateButton:
    def test_true_when_navigate_matches(self):
        page = _list_page(entity="Applicant", route="/applicants",
                          with_button=True)
        assert _has_create_button(page, "Applicant") is True

    def test_false_when_button_missing(self):
        page = _list_page(entity="Applicant", route="/applicants",
                          with_button=False)
        assert _has_create_button(page, "Applicant") is False

    def test_false_when_button_targets_different_route(self):
        page = _list_page(entity="Applicant", route="/applicants",
                          with_button=True)
        # Header button points at /applicants/new — a different slug
        # should still say False.
        assert _has_create_button(page, "OtherEntity") is False

    def test_true_when_navigate_lives_in_onclick(self):
        page = {
            "dataSources": [{"name": "x", "entity": "X", "op": "list"}],
            "children": [
                {"type": "Row", "props": {}, "children": [
                    {"type": "Heading", "props": {"content": "Xs", "level": 1}},
                    {"type": "Button", "props": {
                        "label": "New X",
                        "onClick": {"navigate": "/x/new"},
                    }},
                ]},
                {"type": "Table", "props": {"rows": "{{x}}"}},
            ],
        }
        assert _has_create_button(page, "x") is True


class TestSlugForEntity:
    def test_exact_match(self):
        assert _slug_for_entity("Applicant", {"Applicant"}, "/x") == "Applicant"

    def test_canonical_match(self):
        # Registered as camelCase, entity as PascalCase differing only
        # in first-letter casing.
        assert _slug_for_entity("applicant", {"Applicant"}, "/x") == "Applicant"

    def test_route_fallback(self):
        # Entity "ClassBooking" registered but the page's route is
        # /bookings — should still find something. Here we register the
        # /bookings slug too.
        assert _slug_for_entity(
            "ClassBooking",
            {"ClassBooking", "bookings"},
            "/bookings",
        ) == "ClassBooking"

    def test_none_when_no_match(self):
        assert _slug_for_entity("Unknown", {"Other"}, "/nope") is None


class TestFindHeaderRow:
    def test_matches_row_whose_first_child_is_heading(self):
        row = {"type": "Row", "props": {},
               "children": [{"type": "Heading", "props": {"content": "Hi"}}]}
        assert _find_header_row([row]) is row

    def test_ignores_row_without_heading(self):
        row = {"type": "Row", "children": [{"type": "Text", "props": {}}]}
        assert _find_header_row([row]) is None


# --------------------------------------------------------------------------- #
# Full sweep                                                                   #
# --------------------------------------------------------------------------- #

class TestEnsureListPagesHaveCreateAction:
    def test_inserts_missing_button(self, tmp_path: Path):
        _write_entity(tmp_path, "Applicant")
        p = _write_schema(tmp_path, "applicants",
                          _list_page(entity="Applicant", route="/applicants",
                                     with_button=False))
        result = ensure_list_pages_have_create_action(str(tmp_path))
        assert len(result.inserted) == 1
        assert result.inserted[0].slug == "Applicant"
        assert result.inserted[0].label == "New Applicant"
        # File actually changed.
        after = json.loads(p.read_text(encoding="utf-8"))
        assert _has_create_button(after, "Applicant") is True

    def test_idempotent(self, tmp_path: Path):
        _write_entity(tmp_path, "Applicant")
        _write_schema(tmp_path, "applicants",
                      _list_page(entity="Applicant", route="/applicants",
                                 with_button=True))
        result = ensure_list_pages_have_create_action(str(tmp_path))
        assert result.inserted == []
        assert len(result.already_present) == 1

    def test_skip_new_pages(self, tmp_path: Path):
        # A create-form page (/applicants/new) is not a list page. We
        # shouldn't add a button to itself.
        _write_entity(tmp_path, "Applicant")
        _write_schema(tmp_path, "applicants_new",
                      {"name": "NewApplicant",
                       "route": "/applicants/new",
                       "dataSources": [],
                       "children": [{"type": "Form", "props": {}}]})
        result = ensure_list_pages_have_create_action(str(tmp_path))
        assert result.inserted == []

    def test_skip_edit_pages(self, tmp_path: Path):
        _write_entity(tmp_path, "Applicant")
        _write_schema(tmp_path, "applicants_edit",
                      {"name": "EditApplicant",
                       "route": "/applicants/[id]/edit",
                       "dataSources": [],
                       "children": []})
        result = ensure_list_pages_have_create_action(str(tmp_path))
        assert result.inserted == []

    def test_multi_word_entity_generalizes(self, tmp_path: Path):
        # "ClassBooking" — the exact bug the user reported ("New booking"
        # missing). Registered as ClassBooking; the list page's
        # dataSource is bookings (route slug); page displays a Table.
        _write_entity(tmp_path, "ClassBooking")
        page = {
            "name": "BookingList",
            "route": "/bookings",
            "dataSources": [{"name": "bookings", "entity": "ClassBooking",
                             "op": "list"}],
            "children": [
                {"type": "Row", "props": {}, "children": [
                    {"type": "Heading", "props": {"content": "Bookings",
                                                  "level": 1}},
                ]},
                {"type": "Table", "props": {"rows": "{{bookings}}"}},
            ],
        }
        _write_schema(tmp_path, "bookings", page)
        result = ensure_list_pages_have_create_action(str(tmp_path))
        assert len(result.inserted) == 1
        assert result.inserted[0].slug == "ClassBooking"
        assert result.inserted[0].label == "New Class Booking"

    def test_kanban_counts_as_list(self, tmp_path: Path):
        # A kanban-mode entity view still needs a "New X" button.
        _write_entity(tmp_path, "Task")
        page = {
            "name": "TaskBoard",
            "route": "/tasks",
            "dataSources": [{"name": "Task", "entity": "Task", "op": "list"}],
            "children": [
                {"type": "Row", "props": {}, "children": [
                    {"type": "Heading",
                     "props": {"content": "Tasks", "level": 1}},
                ]},
                {"type": "Kanban", "props": {"items": "{{Task}}"}},
            ],
        }
        _write_schema(tmp_path, "tasks", page)
        result = ensure_list_pages_have_create_action(str(tmp_path))
        assert len(result.inserted) == 1

    def test_no_registered_slug_skips(self, tmp_path: Path):
        # No pgTable exports at all — data engine hasn't emitted schemas
        # yet. Guard exits cleanly.
        _write_schema(tmp_path, "applicants",
                      _list_page(entity="Applicant", route="/applicants",
                                 with_button=False))
        result = ensure_list_pages_have_create_action(str(tmp_path))
        assert result.inserted == []

    def test_entity_without_slug_recorded_as_skipped(self, tmp_path: Path):
        # Registered slug set exists but doesn't include this entity.
        _write_entity(tmp_path, "OtherThing")
        _write_schema(tmp_path, "applicants",
                      _list_page(entity="Applicant", route="/applicants",
                                 with_button=False))
        result = ensure_list_pages_have_create_action(str(tmp_path))
        assert result.inserted == []
        assert any(s.get("entity") == "Applicant" for s in result.skipped)

    def test_synthesizes_header_when_none_exists(self, tmp_path: Path):
        _write_entity(tmp_path, "Applicant")
        page = {
            "name": "ApplicantList",
            "route": "/applicants",
            "dataSources": [{"name": "Applicant", "entity": "Applicant",
                             "op": "list"}],
            "children": [
                {"type": "Table", "props": {"rows": "{{Applicant}}"}},
            ],
        }
        p = _write_schema(tmp_path, "applicants", page)
        result = ensure_list_pages_have_create_action(str(tmp_path))
        assert len(result.inserted) == 1
        after = json.loads(p.read_text(encoding="utf-8"))
        assert _has_create_button(after, "Applicant") is True
        # Header row synthesized at top of children.
        assert after["children"][0]["type"] == "Row"

    def test_never_raises_on_malformed_schema(self, tmp_path: Path):
        _write_entity(tmp_path, "Applicant")
        # Non-dict children — degenerate but shouldn't crash the sweep.
        _write_schema(tmp_path, "broken", {
            "name": "Broken", "route": "/broken",
            "dataSources": [{"name": "x", "entity": "Applicant", "op": "list"}],
            "children": "not a list",
        })
        _write_schema(tmp_path, "applicants",
                      _list_page(entity="Applicant", route="/applicants",
                                 with_button=False))
        result = ensure_list_pages_have_create_action(str(tmp_path))
        # The valid page was still fixed.
        assert len(result.inserted) == 1
