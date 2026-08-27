"""Tests for services.deterministic_pages.build_crud_page threading
page_hint['submit']['target'] into build_form_page.

Regression for the gap between Slice A T5 (which taught build_form_page
to honour submit_target) and the dispatcher build_crud_page (which
received the plan's whole page dict as page_hint but dropped the submit
sub-dict for form/edit archetypes). Any domain that authors a workflow
submit target in the plan — recruitment, retail, healthcare, whatever —
should see its Form.props.workflow set to that target.

Domain-agnostic: the assertions use string comparison against the
target passed in, never a hard-coded workflow name.
"""
from __future__ import annotations


def _find_form(node):
    if isinstance(node, dict):
        if (node.get("component") or node.get("type")) == "Form":
            return node
        for v in node.values():
            if isinstance(v, (dict, list)):
                r = _find_form(v)
                if r is not None:
                    return r
    elif isinstance(node, list):
        for i in node:
            r = _find_form(i)
            if r is not None:
                return r
    return None


# --------------------------------------------------------------------------- #
# Positive path — dispatcher threads submit.target through
# --------------------------------------------------------------------------- #

def test_form_archetype_reads_submit_target_from_page_hint():
    from services.deterministic_pages import build_crud_page

    plan_page = {
        "route": "/anything/new",
        "archetype": "form",
        "submit": {"kind": "workflow", "target": "PLAN_AUTHORED_WORKFLOW"},
    }
    page = build_crud_page(
        archetype="form",
        entity="Anything",
        columns={"field": {"type": "text"}},
        route="/anything/new",
        page_hint=plan_page,
    )
    form = _find_form(page)
    assert form is not None, "expected a Form node in the built page"
    assert form["props"]["workflow"] == "PLAN_AUTHORED_WORKFLOW", (
        "dispatcher must pass page_hint['submit']['target'] into build_form_page; "
        f"got Form.props.workflow={form['props'].get('workflow')!r}"
    )


def test_create_archetype_reads_submit_target_from_page_hint():
    # `create` is a valid alias of `form` in the dispatcher.
    from services.deterministic_pages import build_crud_page

    plan_page = {
        "route": "/x/new",
        "archetype": "create",
        "submit": {"kind": "workflow", "target": "SomeDomainWorkflow"},
    }
    page = build_crud_page(
        archetype="create",
        entity="X",
        columns={"field": {"type": "text"}},
        route="/x/new",
        page_hint=plan_page,
    )
    form = _find_form(page)
    assert form["props"]["workflow"] == "SomeDomainWorkflow"


def test_edit_archetype_reads_submit_target_from_page_hint():
    from services.deterministic_pages import build_crud_page

    plan_page = {
        "route": "/x/[id]/edit",
        "archetype": "edit",
        "submit": {"kind": "workflow", "target": "UpdateXViaWorkflow"},
    }
    page = build_crud_page(
        archetype="edit",
        entity="X",
        columns={"field": {"type": "text"}},
        route="/x/[id]/edit",
        page_hint=plan_page,
    )
    form = _find_form(page)
    assert form["props"]["workflow"] == "UpdateXViaWorkflow"


# --------------------------------------------------------------------------- #
# Backward-compat: absent / malformed submit falls back to CRUD default
# --------------------------------------------------------------------------- #

def test_no_page_hint_falls_back_to_crud_default_on_form():
    from services.deterministic_pages import build_crud_page

    page = build_crud_page(
        archetype="form",
        entity="Widget",
        columns={"name": {"type": "text"}},
        route="/widgets/new",
        # no page_hint at all
    )
    form = _find_form(page)
    assert form["props"]["workflow"] == "CreateWidget"


def test_page_hint_without_submit_falls_back_to_crud_default():
    from services.deterministic_pages import build_crud_page

    page = build_crud_page(
        archetype="form",
        entity="Widget",
        columns={"name": {"type": "text"}},
        route="/widgets/new",
        page_hint={"route": "/widgets/new", "archetype": "form"},  # no submit key
    )
    form = _find_form(page)
    assert form["props"]["workflow"] == "CreateWidget"


def test_page_hint_with_data_api_submit_falls_back_to_crud_default():
    """kind=data_api means the plan explicitly wants the CRUD path — no
    workflow target to thread. Legacy behaviour must be preserved."""
    from services.deterministic_pages import build_crud_page

    page = build_crud_page(
        archetype="form",
        entity="Widget",
        columns={"name": {"type": "text"}},
        route="/widgets/new",
        page_hint={"submit": {"kind": "data_api", "target": "Widget"}},
    )
    form = _find_form(page)
    # Same as if no page_hint — CRUD default. `target` is an entity name
    # for data_api, NOT a workflow name; we must not use it as a workflow.
    # (build_form_page treats non-empty submit_target as the workflow name,
    # so the dispatcher's job is to only pass workflow-kind targets.
    # For data_api kind, submit_target should be None.)
    assert form["props"]["workflow"] == "CreateWidget", (
        "data_api submit.target is an entity name, not a workflow — must "
        "not be threaded as workflow. Got "
        f"Form.props.workflow={form['props'].get('workflow')!r}"
    )


def test_page_hint_with_malformed_submit_falls_back_to_crud_default():
    from services.deterministic_pages import build_crud_page

    for bad_submit in (None, "not-a-dict", 42, {"kind": "workflow"}):  # last one: no target
        page = build_crud_page(
            archetype="form",
            entity="Widget",
            columns={"name": {"type": "text"}},
            route="/widgets/new",
            page_hint={"submit": bad_submit} if bad_submit is not None else {},
        )
        form = _find_form(page)
        assert form["props"]["workflow"] == "CreateWidget", (
            f"malformed submit ({bad_submit!r}) should fall back to CRUD default"
        )


# --------------------------------------------------------------------------- #
# Non-form archetypes are unaffected (safety guard)
# --------------------------------------------------------------------------- #

def test_list_archetype_ignores_submit_target():
    """List pages have no Form node; submit_target must not blow anything up."""
    from services.deterministic_pages import build_crud_page

    plan_page = {"submit": {"kind": "workflow", "target": "SomeWorkflow"}}
    page = build_crud_page(
        archetype="list",
        entity="Widget",
        columns={"name": {"type": "text"}},
        route="/widgets",
        page_hint=plan_page,
    )
    # Just needs to build without error; no Form to check.
    assert page is not None
    assert _find_form(page) is None
