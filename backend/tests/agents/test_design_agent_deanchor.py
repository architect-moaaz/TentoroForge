from agents.design_agent import DESIGN_AGENT_SYSTEM_PROMPT as P


def test_design_prompt_deanchors_nav_from_sidebar():
    low = P.lower()
    # An explicit anti-default directive must be present (don't auto-pick dark sidebar)
    assert "do not default" in low or "don't default" in low, "needs an anti-default-sidebar nav directive"
    # The old hard anchor that funnelled every data app to a dark sidebar must be gone
    assert "dark sidebar for dashboard-heavy" not in low, "old dashboard->dark-sidebar anchor should be removed"


def test_design_prompt_still_offers_diverse_nav_options():
    low = P.lower()
    assert "sidebar" in low  # sidebar is still a valid choice
    assert "topbar" in low or "top-bar" in low or "command-bar" in low
