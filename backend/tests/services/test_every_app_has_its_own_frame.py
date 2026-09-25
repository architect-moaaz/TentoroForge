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
    AUTH_LAYOUTS, CHROMES, RAIL_PAINT, SHELL_IDENTITY_PATH, TONES, derive_shell, project_shell,
    project_shell_identity,
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
    assert dna["layout"] == {"chrome": "wide-rail", "auth": "side-panel", "tone": "light", "density": "spacious"}
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


# --- the rail's paint is a decision, and the rail is the person's ------------

def test_the_tone_is_stated_or_read_off_the_personality():
    assert derive_shell(_doc(shell={"chrome": "dock", "auth": "brand-wash", "tone": "brand"}))["tone"] == "brand"
    assert derive_shell(_doc(visualPersonality="warm and child-friendly, a warm paper ground"))["tone"] == "tinted"
    assert derive_shell(_doc(visualPersonality="a stark utility"))["tone"] == "light"
    assert derive_shell(_doc(visualPersonality="bold and confident"))["tone"] == "brand"
    assert derive_shell(_doc(informationDensity="compact"))["tone"] == "dark"
    assert derive_shell(_doc(informationDensity="spacious"))["tone"] == "light"
    for tone in TONES:
        assert set(RAIL_PAINT[tone]) == {"mode", "bg", "text", "muted"}
        assert "var(--" in RAIL_PAINT[tone]["bg"], "painted from the app's own tokens"
    schema = json.loads((ROOT / "contracts" / "blueprint.schema.json").read_text())
    assert schema["properties"]["designSystem"]["properties"]["shell"]["properties"]["tone"]["enum"] == list(TONES)
    assert "`shell.tone`" in NODE_TASKS["design_system"]


def test_the_rail_is_painted_in_the_tone_and_says_who_each_destination_is_for(tmp_path):
    doc = {
        "application": {"name": "Clinic"},
        "designSystem": {"colors": {"primary": "#123456"}, "shell": {"chrome": "wide-rail", "auth": "side-panel", "tone": "brand"}},
        "roles": [{"id": "ROLE-1", "name": "Parent"}, {"id": "ROLE-2", "name": "Admin"}],
        "pages": [{"id": "PAGE-1", "route": "/", "users": []},
                  {"id": "PAGE-2", "route": "/my-child", "users": ["ROLE-1"]},
                  {"id": "PAGE-3", "route": "/admin/doctors", "users": ["ROLE-2"], "access": "role_restricted"}],
        "navigation": {"tree": [{"label": "Home", "page": "PAGE-1"},
                                {"label": "Parent", "children": [{"label": "My child", "page": "PAGE-2"}]},
                                {"label": "Admin", "children": [{"label": "Doctors", "page": "PAGE-3"}]}]},
    }
    project_shell(doc, tmp_path)
    props = json.loads((tmp_path / "src/schemas/shell.json").read_text())["children"][0]["props"]
    assert props["mode"] == "dark" and props["bg"] == "hsl(var(--primary))"
    home, parent, admin = props["groups"]
    assert "audience" not in home and "roles" not in home
    assert parent["audience"] == ["Parent"] and "roles" not in parent
    assert admin["audience"] == ["Admin"] and admin["roles"] == ["Admin"]
    # A role's landing page is that role's, even when it names no users.
    doc["navigation"]["initialRoute"] = {"parent": "/", "admin": "/admin/doctors"}
    project_shell(doc, tmp_path)
    props = json.loads((tmp_path / "src/schemas/shell.json").read_text())["children"][0]["props"]
    assert props["groups"][0]["audience"] == ["Parent"]
    # One kind of user: the audience is everyone, so nothing is narrowed.
    doc["roles"] = doc["roles"][:1]
    project_shell(doc, tmp_path)
    props = json.loads((tmp_path / "src/schemas/shell.json").read_text())["children"][0]["props"]
    assert all("audience" not in g for g in props["groups"])


def test_the_layout_scopes_the_rail_and_keeps_its_controls_in_the_frame():
    layout = (ROOT / "templates/app-foundation/src/app/(dashboard)/layout.tsx").read_text()
    assert "forMe(group.audience)" in layout and "forMe(i.audience)" in layout
    assert "ONE HEADING IS NO HEADING" in layout
    # The bell and the account: in the rail's footer or the bar's right end,
    # never floating over the page's own header.
    assert layout.count("footer={cluster}") == 4 and "right={cluster}" in layout
    assert "!clusterInRail && !clusterInBar" in layout
    assert 'data-rail-footer=""' in layout and 'data-rail-caption=""' in layout
    assert '<span className="text-xs opacity-80">Account</span>' not in layout, "the static footer that did nothing"
