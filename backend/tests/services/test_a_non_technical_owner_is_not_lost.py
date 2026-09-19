"""What a non-technical owner met on UAT (jubyt8jk, 18 Sep), each held here.

Long asks answered "I did not follow that"; a label read as a data-model
rename; a bug report answered "nothing has crashed" and nothing else; a plan
whose step split dropped the rest; "composed /" as a whole reply; a review
cut loose with "Still building"; a message that got no reply at all.
"""
from __future__ import annotations

import inspect

from services.smith import plan as plan_mod


def test_a_step_that_splits_keeps_the_rest_of_the_plan(tmp_path):
    plan_mod.remember(tmp_path, ["build the home grid", "show the area", "take the current location"])
    assert plan_mod.take_next(tmp_path) == "build the home grid"
    # the step itself split into three; the two left after it must survive
    rest = plan_mod.peek(tmp_path)
    plan_mod.remember_all(tmp_path, ["add area", "remove latitude", "remove longitude"] + rest)
    assert plan_mod.peek(tmp_path) == ["add area", "remove latitude", "remove longitude",
                                       "show the area", "take the current location"]


def test_the_session_splices_rather_than_replaces_and_keeps_the_plan_in_view():
    from services import smith_session
    src = inspect.getsource(smith_session)
    assert '_in_plan_step' in src and "_plan.remember_all(self.output_dir, planned + over + rest)" in src
    assert "note = _plan_mod.remaining_note(_plan_mod.peek(self.output_dir))" in src


def test_understanding_is_told_what_non_technical_owners_actually_say():
    from services.smith import understand_ask
    src = inspect.getsource(understand_ask)
    for rule in ("EVERY ask, the layout ones too", "WHAT A SCREEN CALLS A THING IS NOT WHAT THE DATA MODEL",
                 "WHAT THE APPLICATION CANNOT DO IS SAID, NOT DROPPED", "WRONG BEHAVIOUR IS NOT A CRASH"):
        assert rule in src, rule


def test_a_reply_names_the_page_and_how_to_reach_it():
    from services.smith.compose import _where

    class Svc:
        doc = {"pages": [{"id": "P1", "route": "/", "name": "Home"}, {"id": "P2", "route": "/tools", "name": "Discover"}],
               "navigation": {"tree": [{"label": "Discover", "page": "P2"}]}}
    assert _where(Svc(), "/tools") == "**Discover** (`/tools`), which the menu calls “Discover”"
    assert _where(Svc(), "/") == "**Home** (`/`) — it is not in the menu; open it at `/`"


def test_every_turn_answers_in_the_conversation():
    from routers import blueprint_generate
    src = inspect.getsource(blueprint_generate)
    assert "A TURN ALWAYS ANSWERS" in src
    assert 'emit("message", {\n                "text": ("Something went wrong on my side' in src
    assert "_turn_timeout = 3600.0 if (req.approved or _reviewing) else 600.0" in src


def test_the_accounts_are_in_smiths_context(tmp_path):
    from services.smith.engine_blueprint_adapter import to_smith_fields
    doc = {"roles": [{"id": "R1", "name": "Member"}],
           "pages": [{"id": "P1", "route": "/login", "pattern": "auth", "auth": "login"},
                     {"id": "P2", "route": "/tools", "users": ["R1"]}],
           "navigation": {"initialRoute": {"default": "/tools"}}, "data": {"entities": []}}
    acc = to_smith_fields(doc)["accounts"]
    assert acc["sign_in_page"] == "/login" and acc["after_sign_in"] == "/tools"
