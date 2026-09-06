"""When a file publishes no variables, its frames still say what the scheme is.

`design_system_from` projected published variables only. Most files publish
none, the extraction recorded the gap, and nothing derived tokens from the
frames — so `designSystem` stayed the agent's generic palette and every surface
painted from it (the sign-in page first) looked unrelated to the design.

Three properties: the frames' fills and faces become tokens under the keys the
CSS projection reads; a published variable still beats a counted one; and a
file with too few fills yields nothing new, which is the behaviour every run
had before.
"""
from services.figma.projection import design_system_from
from services.figma.reference import DesignReference, DesignTokens, ScreenRef
from services.figma.url import FigmaTarget


def _screen(nid, body):
    return ScreenRef(node_id=nid, name="S", canvas="P", width=1440, height=900,
                     structure={"source": "design_context_code", "code": body, "assets": []})


CREAM_AND_GOLD = '''
<div className="bg-[#f7f3eb] flex" data-node-id="1:1">
  <div className="bg-[#110f0c] w-[240px]"><p className="text-[#8a7f78] font-['Inter:Regular']">OVERVIEW</p></div>
  <div className="bg-[#f7f3eb] flex-1">
    <p className="font-['Fraunces:Regular'] text-[#1a1612] text-[28px]">Operations Dashboard</p>
    ''' + "".join(f'<div className="bg-[#c9a84c] rounded"><p className="text-[#1a1612] font-[\'Inter:Regular\']">Card {i}</p></div>' for i in range(8)) + '''
    ''' + "".join(f'<div className="bg-[#f7f3eb] border-[#e6ddcc]"><p className="text-[#1a1612] font-[\'Inter:Regular\']">Row {i}</p><p className="font-[\'JetBrains_Mono:Regular\'] text-[#8a7f78]">£{i}</p></div>' for i in range(8)) + '''
  </div>
</div>
'''


def _ref(code, tokens=None):
    return DesignReference(target=FigmaTarget(file_key="aBcD1234EfGh"), source_id="FIGMA-001",
                           screens=[_screen("1:1", code), _screen("1:2", code)],
                           tokens=tokens or DesignTokens())


def test_the_frames_fills_become_the_tokens():
    ds = design_system_from(_ref(CREAM_AND_GOLD))
    assert ds["derivedFromFigma"] is True
    c = ds["colors"]
    assert c["background"] == "#f7f3eb"
    assert c["primary"] == "#c9a84c" and c["accent"] == "#c9a84c"
    assert c["sidebarBackground"] == "#110f0c"
    assert c["foreground"] == "#1a1612"
    assert c["border"] == "#e6ddcc"


def test_the_frames_faces_become_the_typography():
    t = design_system_from(_ref(CREAM_AND_GOLD))["typography"]
    assert t["fontFamilyBase"] == "Inter"
    assert t["fontFamilyHeading"] == "Fraunces"
    assert t["fontFamilyNumeric"] == "JetBrains Mono"


def test_the_evidence_travels_with_the_verdict():
    """§49 — a count beside each choice, so a reader can disagree."""
    ev = design_system_from(_ref(CREAM_AND_GOLD))["paletteEvidence"]
    assert ev["background"] > ev["sidebarBackground"]
    assert "fontFamilyHeading" in ev


def test_a_published_variable_beats_a_counted_one():
    published = DesignTokens(colors={"primary": "#123456", "background": "#ffffff"})
    ds = design_system_from(_ref(CREAM_AND_GOLD, published))
    assert ds["colors"] == {"primary": "#123456", "background": "#ffffff"}
    # typography was not published, so it may still come from the frames
    assert ds["typography"]["fontFamilyHeading"] == "Fraunces"


def test_a_sketch_yields_nothing_new():
    """Three fills is a screen, not a scheme."""
    ds = design_system_from(_ref('<div className="bg-[#ffffff]"><p className="text-[#000000]">x</p></div>'))
    assert set(ds) == {"derivedFromFigma"}


def test_what_the_frames_state_satisfies_the_contract():
    """The first run that wrote `paletteEvidence` was refused as unexpected —
    the same closed-contract failure `chrome` and `canvas` each hit first.
    Pinned against the generated JSON, which is what the validator reads."""
    import json
    from pathlib import Path
    import jsonschema
    contract = json.load(open(Path(__file__).resolve().parents[2] / "contracts" / "blueprint.schema.json"))
    ds = design_system_from(_ref(CREAM_AND_GOLD))
    v = jsonschema.validators.validator_for(contract)(contract).evolve(
        schema=contract["properties"]["designSystem"])
    errors = list(v.iter_errors(ds))
    assert not errors, [e.message for e in errors][:3]
