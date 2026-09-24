"""Every app gets the frame its design decided — not the one rail.

The scaffold's layout has six navigation chromes and the sign-in page six
compositions, chosen from `design-dna.json`; only the old pipeline wrote it,
so 0 of 70 Blueprint apps had one (2026-09-24) and every app opened on the
identical hover-expand rail and split sign-in. Worse, the layout read
`design-spec.json` FIRST and threw to the fallback when it was missing, so
even a dna file would have been ignored. The design agent now decides
`shell.chrome` and `shell.auth`; the projection writes them where the
layout reads; a Blueprint that states no shell gets one derived from what
it did say.
"""
import json
from pathlib import Path

from services.blueprint.executors import NODE_TASKS
from services.blueprint.projection import (
    AUTH_LAYOUTS, CHROMES, SHELL_IDENTITY_PATH, derive_shell, project_shell_identity,
)

ROOT = Path(__file__).resolve().parents[2]


def _doc(**design):
    pages = [{"id": f"PAGE-{i:03d}", "route": f"/p{i}"} for i in range(1, 9)]
    return {"designSystem": {"colors": {"primary": "#123456"}, **design}, "navigation": {}, "pages": pages}


def test_a_stated_shell_is_used_as_is():
    s = derive_shell(_doc(shell={"chrome": "dock", "auth": "brand-wash"}, navigationApproach="left sidebar"))
    assert (s["chrome"], s["auth"]) == ("dock", "brand-wash")


def test_a_missing_shell_is_derived_from_what_the_design_said():
    assert derive_shell(_doc(navigationApproach="A single persistent top bar"))["chrome"] == "topbar"
    assert derive_shell(_doc(navigationApproach="Mobile-first bottom tab bar"))["chrome"] == "dock"
    assert derive_shell(_doc(navigationApproach="A narrow icon rail"))["chrome"] == "icon-rail"
    assert derive_shell(_doc(navigationApproach="Persistent left sidebar", visualPersonality="warm, editorial"))["chrome"] == "floating-rail"
    assert derive_shell(_doc(navigationApproach="Persistent left sidebar", informationDensity="compact"))["chrome"] == "wide-rail"
    assert derive_shell(_doc(navigationApproach="Persistent left sidebar"))["chrome"] == "standard-rail"


def test_the_sign_in_follows_the_product():
    assert derive_shell(_doc(navigationApproach="bottom tab bar"))["auth"] == "brand-wash"
    assert derive_shell(_doc(visualPersonality="a stark utility"))["auth"] == "centered-minimal"
    assert derive_shell(_doc(informationDensity="compact"))["auth"] == "top-anchored"
    assert derive_shell(_doc(navigationApproach="top bar"))["auth"] == "split-reversed"
    assert derive_shell(_doc())["auth"] == "split-editorial"


def test_every_derived_value_is_one_the_shell_knows():
    for approach in ("top bar", "bottom tab bar", "icon rail", "right rail", "left sidebar", ""):
        for personality in ("warm", "stark tool", "dense operations", ""):
            s = derive_shell(_doc(navigationApproach=approach, visualPersonality=personality))
            assert s["chrome"] in CHROMES and s["auth"] in AUTH_LAYOUTS


def test_the_identity_is_written_where_the_layout_and_the_sign_in_read_it(tmp_path):
    out = project_shell_identity(_doc(shell={"chrome": "wide-rail", "auth": "side-panel"}, informationDensity="spacious"), tmp_path)
    dna = json.loads((tmp_path / SHELL_IDENTITY_PATH).read_text())
    assert dna["layout"] == {"chrome": "wide-rail", "auth": "side-panel", "density": "spacious"}
    assert out["chrome"] == "wide-rail"
    layout = (ROOT / "templates/app-foundation/src/app/(dashboard)/layout.tsx").read_text()
    assert 'dna?.layout?.chrome' in layout and 'dna?.layout?.density' in layout
    # design-spec.json is optional now: its read is wrapped on its own.
    assert "/* no design-spec" in layout
    from services.runtime_injector import _substitute_auth_image
    src = Path(_substitute_auth_image.__code__.co_filename).read_text()
    assert '(dna.get("layout") or {}).get("auth")' in src


def test_the_layout_names_every_chrome_and_the_sign_in_every_composition():
    layout = (ROOT / "templates/app-foundation/src/app/(dashboard)/layout.tsx").read_text()
    for chrome in CHROMES:
        assert f'"{chrome}"' in layout, chrome
    login = (ROOT / "templates/app-foundation/src/app/login/page.tsx").read_text()
    for auth in AUTH_LAYOUTS:            # split-editorial is the switch's default arm
        assert auth in login, auth


def test_the_designer_is_asked_and_the_contract_carries_it():
    task = NODE_TASKS["design_system"]
    assert "`shell.chrome`" in task and "`shell.auth`" in task and "`dock`" in task and "`brand-wash`" in task
    schema = json.loads((ROOT / "contracts" / "blueprint.schema.json").read_text())
    shell = schema["properties"]["designSystem"]["properties"]["shell"]["properties"]
    assert shell["chrome"]["enum"] == list(CHROMES) and shell["auth"]["enum"] == list(AUTH_LAYOUTS)
