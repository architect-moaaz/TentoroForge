"""The native app speaks in the design's own typefaces.

The web loads `Fraunces` and `Inter` from Google Fonts by name; a phone loads font FILES, one per weight.
The Blueprint's heading and base typefaces are mapped to the `@expo-google-fonts/*` package that carries
each, the app's `package.json` gets those packages, and the generated modules say which file is which
weight. A typeface the table does not know is the system font - the app is never blocked on one."""
from __future__ import annotations

import json

from services.blueprint import native_fonts as nf
from services.blueprint.native_projection import native_root, project_native

DOC = {
    "application": {"name": "Field Crew"},
    "mobile": {"native": {"enabled": True}, "store": {"bundleId": "com.acme.fieldcrew"}},
    "designSystem": {"typography": {"fontFamilyBase": "Inter", "fontFamilyHeading": "Fraunces"}},
    "data": {"entities": []}, "workflows": [], "roles": [], "security": {}, "pages": [], "nativeCode": [],
}


def test_the_first_family_of_a_stack_is_the_one():
    assert nf.family_of('"Fraunces", Georgia, serif') == "fraunces"
    assert nf.family_of("Inter") == "inter"
    assert nf.family_of("") is None and nf.family_of(None) is None


def test_the_designs_typefaces_are_found():
    assert nf.design_fonts(DOC) == {"body": "inter", "heading": "fraunces"}
    only_body = {**DOC, "designSystem": {"typography": {"fontFamilyBase": "Inter"}}}
    assert nf.design_fonts(only_body) == {"body": "inter", "heading": "inter"}, "no heading face: the body's"
    unknown = {**DOC, "designSystem": {"typography": {"fontFamilyBase": "Comic Neue", "fontFamilyHeading": "Fraunces"}}}
    assert nf.design_fonts(unknown) == {"heading": "fraunces"}, "a family the table lacks is the system font"
    assert nf.design_fonts({"designSystem": {}}) == {}


def test_each_weight_is_a_file_of_its_own():
    assert nf.font_set("inter") == {"regular": "Inter_400Regular", "medium": "Inter_500Medium",
                                    "semibold": "Inter_600SemiBold", "bold": "Inter_700Bold"}


def test_a_weight_the_face_lacks_is_the_nearest_it_has():
    assert nf.font_set("merriweather") == {"regular": "Merriweather_400Regular", "medium": "Merriweather_400Regular",
                                           "semibold": "Merriweather_700Bold", "bold": "Merriweather_700Bold"}
    assert nf.font_set("roboto")["semibold"] == "Roboto_700Bold"


def test_the_packages_are_the_ones_the_faces_come_from():
    assert nf.packages(DOC) == {"@expo-google-fonts/fraunces": nf.PACKAGE_RANGE, "@expo-google-fonts/inter": nf.PACKAGE_RANGE}
    assert nf.packages({"designSystem": {}}) == {}


def test_the_fonts_module_imports_each_file_once():
    src = nf.fonts_module(DOC)
    assert 'from "@expo-google-fonts/inter"' in src and 'from "@expo-google-fonts/fraunces"' in src
    assert src.count("Inter_700Bold") == 2, "imported, then listed"
    assert nf.fonts_module({"designSystem": {}}).rstrip().endswith("= {};")


def test_the_project_carries_the_packages_the_fonts_and_the_families(tmp_path):
    project_native(DOC, tmp_path)
    root = native_root(tmp_path)
    pkg = json.loads((root / "package.json").read_text("utf-8"))["dependencies"]
    assert "@expo-google-fonts/inter" in pkg and "@expo-google-fonts/fraunces" in pkg and "expo-font" in pkg
    assert "Fraunces_600SemiBold" in (root / "src" / "fonts.generated.ts").read_text("utf-8")
    theme = (root / "src" / "theme.generated.ts").read_text("utf-8")
    assert '"heading"' in theme and '"Fraunces_700Bold"' in theme and '"Inter_400Regular"' in theme


def test_an_app_with_no_known_typeface_ships_none_and_uses_the_system_font(tmp_path):
    project_native({**DOC, "designSystem": {"typography": {"fontFamilyBase": "Comic Neue"}}}, tmp_path)
    root = native_root(tmp_path)
    pkg = json.loads((root / "package.json").read_text("utf-8"))["dependencies"]
    assert not [k for k in pkg if k.startswith("@expo-google-fonts/")]
    assert "export const FONT_FILES: Record<string, number> = {};" in (root / "src" / "fonts.generated.ts").read_text("utf-8")
