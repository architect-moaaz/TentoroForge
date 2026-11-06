"""A drawn control does what the drawing shows it doing, for every person.

DITANS QA (DIT-001…018, 2026-11-05) found the same six faults on screen after
screen, all made by the conversion and every one fixed in that app by hand:
fields drawn with a chevron became selects of the one sample value; chips and
switches drawn in one state stayed in it; a page's content column drawn in a
free frame was cut off at the first screenful; pressable divs were out of the
keyboard's reach; and the designer's example words and choices were every new
form's starting values. Each is fixed where the markup is written.
"""
from __future__ import annotations

import json
import re

from services.drawn import params as P
from services.drawn.components import _typed
from services.drawn.tsx import Emitter

PROFILE = """export default function ProfileView() {
  return (
    <div className="flex flex-col bg-[#ffffff]">
      <div className="flex flex-row h-[46px] border-[1px]" data-layer="Nationality">
        <p className="flex-1 text-[14px]">Egyptian</p>
      </div>
      <div className="flex flex-row h-[46px] border-[1px]" data-layer="Specialty">
        <p className="flex-1 text-[14px]">Nursing</p>
      </div>
      <div className="flex flex-row gap-x-[8px]" data-layer="Gender">
        <div className="px-[12px] bg-[#ffffff]" data-layer="Chip">
          <p className="text-[12px] text-[#1e1e20]">Male</p>
        </div>
        <div className="px-[12px] bg-[#ffffff]" data-layer="Chip">
          <p className="text-[12px] text-[#1e1e20]">Female</p>
        </div>
        <div className="px-[12px] bg-[#0443fa]" data-layer="Chip">
          <p className="text-[12px] text-[#ffffff]">Other</p>
        </div>
      </div>
      <div className="w-[20px] h-[20px] rounded-[4px] bg-[#0443fa]" data-layer="Agree">
        <p className="text-[12px] text-[#ffffff]">✓</p>
      </div>
      <div className="flex flex-row justify-end p-[2px] w-[44px] h-[24px] rounded-full bg-[#0443fa]" data-layer="Alerts">
        <div className="w-[20px] h-[20px] rounded-full bg-[#ffffff]" data-layer="Knob" />
      </div>
      <div className="w-[160px] h-[44px] bg-[#0443fa] rounded-[8px]" data-layer="Save">
        <p className="text-[14px] text-[#ffffff]">Save</p>
      </div>
    </div>
  );
}
"""


def _profile(**changes):
    answer = {"contract": {"data": [{"name": "profile", "kind": "form", "label": "Profile", "fields": [
                  {"name": "nationality", "label": "Nationality", "type": "string"},
                  {"name": "specialty", "label": "Specialty", "type": "enum", "options": ["Nursing", "Medicine"]},
                  {"name": "gender", "label": "Gender", "type": "enum", "options": ["Male", "Female", "Other"]},
                  {"name": "agree", "label": "Agree", "type": "boolean"},
                  {"name": "alerts", "label": "Alerts", "type": "boolean"}]}],
                  "actions": [{"name": "onSave", "label": "Save", "kind": "submit", "on": "profile", "nodes": ["17"]}]},
              "lists": [], "values": [], "shows": [],
              # the model's answer as it came on DITANS: one look given, the same for both states
              "inputs": [{"node": "3", "form": "profile", "field": "nationality", "kind": "select"},
                         {"node": "5", "form": "profile", "field": "specialty", "kind": "select"},
                         {"node": "7", "form": "profile", "field": "gender", "kind": "choice", "value": "Male",
                          "on_look": "7", "off_look": "7"},
                         {"node": "9", "form": "profile", "field": "gender", "kind": "choice", "value": "Female"},
                         {"node": "11", "form": "profile", "field": "gender", "kind": "choice", "value": "Other"},
                         {"node": "13", "form": "profile", "field": "agree", "kind": "toggle", "on": True},
                         {"node": "15", "form": "profile", "field": "alerts", "kind": "toggle", "on": True}]}
    answer.update(changes)
    out, problems = P.apply(PROFILE, json.loads(json.dumps(answer)), "ProfileView")
    assert problems == [], problems
    return out


def _branches(code: str, test: str) -> tuple[str, str]:
    """The chosen and the not-chosen markup of `{test ? (…) : (…)}`."""
    start = code.index("{" + test + " ? (")
    middle = code.index(") : (", start)
    end = re.compile(r"\n\s*\)\}").search(code, middle).start()
    return code[start:middle], code[middle:end]


def test_a_field_drawn_with_a_chevron_offers_what_its_field_declares_and_starts_on_none():
    """DIT-012: nationality offered "Egyptian" and nothing else."""
    code = _profile()["code"]
    # nothing declared: typed into, the drawn words its hint
    assert 'value={props.profile.nationality ?? ""} placeholder={"Egyptian"}' in code
    assert '<option value={"Egyptian"}>' not in code
    # declared: those options, after an empty one
    assert ('<option value="">{"Choose\\u2026"}</option><option value={"Nursing"}>{"Nursing"}</option>'
            '<option value={"Medicine"}>{"Medicine"}</option></select>') in code
    # a shared component's select starts on none too
    assert '<option value="">{props.valueInput.placeholder ?? "Choose\\u2026"}</option>' in _typed("value")


def test_a_chip_shows_its_choice_whatever_looks_the_answer_named():
    """DIT-013 / 30 chip groups: given one look for both states, every chip was drawn the same either way.
    Among the options drawn two ways, the fewer are the chosen look."""
    code = _profile()["code"]
    for gender in ("Male", "Female", "Other"):
        chosen, other = _branches(code, f'props.profile.gender === "{gender}"')
        assert "bg-[#0443fa]" in chosen and "bg-[#0443fa]" not in other, gender
        assert f">{gender}</p>" in chosen and f">{gender}</p>" in other, "each chip keeps its own words"
        assert f'aria-pressed={{props.profile.gender === "{gender}"}}' in chosen


def test_a_switch_or_check_box_drawn_in_one_state_shows_the_other():
    """DIT-004: drawn ticked, the declaration box looked ticked whatever its value."""
    code = _profile()["code"]
    ticked, unticked = _branches(code, "!!props.profile.agree")
    assert "✓" in ticked and "✓" not in unticked, "an unticked box has no tick"
    assert "bg-transparent border-[1.5px] border-[#0443fa]" in unticked, "its fill becomes its outline"
    assert 'role="checkbox" aria-checked={!!props.profile.agree}' in ticked
    on, off = _branches(code, "!!props.profile.alerts")
    assert "justify-end" in on and "bg-[#0443fa]/25" in off and "justify-start" in off, "the knob goes to the start"
    assert 'role="switch"' in on and 'role="switch"' in off


SETTINGS = """export default function SettingsView() {
  return (
    <div className="flex flex-col bg-[#ffffff]">
      <div className="flex flex-row justify-end p-[2px] w-[44px] h-[24px] rounded-full bg-[#2e7d32]" data-layer="Email">
        <div className="w-[20px] h-[20px] rounded-full bg-[#ffffff]" data-layer="Knob" />
      </div>
      <div className="flex flex-row justify-start p-[2px] w-[44px] h-[24px] rounded-full bg-[#d4d8dd]" data-layer="Sms">
        <div className="w-[20px] h-[20px] rounded-full bg-[#ffffff]" data-layer="Knob" />
      </div>
      <div className="w-[20px] h-[20px] rounded-[4px] bg-[#ffffff] border-[1px] border-[#2e7d32]" data-layer="Remember" />
    </div>
  );
}
"""


def test_the_other_state_is_a_twin_drawn_on_the_screen_else_the_drawings_own_colour():
    answer = {"contract": {"data": [{"name": "prefs", "kind": "form", "label": "Preferences", "fields": [
                  {"name": "email", "label": "Email", "type": "boolean"},
                  {"name": "sms", "label": "SMS", "type": "boolean"},
                  {"name": "remember", "label": "Remember", "type": "boolean"}]}], "actions": []},
              "lists": [], "values": [], "shows": [],
              "inputs": [{"node": "2", "form": "prefs", "field": "email", "kind": "toggle", "on": True},
                         {"node": "4", "form": "prefs", "field": "sms", "kind": "toggle", "on": False},
                         {"node": "6", "form": "prefs", "field": "remember", "kind": "toggle", "on": False}]}
    out, problems = P.apply(SETTINGS, answer, "SettingsView")
    assert problems == [], problems
    code = out["code"]
    # each switch's other state is the other switch, as drawn
    for field in ("email", "sms"):
        on, off = _branches(code, f"!!props.prefs.{field}")
        assert "bg-[#2e7d32] cursor-pointer" in on and "justify-end" in on, field
        assert "bg-[#d4d8dd]" in off and "justify-start" in off, field
    # a box drawn empty is filled, ticked, in its outline's colour
    ticked, unticked = _branches(code, "!!props.prefs.remember")
    assert "bg-[#2e7d32]" in ticked and "✓" in ticked
    assert "bg-[#ffffff]" in unticked and "✓" not in unticked


def test_a_pressable_drawing_is_a_button_to_the_keyboard():
    """DIT-015: Tab never reached a drawn action."""
    code = _profile()["code"]
    save = next(line for line in code.splitlines() if 'data-layer="Save"' in line)
    assert 'role="button" tabIndex={0}' in save and 'e.key === "Enter" || e.key === " "' in save
    assert "(e.currentTarget as HTMLElement).click()" in save, "a key does what a press does"
    assert not re.search(r"<(input|select)[^>]*role=", code), "a native control is one already"


def test_a_new_form_starts_empty_and_the_drawing_is_its_hints():
    """DIT-009, DIT-013: a new account opened with the designer's examples as its values."""
    out = _profile()
    assert out["sample"]["profile"] == {"nationality": "", "specialty": "", "gender": "", "agree": False,
                                        "alerts": False}
    assert 'placeholder={"Egyptian"}' in out["code"]


def _frame(nid, x, y, w, h, **more):
    return {"id": nid, "type": "FRAME", "name": nid, "absoluteBoundingBox": {"x": x, "y": y, "width": w, "height": h},
            **more}


def test_the_column_holding_a_free_frames_content_stays_in_the_flow():
    """DIT-003: the documents step's fields and buttons were below the fold and cut off."""
    glow = _frame("1:2", 1040, -220, 520, 520, fills=[{"type": "SOLID", "color": {"r": 0.02, "g": 0.96, "b": 0.89}}])
    content = _frame("1:3", 0, 0, 1440, 1400, layoutMode="VERTICAL", layoutSizingVertical="HUG",
                     layoutSizingHorizontal="FIXED", children=[_frame("1:4", 0, 0, 600, 1400)])
    badge = _frame("1:5", 1200, 0, 120, 40, layoutMode="HORIZONTAL", layoutSizingVertical="FIXED")
    page = _frame("1:1", 0, 0, 1440, 900, children=[glow, content, badge])
    out = Emitter(trace_ids=True).element(page)
    line = next(ln for ln in out.splitlines() if 'data-node="1:3"' in ln)
    assert "relative" in line and "absolute" not in line and "h-[" not in line.split("data-node")[0].split(
        "w-[1440px]")[1], line
    for placed in ("1:2", "1:5"):
        assert "absolute" in next(ln for ln in out.splitlines() if f'data-node="{placed}"' in ln), placed
