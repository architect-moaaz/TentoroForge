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


def test_a_new_page_in_a_coded_app_is_declared_put_in_the_menu_and_written_as_code(tmp_path, monkeypatch):
    """UAT: "a home page listing the tools" went to the layout composer for
    seven minutes, the frontend dropped its tree, and Smith said it was done."""
    from services.blueprint.service import BlueprintService
    from services.smith import compose

    svc = BlueprintService.create(output_dir=tmp_path, app_id="a", name="T", domain="d")
    svc.upsert("pages", {"name": "Tools", "route": "/tools", "purpose": "x"}, natural_key="PAGE:/tools")
    tools = svc.doc["pages"][0]["id"]
    svc.doc["pageCode"] = [{"page": tools, "load": "", "view": "x"}]
    svc.doc["navigation"] = {"tree": [{"label": "Discover", "page": tools}], "initialRoute": {"default": "/tools"}}
    svc.save()
    monkeypatch.setattr(compose, "prepare_capabilities", lambda *a, **k: {"declared": [], "created": []})
    calls = []
    monkeypatch.setattr(compose, "recode_page", lambda svc, route, **k: calls.append(route) or
                        {"applied": True, "committed": [], "version": 2, "reason": "", "missing": [], "widgets": []})
    monkeypatch.setattr(compose, "compose_route", lambda *a, **k: calls.append("LAYOUT"))
    out = compose.run(str(tmp_path), "compose_route", route="/", request="a home page listing the tools")
    assert calls == ["/"] and out["applied"]
    doc = BlueprintService.load(output_dir=tmp_path).doc
    home = next(p for p in doc["pages"] if p["route"] == "/")
    assert doc["navigation"]["tree"][0]["page"] == home["id"]
    assert doc["navigation"]["initialRoute"]["default"] == "/"
    assert "the menu calls" in out["diff_summary"]


def test_a_raw_newline_inside_a_proposal_body_is_still_read():
    import json

    from services.blueprint.executors import parse_envelope
    body = '{"name": "Orange\n and charcoal"}'
    raw = json.dumps({"proposals": [{"section": "design.designSystem", "natural_key": "x", "body": body}]})
    result = parse_envelope(raw, task_id="T", agent="a", node="design_system")
    assert result.proposals[0].body["name"] == "Orange\n and charcoal"


def test_a_restyle_that_breaks_answers_in_plain_words(monkeypatch, tmp_path):
    from services.smith import restyle as restyle_mod

    class _Svc:
        doc = {}

    monkeypatch.setattr("services.blueprint.service.BlueprintService.load", classmethod(lambda cls, **kw: _Svc()))
    monkeypatch.setattr(restyle_mod, "restyle", lambda *a, **kw: (_ for _ in ()).throw(ValueError("proposal 0 body")))
    out = restyle_mod.run(str(tmp_path), "orange and charcoal")
    assert not out["applied"] and "ValueError" not in out["reason"] and "nothing in the app was changed" in out["reason"]


def test_a_second_restyle_supersedes_the_first_not_the_original():
    from services.smith.restyle import palette_decision
    doc = {"designSystem": {}, "decisions": [
        {"id": "DEC-002", "decision": "sage and sand", "reason": "the palette asked in discovery", "status": "APPROVED"},
        {"id": "DEC-033", "decision": "darker, moodier", "supersedes": "DEC-002", "status": "APPROVED",
         "reason": "Asked in conversation after the build; the design system's palette and theme were re-decided"},
    ]}
    assert palette_decision(doc)["id"] == "DEC-033"
