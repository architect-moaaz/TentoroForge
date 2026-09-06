"""`ux_architecture` — the one author of `navigation.tree` — must see the rail.

A connected design's sidebar is identical on every screen, and `store.connect`
records what it says as `designSources[].chrome`. Until this, the agent that
authors navigation could read only `application` and `product`; every Figma
application therefore got the generic sidebar, with the design's own rail
composed inside each page beside it.

Two properties, and the second is the one a bug hid: the addendum appears when
a design carries chrome and is absent otherwise; and building the prompt does
not raise. The first version of this hook sat among the per-agent branches
where `user` was not yet assigned, and raised UnboundLocalError on every call —
inside a run whose whole purpose was to prove the rail could become the shell.
"""
from services.blueprint.executors import build_prompt

BASE = {"application": {"name": "X", "description": "d"}, "requirements": [],
        "pages": [{"id": "PAGE-001", "route": "/", "name": "Home"}],
        "product": {}, "data": {"entities": []}, "modules": [], "roles": []}

CHROME = {"sidebar": {"brand": ["Criterion"], "groups": [
    {"label": "Overview", "items": [{"label": "Dashboard", "navigate": "/"}]},
    {"label": "Cases", "items": [{"label": "New Case"}]}]}, "sharedBy": 15}


def test_a_drawn_rail_reaches_the_navigation_author():
    doc = dict(BASE, designSources=[{"id": "FIGMA-001", "frames": [], "chrome": CHROME}])
    _system, user = build_prompt(doc, "ux_architecture")
    assert "A CONNECTED DESIGN DRAWS THE NAVIGATION" in user
    assert "Overview: Dashboard → /" in user
    assert "REPRODUCE IT" in user


def test_a_design_without_chrome_leaves_the_prompt_alone():
    doc = dict(BASE, designSources=[{"id": "FIGMA-001", "frames": []}])
    _system, user = build_prompt(doc, "ux_architecture")
    assert "A CONNECTED DESIGN DRAWS THE NAVIGATION" not in user


def test_no_design_at_all_leaves_the_prompt_alone():
    _system, user = build_prompt(BASE, "ux_architecture")
    assert "A CONNECTED DESIGN DRAWS THE NAVIGATION" not in user


def test_feedback_still_follows_the_addendum():
    """The addendum sits before the retry feedback, not after the return."""
    doc = dict(BASE, designSources=[{"id": "FIGMA-001", "frames": [], "chrome": CHROME}])
    _system, user = build_prompt(doc, "ux_architecture", feedback="tree was empty")
    assert user.index("REPRODUCE IT") < user.index("tree was empty")
