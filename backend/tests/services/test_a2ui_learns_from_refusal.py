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
    drop it — this is what the composer is now being told."""
    from services.blueprint import orchestrator

    src = inspect.getsource(orchestrator._apply_round)
    assert "state.feedback[subject] = _reason(exc)" in src
    assert "InvalidPatternTemplate" in src
