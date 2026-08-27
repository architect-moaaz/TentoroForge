"""Per-unit page-detail authoring + plan assembly — injectable LLM boundary.

The LLM is mocked via the ``_query`` seam (no network). Covers: form → authored
``fields``, malformed output → page unchanged, the deterministic short-circuit
(routine list page, NO ``_query`` call), full assembly over a 3-page skeleton,
and a raising ``_query`` falling back per-page while orchestration still returns
a full plan.
"""

import json
import os

from services.per_unit_authoring import author_all_units, author_page_detail
from services.resource_registry import build_canonical_registry


# A normalized, plan-shaped skeleton (as run_app_map_planner emits): data_models
# list + lean pages + workflows + roles.
def _skeleton() -> dict:
    return {
        "module_name": "field_ops",
        "data_models": [
            {
                "name": "Invoice",
                "table": "invoices",
                "fields": [
                    {"name": "id", "type": "uuid"},
                    {"name": "amount", "type": "numeric", "nullable": False},
                    {"name": "status", "type": "varchar"},
                ],
            },
            {
                "name": "Customer",
                "table": "customers",
                "fields": [
                    {"name": "id", "type": "uuid"},
                    {"name": "name", "type": "varchar"},
                ],
            },
        ],
        "pages": [
            {
                "route": "/invoices/new",
                "name": "New Invoice",
                "entity": "Invoice",
                "archetype": "form",
                "description": "Create an invoice",
            },
            {
                "route": "/dashboard",
                "name": "Dashboard",
                "entity": "Invoice",
                "archetype": "dashboard",
                "description": "Revenue overview",
            },
            {
                "route": "/invoices",
                "name": "Invoices",
                "entity": "Invoice",
                "archetype": "list",
                "description": "All invoices",
            },
        ],
        "workflows": [
            {"id": "issue-invoice", "trigger": "button", "entity": "Invoice"},
        ],
        "roles": ["admin"],
    }


class _RecordingQuery:
    """A fake ``_query`` that records calls and returns detail keyed by archetype."""

    def __init__(self):
        self.calls = []

    def __call__(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        if "dashboard" in user_prompt or "Dashboard" in user_prompt:
            return json.dumps({"widgets": [{"type": "stat", "entity": "invoices"}]})
        return json.dumps(
            {"fields": [{"name": "amount", "semanticType": "currency"}]}
        )


def test_form_page_gets_authored_fields(tmp_path):
    page = {
        "route": "/invoices/new",
        "name": "New Invoice",
        "entity": "Invoice",
        "archetype": "form",
    }

    def fake_query(system_prompt, user_prompt):
        return json.dumps({"fields": [{"name": "amount", "semanticType": "currency"}]})

    out = author_page_detail(page, str(tmp_path), _query=fake_query)
    assert out["fields"] == [{"name": "amount", "semanticType": "currency"}]
    # Original identity preserved.
    assert out["route"] == "/invoices/new"


def test_malformed_query_returns_page_unchanged(tmp_path):
    page = {"route": "/invoices/new", "entity": "Invoice", "archetype": "form"}

    def bad_query(system_prompt, user_prompt):
        return "not json at all <<<"

    out = author_page_detail(page, str(tmp_path), _query=bad_query)
    assert "fields" not in out
    assert out == page


def test_routine_list_page_short_circuits_without_llm(tmp_path):
    page = {"route": "/invoices", "entity": "Invoice", "archetype": "list"}
    called = {"n": 0}

    def fake_query(system_prompt, user_prompt):
        called["n"] += 1
        return json.dumps({"fields": []})

    out = author_page_detail(page, str(tmp_path), _query=fake_query)
    assert out == page
    assert called["n"] == 0  # deterministic short-circuit: NO LLM call


def test_author_all_units_assembles_full_plan(tmp_path):
    skeleton = _skeleton()
    q = _RecordingQuery()

    result = author_all_units(skeleton, str(tmp_path), _query=q)

    # Registry was written first so slices are readable.
    reg_path = os.path.join(str(tmp_path), "contracts", "resource-registry.json")
    assert os.path.isfile(reg_path)

    # Shape-identical to a one-shot plan.
    assert "data_models" in result
    assert "pages" in result
    assert "workflows" in result
    assert "roles" in result

    pages = result["pages"]
    assert len(pages) == 3
    by_route = {p["route"]: p for p in pages}

    # Form carries authored fields.
    assert by_route["/invoices/new"]["fields"] == [
        {"name": "amount", "semanticType": "currency"}
    ]
    # Dashboard carries authored widgets.
    assert by_route["/dashboard"]["widgets"] == [
        {"type": "stat", "entity": "invoices"}
    ]
    # List page unchanged — no detail key, no LLM call for it.
    assert "fields" not in by_route["/invoices"]
    assert "widgets" not in by_route["/invoices"]

    # Only the form + dashboard triggered the LLM (list short-circuited).
    assert len(q.calls) == 2

    # The assembled plan feeds build_canonical_registry unchanged → non-empty.
    registry = build_canonical_registry(result)
    assert registry["entities"]


def test_raising_query_falls_back_but_plan_is_full(tmp_path):
    skeleton = _skeleton()

    def raising_query(system_prompt, user_prompt):
        raise RuntimeError("LLM exploded")

    result = author_all_units(skeleton, str(tmp_path), _query=raising_query)

    # Orchestration never raised; full plan returned.
    assert "data_models" in result and "workflows" in result
    assert len(result["pages"]) == 3

    by_route = {p["route"]: p for p in result["pages"]}
    # Form page fell back to its skeleton form (no authored fields).
    assert "fields" not in by_route["/invoices/new"]
    # Still a valid registry from the assembled plan.
    assert build_canonical_registry(result)["entities"]
