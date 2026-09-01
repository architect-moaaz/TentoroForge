"""Smith composes a screen by calling the agent that already composes them."""
from __future__ import annotations

import pytest

from services.smith.compose import ComposeError, _page_for_route


def _doc():
    return {"pages": [
        {"id": "PAGE-001", "route": "/", "name": "Dashboard",
         "pattern": "dashboard", "primaryTasks": ["See what needs attention"]},
        {"id": "PAGE-010", "route": "/sessions", "name": "Sessions",
         "pattern": "entity_list"},
        {"id": "PAGE-099", "route": "/old", "status": "DEPRECATED"},
    ]}


def test_a_route_is_found_however_a_user_types_it():
    doc = _doc()
    assert _page_for_route(doc, "/sessions")["id"] == "PAGE-010"
    assert _page_for_route(doc, "sessions")["id"] == "PAGE-010"
    # People name the screen as often as the path.
    assert _page_for_route(doc, "Dashboard")["id"] == "PAGE-001"
    assert _page_for_route(doc, "home")["id"] == "PAGE-001"


def test_a_deprecated_page_is_not_a_target():
    assert _page_for_route(_doc(), "/old") is None


def test_an_unknown_route_says_what_the_app_does_have():
    """Refusing without naming the alternatives sends someone guessing."""
    from services.smith.compose import compose_route

    class _Svc:
        doc = _doc()
        output_dir = "/tmp/nope"

    with pytest.raises(ComposeError) as exc:
        compose_route(_Svc(), "/nowhere")
    assert "/sessions" in str(exc.value)


def test_a_composer_that_returns_nothing_is_not_reported_as_success():
    from services.smith.compose import compose_route

    class _Svc:
        doc = _doc()
        output_dir = "/tmp/nope"

    class _Empty:
        proposals: list = []

    with pytest.raises(ComposeError) as exc:
        compose_route(_Svc(), "/sessions", executor=lambda spec: _Empty())
    assert "Nothing has been changed" in str(exc.value)


def test_add_widgets_records_intent_in_the_contract_before_composing():
    """Patching the rendered tree would put the widgets in the app and leave
    the Blueprint describing a page without them — the next composition would
    drop them and nobody would know why."""
    from services.smith.compose import add_widgets

    saved: dict = {}

    class _Svc:
        doc = _doc()
        output_dir = "/tmp/nope"

        def upsert(self, section, body, natural_key=None):
            saved["section"] = section
            saved["body"] = body

        def save(self):
            saved["saved"] = True

    class _Result:
        proposals = ["one"]
        artifacts: list = []

    calls = {}

    def _executor(spec):
        calls["subject"] = spec.subject
        return _Result()

    # apply_change is the commit path; stub it so this stays a unit test.
    import services.smith.change as change_mod
    original = change_mod.apply_change
    change_mod.apply_change = lambda *a, **k: _Result()
    try:
        add_widgets(_Svc(), "/", ["Quorum status", "Recent votes"],
                    executor=_executor)
    finally:
        change_mod.apply_change = original

    assert saved["section"] == "pages"
    assert "Quorum status" in saved["body"]["primaryTasks"]
    assert "Recent votes" in saved["body"]["primaryTasks"]
    # The task the page already had is kept, not replaced.
    assert "See what needs attention" in saved["body"]["primaryTasks"]
    assert calls["subject"] == "PAGE-001"


# ── the change has to reach the application ─────────────────────────────

def test_the_composition_is_regenerated_not_just_committed():
    """`apply_change` runs the §72 sub-DAG only `if run_agents and executor is
    not None`, and this passed none — so the layout was committed, the version
    bumped, the turn reported success, and the frontend was never projected.
    The route stayed blank.

    Committing without regenerating is the divergence §115 refuses, reached by
    omitting an argument.
    """
    import inspect

    from services.smith.compose import compose_route

    src = inspect.getsource(compose_route)
    assert "executor=_traced(run, reasoning)" in src


def test_each_regenerated_node_says_so():
    """The sub-DAG is the last stretch of a compose turn and it was the quiet
    one: composition reported itself, then the panel went still for the part
    that puts the page on disk."""
    from types import SimpleNamespace

    from services.smith.compose import _traced

    said: list[tuple] = []
    run = _traced(lambda _spec: "RESULT",
                  lambda t, kind="reasoning", node="": said.append((kind, node, t)))

    assert run(SimpleNamespace(node="frontend")) == "RESULT"
    assert [k for k, _n, _t in said] == ["step", "step"], "reported as reasoning"
    assert [n for _k, n, _t in said] == ["frontend", "frontend"]


def test_a_run_with_nobody_watching_is_unchanged():
    """Every batch caller passes no sink; the wrapper must be transparent."""
    from types import SimpleNamespace

    from services.smith.compose import _traced

    assert _traced(lambda _s: 7, None)(SimpleNamespace(node="frontend")) == 7


# ── who is credited for the write ───────────────────────────────────────

def test_the_layout_is_committed_under_the_agent_that_authored_it():
    """§30's boundary refused the commit AFTER a 147-second composition had
    already succeeded:

        CapabilityViolation: agent 'smith' may not write 'pageLayouts' (§30).

    The refusal is correct. Smith orchestrated; `a2ui_pages` authored. Widening
    Smith's capability to make the error go away would be the wrong repair — a
    coordinator exempt from the boundary check is §28's uncontrolled swarm with
    a nicer name.
    """
    from services.blueprint.agent_contract import AGENT_REGISTRY
    from services.smith.compose import COMPOSER_AGENT

    writes = set(getattr(AGENT_REGISTRY[COMPOSER_AGENT], "writes", ()) or ())
    assert "pageLayouts" in writes

    smith = set(getattr(AGENT_REGISTRY["smith"], "writes", ()) or ())
    assert "pageLayouts" not in smith, (
        "Smith was given the capability instead of the commit being attributed"
    )


def test_the_agent_that_runs_and_the_agent_credited_are_the_same():
    """Two spellings of one fact is how this error comes back: the TaskSpec
    names who composes, `apply_change` names who wrote, and if they drift the
    boundary check fires again after the expensive part."""
    import inspect

    from services.smith.compose import compose_route

    src = inspect.getsource(compose_route)
    assert 'agent="a2ui_pages"' not in src, "the agent is spelled twice"
    assert src.count("COMPOSER_AGENT") == 2, "spec and commit must share it"


# ── a refused composition is re-asked, not abandoned ────────────────────

def _svc_with_home():
    class _Svc:
        doc = {"pages": [{"id": "PAGE-002", "route": "/", "name": "Home",
                          "pattern": "dashboard"}]}
        output_dir = "/tmp/nope"
    return _Svc()


class _Proposal:
    section = "pageLayouts"


class _Result:
    proposals = [_Proposal()]


def test_a_refused_composition_is_re_asked_with_the_reason(monkeypatch):
    """The DAG catches a rejected apply, records the validator's message as
    the subject's feedback and runs the node again. A conversation reached
    none of that: three and a half minutes of composing were thrown away over
    a `density` on a Card, and the message that would have fixed it went only
    to a log."""
    from services.blueprint.agent_contract import InvalidPatternTemplate
    from services.smith import compose as mod

    seen: list = []
    calls = {"n": 0}

    def _apply(*_a, **_kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise InvalidPatternTemplate(
                "PAGE-002: props.(root): Additional properties are not "
                "allowed ('density' was unexpected)")
        return "COMMITTED"

    monkeypatch.setattr("services.smith.change.apply_change", _apply)

    def _run(spec):
        seen.append(spec.feedback)
        return _Result()

    out = mod.compose_route(_svc_with_home(), "/", executor=_run)
    assert out == "COMMITTED"
    assert calls["n"] == 2, "the refusal ended the turn instead of re-asking"
    # §102 — the second ask is told what the first one got wrong.
    assert seen[0] is None
    assert "density" in (seen[1] or ""), "re-asked without the reason"


def test_it_gives_up_and_says_why(monkeypatch):
    """Bounded like the DAG's. A refusal that survives the retry is reported
    with the validator's own words, not as a bare failure."""
    from services.blueprint.agent_contract import InvalidPatternTemplate
    from services.smith import compose as mod

    def _apply(*_a, **_kw):
        raise InvalidPatternTemplate("PAGE-002: 'items' is a required property")

    monkeypatch.setattr("services.smith.change.apply_change", _apply)

    with pytest.raises(mod.ComposeError) as exc:
        mod.compose_route(_svc_with_home(), "/", executor=lambda _s: _Result())
    assert "'items' is a required property" in str(exc.value)
    assert "nothing has been changed" in str(exc.value)


def test_the_attempt_budget_matches_the_dag():
    """Two paths composing the same page should not disagree about how many
    tries it gets."""
    import inspect

    from services.blueprint import orchestrator
    from services.smith.compose import MAX_ATTEMPTS

    dag_default = inspect.signature(orchestrator.run).parameters["max_attempts"].default
    assert MAX_ATTEMPTS == dag_default
