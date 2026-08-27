"""A page the plan calls a wizard must ship as a Wizard, not a flat form.

Three things already exist: the planner emits ``archetype: "wizard"``, the
library ships a full ``Wizard`` component (step progression, value
accumulation, review pane, workflow dispatch), and ``wizard_page_pass``
knows how to install it. They never met:

* ``effective_archetype`` collapsed ``wizard`` → ``form`` with the comment
  "a create wizard is still a create form", so the CRUD builder emitted a
  flat form and the archetype was gone before anything else could see it.
* ``wizard_page_pass`` triggers only on ``schema.wizard.steps``, which the
  planner does not author — it authors ``archetype``.

Live on pkiuqdrq that turned the Receive Stock Wizard — a three-step flow
the domain dossier names as a core pattern — into a single-page form.
"""
from __future__ import annotations

from services.deterministic_pages import effective_archetype
from services.wizard_page_pass import derive_steps_from_fields


class TestArchetypeSurvives:
    def test_wizard_is_not_collapsed_to_form(self):
        assert effective_archetype("/po/[id]/receive", "wizard") == "wizard"

    def test_route_shape_still_wins_for_real_crud(self):
        # /x/new is a create form no matter what hint rides along.
        assert effective_archetype("/products/new", "wizard") == "form"
        assert effective_archetype("/products/[id]/edit", "wizard") == "edit"

    def test_other_archetypes_unchanged(self):
        assert effective_archetype("/board", "kanban") == "kanban"
        assert effective_archetype("/cal", "calendar") == "calendar"
        assert effective_archetype("/items", "list") == "list"


class TestStepDerivation:
    def test_fields_split_into_ordered_steps(self):
        fields = [{"name": f"f{i}", "label": f"F{i}"} for i in range(7)]
        steps = derive_steps_from_fields(fields, per_step=3)
        assert [s["id"] for s in steps] == ["step-1", "step-2", "step-3"]
        assert [len(s["fields"]) for s in steps] == [3, 3, 1]
        assert steps[0]["fields"][0]["name"] == "f0"

    def test_every_step_has_a_title(self):
        steps = derive_steps_from_fields(
            [{"name": "a", "label": "A"}, {"name": "b", "label": "B"}], per_step=1)
        assert all(s.get("title") for s in steps)

    def test_field_kind_and_required_are_carried(self):
        steps = derive_steps_from_fields([
            {"name": "qty", "label": "Qty", "kind": "number", "required": True},
            {"name": "note", "label": "Note"},
        ])
        f = steps[0]["fields"][0]
        assert f["kind"] == "number" and f["required"] is True

    def test_unknown_kind_falls_back_to_text(self):
        steps = derive_steps_from_fields([
            {"name": "x", "label": "X", "kind": "wat"},
            {"name": "y", "label": "Y"},
        ])
        assert steps[0]["fields"][0]["kind"] == "text"

    def test_no_fields_yields_no_steps(self):
        # Better a flat form than a Wizard with nothing to collect.
        assert derive_steps_from_fields([]) == []
        assert derive_steps_from_fields(None) == []

    def test_a_single_field_does_not_become_a_wizard(self):
        assert derive_steps_from_fields([{"name": "a", "label": "A"}]) == []
