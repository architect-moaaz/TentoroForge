"""The understanding can express a build, not only a rename.

`SmithSession.run_iteration` dispatches on `understanding["verb"]` and this is
the function that fills it — on `/api/projects/{id}/smith/chat`, which is the
endpoint the Smith panel actually posts to. The prompt contained no `verb` at
all, so `verbs.verb_of` defaulted every turn to `rename`, `move_dispatcher`
looked for a label nobody had mentioned, and the turn came back "I don't see
anything to change — the current state already matches".

Six times in one conversation, about a screen that rendered nothing.
"""
from __future__ import annotations

import json

from services.smith.understand_ask import _PROMPT, understand_ask
from services.smith.verbs import REQUIRED_BY_VERB, is_known, missing_fields, verb_of


def _ask(reply: dict, message="build the dashboard at /", history=None):
    return understand_ask(message, "PAGE-002 route / dashboard",
                          history=history or [],
                          provider=lambda _p: json.dumps(reply))


def test_the_prompt_offers_every_verb_the_dispatcher_accepts():
    """A verb the prompt never names cannot be chosen; a verb the dispatcher
    does not know is answered as unknown. They have to be the same set."""
    for verb in REQUIRED_BY_VERB:
        if verb == "rebuild":
            continue  # not offered here — it is a command, not an edit
        assert f'"{verb}"' in _PROMPT, f"{verb} is unreachable from the prompt"


def test_a_composition_survives_into_the_understanding():
    u = _ask({"verb": "compose_route", "route": "/"})
    assert verb_of(u) == "compose_route"
    assert is_known(u) and missing_fields(u) == []


def test_widgets_arrive_as_a_list_the_dispatcher_can_use():
    u = _ask({"verb": "add_widgets", "route": "/",
              "widgets": ["Upcoming Sessions", " Quorum Status ", ""]})
    assert u["widgets"] == ["Upcoming Sessions", "Quorum Status"]
    assert missing_fields(u) == []


def test_a_rename_is_unchanged():
    """Every caller predating the verb field must behave exactly as before.

    Not asserted via `missing_fields`: `REQUIRED_BY_VERB["rename"]` describes
    the ReAct tool's five-field shape, and this prompt has only ever produced
    three of them. `run_iteration` gates the gap check to non-rename verbs
    precisely so that mismatch stays harmless — checking it here would fail on
    a path that works.
    """
    u = _ask({"verb": "rename", "target_file": "src/schemas/plants/new.json",
              "element_label": "Add plant", "new_value": "New plant"})
    assert verb_of(u) == "rename"
    assert u["new_value"] == "New plant"
    assert u["target_file"] == "src/schemas/plants/new.json"
    assert u["element_label"] == "Add plant"


def test_the_new_verbs_are_fully_specified_by_this_prompt():
    """Unlike rename, compose_route and add_widgets ARE gated on their fields
    in `run_iteration` — so the prompt must be able to produce all of them."""
    assert missing_fields(_ask({"verb": "compose_route", "route": "/"})) == []
    assert missing_fields(_ask({"verb": "add_widgets", "route": "/",
                                "widgets": ["Quorum Status"]})) == []


def test_an_absent_verb_still_means_rename():
    """The field is new; a model that omits it must not fall into an
    unknown-verb branch it has never seen."""
    u = _ask({"target_file": "p.json", "element_label": "Save",
              "new_value": "Submit"})
    assert verb_of(u) == "rename" and is_known(u)


def test_every_degraded_path_carries_the_new_keys():
    """`run_iteration` reads `route` and `widgets` off this dict. A shape that
    omits them on the error paths would KeyError the turn that is already
    going badly."""
    blank = understand_ask("", "ctx")
    unreachable = understand_ask("x", "ctx",
                                 provider=lambda _p: (_ for _ in ()).throw(RuntimeError()))
    unparseable = understand_ask("x", "ctx", provider=lambda _p: "not json")
    for shape in (blank, unreachable, unparseable):
        assert {"verb", "route", "widgets"} <= set(shape)
        assert shape["widgets"] == []
