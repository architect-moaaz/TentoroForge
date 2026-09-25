"""Each application's pages share one rhythm, and it is not every other app's.

The page author was handed one anatomy for every application — eyebrow and
title, a dark leading card, KPI tiles, tables in cards — so two apps with
different palettes still read as one product recoloured. The direction
agent now decides five anatomy choices once per application; the page
prompt renders each with what to do; a Blueprint whose direction states
none gets a rhythm read off its density and personality, and only a
Blueprint that says nothing at all gets the old anatomy.
"""
import json
from pathlib import Path

from services.blueprint.ui_engineer import (
    DESIGN_PRINCIPLES, DIRECTION_SCHEMA, RHYTHM_DEFAULT, RHYTHM_OPTIONS, _rhythm, compose_direction,
    derive_rhythm, direction_prompts, system_prompt,
)

ROOT = Path(__file__).resolve().parents[2]


def _doc(comp=None, **design):
    return {"application": {"name": "App", "domain": "ops"}, "designSystem": {"colors": {"primary": "#123456"}, **design},
            "composition": comp or {}, "pages": [], "roles": [], "data": {"entities": []}, "workflows": []}


def test_a_stated_rhythm_wins_and_a_bad_value_is_ignored():
    r = derive_rhythm(_doc({"rhythm": {"header": "band", "lead": "type-only", "lists": "rows", "figures": "strip",
                                        "sections": "open"}}))
    assert r == {"header": "band", "lead": "type-only", "lists": "rows", "figures": "strip", "sections": "open"}
    r = derive_rhythm(_doc({"rhythm": {"header": "marquee"}}))
    assert r["header"] == RHYTHM_DEFAULT["header"]


def test_without_a_direction_the_design_still_sets_a_rhythm():
    assert derive_rhythm(_doc(informationDensity="compact"))["header"] == "compact"
    assert derive_rhythm(_doc(visualPersonality="warm and friendly"))["lists"] == "cards"
    assert derive_rhythm(_doc(visualPersonality="a stark utility"))["lead"] == "type-only"
    assert derive_rhythm(_doc()) == RHYTHM_DEFAULT


def test_every_option_has_an_instruction_and_the_prompt_renders_the_choice():
    for key, opts in RHYTHM_OPTIONS.items():
        for o, what in opts.items():
            assert "`" in what or what, (key, o)
    block = _rhythm(_doc({"rhythm": dict(RHYTHM_DEFAULT, lists="rows")}))
    assert "- lists: `rows` — borderless rows separated by `divide-y`" in block
    prompt = system_prompt(_doc(visualPersonality="warm"))
    assert "# Its page rhythm" in prompt and "- header: `band`" in prompt


def test_the_principles_defer_to_the_rhythm():
    for needle in ("built as the rhythm's `header` says", "rhythm's\n  `lead` says", "rhythm's `figures` says",
                   "rhythm's `lists` says"):
        assert needle in DESIGN_PRINCIPLES, needle
    assert "small eyebrow + title" not in DESIGN_PRINCIPLES


def test_the_direction_agent_must_choose_and_its_choice_is_kept():
    assert "rhythm" in DIRECTION_SCHEMA["required"]
    assert DIRECTION_SCHEMA["properties"]["rhythm"]["properties"]["lists"]["enum"] == ["table", "cards", "rows"]
    _, user = direction_prompts(_doc())
    assert "AND THE PAGE RHYTHM" in user and "`gradient-band`" in user
    reply = json.dumps({"vision": "v", "conventions": [], "rhythm": {"header": "compact", "lead": "outlined-panel",
                                                                     "lists": "table", "figures": "strip", "sections": "dense"}})
    body, _ = compose_direction(_doc(), lambda **_: reply)
    assert body["rhythm"]["figures"] == "strip"
    half = json.dumps({"vision": "v", "conventions": [], "rhythm": {"header": "compact"}})
    assert "rhythm" not in compose_direction(_doc(), lambda **_: half)[0]


def test_the_contract_carries_the_rhythm():
    schema = json.loads((ROOT / "contracts" / "blueprint.schema.json").read_text())
    rhythm = schema["properties"]["composition"]["properties"]["rhythm"]["properties"]
    assert set(rhythm) == set(RHYTHM_OPTIONS)
    for key in RHYTHM_OPTIONS:
        assert rhythm[key]["enum"] == list(RHYTHM_OPTIONS[key])
