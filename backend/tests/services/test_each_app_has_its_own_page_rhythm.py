"""Each application's pages share one rhythm, and it is not every other app's.

The page author was handed one anatomy for every application — eyebrow and
title, a dark leading card, KPI tiles, tables in cards — so two apps with
different palettes still read as one product recoloured. The direction
agent now decides five anatomy choices once per application; the page
prompt renders each with what to do. Since 2026-10-08 each audience has
its own (`composition.looks`, `test_each_audience_has_its_own_look`); a
Blueprint whose direction states none gets the old anatomy — never one read
off the personality's words.
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


def test_without_a_direction_the_rhythm_is_the_default_whatever_the_words():
    assert derive_rhythm(_doc(informationDensity="compact")) == RHYTHM_DEFAULT
    assert derive_rhythm(_doc(visualPersonality="warm and friendly, a consumer app")) == RHYTHM_DEFAULT
    assert derive_rhythm(_doc(visualPersonality="a stark utility")) == RHYTHM_DEFAULT
    assert derive_rhythm(_doc()) == RHYTHM_DEFAULT


def test_every_option_has_an_instruction_and_the_prompt_renders_the_choice():
    for key, opts in RHYTHM_OPTIONS.items():
        for o, what in opts.items():
            assert "`" in what or what, (key, o)
    block = _rhythm(_doc({"rhythm": dict(RHYTHM_DEFAULT, lists="rows")}))
    assert "- lists: `rows` — borderless rows separated by `divide-y`" in block
    prompt = system_prompt(_doc({"rhythm": dict(RHYTHM_DEFAULT, header="band")}))
    assert "# Its page rhythm" in prompt and "- header: `band`" in prompt


def test_the_principles_defer_to_the_rhythm():
    for needle in ("built as the rhythm's `header` says", "rhythm's\n  `lead` says", "rhythm's `figures` says",
                   "rhythm's `lists` says"):
        assert needle in DESIGN_PRINCIPLES, needle
    assert "small eyebrow + title" not in DESIGN_PRINCIPLES


def test_the_direction_agent_must_choose_and_its_choice_is_kept():
    assert "looks" in DIRECTION_SCHEMA["required"] and "rhythm" not in DIRECTION_SCHEMA["properties"]
    look = DIRECTION_SCHEMA["properties"]["looks"]["items"]
    assert look["properties"]["rhythm"]["properties"]["lists"]["enum"] == ["table", "cards", "rows"]
    _, user = direction_prompts(_doc())
    assert "ONE LOOK FOR EACH AUDIENCE" in user and "`gradient-band`" in user
    rhythm = {"header": "compact", "lead": "outlined-panel", "lists": "table", "figures": "strip", "sections": "dense"}
    reply = json.dumps({"vision": "v", "conventions": [], "looks": [
        {"audience": ["ROLE-1"], "experience": "x", "chrome": "wide-rail", "tone": "dark", "rhythm": rhythm, "why": "y"}]})
    body, _ = compose_direction(_doc(), lambda **_: reply)
    assert body["looks"][0]["rhythm"]["figures"] == "strip" and "rhythm" not in body


def test_the_contract_carries_the_rhythm():
    schema = json.loads((ROOT / "contracts" / "blueprint.schema.json").read_text())
    rhythm = schema["properties"]["composition"]["properties"]["rhythm"]["properties"]
    assert set(rhythm) == set(RHYTHM_OPTIONS)
    for key in RHYTHM_OPTIONS:
        assert rhythm[key]["enum"] == list(RHYTHM_OPTIONS[key])
