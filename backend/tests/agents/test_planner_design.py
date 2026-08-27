from agents.planner import _sanitize_page_design


def test_sanitize_keeps_renderable_drops_invalid():
    plan = {"pages": [
        {"route": "/t", "type": "list", "archetype": "kanban",
         "features": ["approval", "ghost", "sla-escalation"]},
        {"route": "/x", "type": "detail", "archetype": "made-up"},
    ]}
    out = _sanitize_page_design(plan)
    assert out["pages"][0]["archetype"] == "kanban"
    assert out["pages"][0]["features"] == ["approval"]
    # invalid archetype normalized to the page type
    assert out["pages"][1]["archetype"] == "detail"
    assert out["pages"][1]["features"] == []


def test_sanitize_safe_without_pages():
    assert _sanitize_page_design({}) == {}


def test_planner_prompts_showcase_noncrud_archetypes():
    """Both planner prompt strings must demonstrate non-CRUD archetypes in their
    example pages block so the LLM sees variety rather than anchoring to list/detail/form."""
    from agents.planner import _ONESHOT_SYSTEM_PROMPT, PLANNER_SYSTEM_PROMPT
    for prompt in (_ONESHOT_SYSTEM_PROMPT, PLANNER_SYSTEM_PROMPT):
        for arch in (
            '"archetype": "kanban"',
            '"archetype": "report"',
            '"archetype": "calendar"',
            '"archetype": "inbox"',
        ):
            assert arch in prompt, (
                f"{arch!r} missing from a planner prompt example — "
                "both prompts must showcase non-CRUD archetypes to reduce CRUD anchoring"
            )
