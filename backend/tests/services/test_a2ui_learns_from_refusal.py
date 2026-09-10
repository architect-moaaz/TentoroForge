"""A2UI is told why its last composition was thrown away.

The orchestrator records the validator's own message
(`state.feedback[subject] = _reason(exc)`), threads it into the retry's
TaskSpec, and the authoring agent's prompt reads it — "Your previous attempt
was rejected:". That loop was intact.

But a `page_layouts` retry runs `_compose_via_a2ui` FIRST, unconditionally, on
every attempt. A2UI was told nothing, so a page refused for `'items' is a
required property` was recomposed by a composer with no idea it had been
refused — and if that composition cleared the floor again, it returned early
and the agent that HAD been told never ran. §102: a retry that is not told what
went wrong is the same request again.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from services.blueprint.agent_contract import InvalidPatternTemplate

from services.a2ui_authority import build_domain_context, build_requirement


def test_the_refusal_reaches_the_composer(tmp_path):
    ctx = build_domain_context(tmp_path, registry={"entities": {}},
                               feedback="PAGE-009: 'items' is a required property")
    assert "'items' is a required property" in ctx
    assert "without that fault" in ctx


def test_saying_nothing_adds_nothing(tmp_path):
    """A first attempt must be byte-identical to what it always was — this is
    the cached prefix as well as the brief."""
    plain = build_domain_context(tmp_path, registry={"entities": {}})
    assert plain == build_domain_context(tmp_path, registry={"entities": {}},
                                         feedback="   ")


def test_the_refusal_is_not_put_where_it_becomes_a_demand(tmp_path):
    """THE REASON IT IS IN THE DOMAIN CONTEXT AND NOT THE REQUIREMENT.

    The A2UI server scans the REQUIREMENT for capability keywords and makes
    every match mandatory (`req = (requirement or "").lower()` in
    tools/a2ui-mcp/checks.py; the domain context is never read). A rejection
    that happened to mention a table or a chart would become a demand on the
    retry — so the message explaining the last failure would cause the next
    one, on a page that never wanted either.
    """
    keywords = ("chart", "graph", "trend", "table", "timeline", "kanban",
                "kpi", "metric", "badge", "pill")
    refusal = ("PAGE-047: bulkActions.0: 'workflow' is a required property; "
               "the table of votes and its chart were both rejected")

    req = build_requirement(tmp_path, "collection", "/votes")
    assert not any(re.search(rf"\b{k}\b", req, re.I) for k in keywords), (
        "the collection brief already names a component — a different bug")

    # The refusal is carried, and it is carried somewhere unscanned.
    ctx = build_domain_context(tmp_path, registry={"entities": {}},
                               feedback=refusal)
    assert "bulkActions" in ctx
    assert "feedback" not in inspect.signature(build_requirement).parameters, (
        "the refusal must not be able to reach the scanned requirement")


def test_the_executor_hands_the_spec_feedback_over():
    """The hop that was missing. Everything upstream of it already worked."""
    from services.blueprint import executors

    src = inspect.getsource(executors.make_executor)
    assert "feedback=spec.feedback or \"\"" in src


def test_the_orchestrator_still_records_the_validator_message():
    """The other end of the same loop, pinned so a refactor cannot quietly
    drop it — this is what the composer is now being told.

    Asserted by running the round rather than by reading its source. The
    source-text version pinned one statement, and the statement moved into a
    helper during an unrelated refactor while the behaviour it guarded stayed
    exactly the same — a red test that proved nothing about the loop.
    """
    from services.blueprint import orchestrator
    from services.blueprint.orchestrator import RunReport, _NodeRun

    state = _NodeRun(subjects=["PAGE-009"], pending=["PAGE-009"])
    refusal = InvalidPatternTemplate("bulkActions is not in the catalog")

    retry = orchestrator._apply_round(
        None, "page_layouts", state,
        {("page_layouts", "PAGE-009"): refusal},
        attempt=1, max_attempts=2, commit=False,
        user_request="", report=RunReport(),
    )

    # It goes round again, and it is told why.
    assert retry == ["PAGE-009"]
    assert "bulkActions" in state.feedback["PAGE-009"]


# ─────────────────── the other half: a refusal the composer cannot act on
#
# Everything above routes the validator's message back to the A2UI composer,
# which is right when the composer is at fault. It was not, here. gh0mlpbp's
# PAGE-003 was refused twice for `'items' is a required property` against two
# saved surfaces that BOTH carry a well-formed `KeyValueList.items` — the
# binder dropped the prop, downstream of the composer, and the composer was
# told it had omitted what it had supplied. It rewrote the screen (the two
# surfaces differ) and could not possibly have fixed it. The page was
# abandoned, `/items/[id]` got no layout, and the shipped app 404s on it.
#
# The checks that refuse the tree at commit now also run at compose time, so a
# binder fault declines the composition instead of being attributed to the
# model — and the decline reason reaches `spec.feedback`, i.e. the LLM page
# author, which writes the Forge tree itself and CAN act on a missing prop.


def test_a_tree_the_commit_will_reject_is_refused_at_compose_time(tmp_path,
                                                                  monkeypatch):
    """`Tabs` without `tabs` fails `validate_props` — the same function, the
    same catalog, one round earlier."""
    monkeypatch.setenv("FORGE_A2UI", "1")
    from tests.services.test_a2ui_authority import _app, _surface
    from services.a2ui_authority import compose_page_via_a2ui

    root = _app(tmp_path)
    surface = _surface(
        [{"id": "root", "component": "Stack", "children": ["t", "tabs"]},
         {"id": "t", "component": "Table", "rows": {"path": "/bills/rows"}},
         {"id": "tabs", "component": "Tabs", "value": "overview"}],
        {"bills": {"rows": []}})
    res = compose_page_via_a2ui(str(root), "/bills", "list",
                                surface_provider=surface)
    assert res["applied"] is False
    assert "'tabs' is a required property" in res["reason"]


def test_the_refusal_names_the_drop_that_caused_it(tmp_path, monkeypatch):
    """"'data' is a required property" is a true statement about the tree and
    a useless one about the failure: the prop was in the payload and the
    translation removed it. Whoever is asked next has to be told which."""
    monkeypatch.setenv("FORGE_A2UI", "1")
    from tests.services.test_a2ui_authority import _app, _surface
    from services.a2ui_authority import compose_page_via_a2ui

    root = _app(tmp_path)
    surface = _surface(
        [{"id": "root", "component": "Stack", "children": ["t", "s"]},
         {"id": "t", "component": "Table", "rows": {"path": "/bills/rows"}},
         # A fabricated sparkline: `data` is required AND is measurement, so
         # the binder drops it and the tree then fails its own contract.
         {"id": "s", "component": "Sparkline", "data": [8, 9, 10, 11, 12]}],
        {"bills": {"rows": []}})
    res = compose_page_via_a2ui(str(root), "/bills", "list",
                                surface_provider=surface)
    assert res["applied"] is False
    assert "'data' is a required property" in res["reason"]
    assert "dropped a literal on a data prop" in res["reason"]
    assert "reproduces this exactly" in res["reason"]


def test_the_compose_seam_uses_the_commit_gates_own_checks():
    """Not a second opinion about what renders. Two implementations of that
    question are how the gate and the composer come to disagree about a page
    that is already on disk."""
    import inspect

    from services import a2ui_authority

    src = inspect.getsource(a2ui_authority._contract_errors)
    assert "validate_template" in src and "validate_props" in src
    assert "from services.blueprint.page_planner import" in src
