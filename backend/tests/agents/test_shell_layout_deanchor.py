from agents.shell_layout_agent import SHELL_LAYOUT_SYSTEM_PROMPT as P


def test_prompt_offers_diverse_shells_not_just_sidebar():
    low = P.lower()
    named = sum(k in low for k in ["top-bar", "topbar", "command-bar", "split workspace",
                                   "icon rail", "icon-rail", "sectioned sidebar", "rail"])
    assert named >= 3, "prompt should describe diverse shell structures, not one sidebar pattern"
    assert "do not default" in low or "don't default" in low or "avoid default" in low


def test_prompt_keeps_renderability_rules():
    low = P.lower()
    assert "pageoutlet" in low and "data-shell-region" in low
    assert "375" in P  # responsive floor retained
