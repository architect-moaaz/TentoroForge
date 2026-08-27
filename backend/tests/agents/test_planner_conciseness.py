from agents.planner import PLANNER_SYSTEM_PROMPT as P


def test_planner_prompt_drops_exhaustiveness_mandates():
    low = P.lower()
    # The mandates that drove a huge, slow plan must be gone.
    assert "list every component" not in low
    assert "every reusable component must be listed" not in low
    assert "be especially thorough" not in low


def test_planner_prompt_favors_lean_concise_plan():
    low = P.lower()
    assert "lean" in low
    assert "one-line" in low or "concise" in low
    assert "do not enumerate every component" in low
