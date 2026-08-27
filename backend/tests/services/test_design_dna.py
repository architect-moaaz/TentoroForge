"""design_dna — the per-app design identity generator.

Locks the properties that make generated apps LOOK DIFFERENT while staying
premium: determinism, cross-domain distinctness, same-domain variety,
WCAG contrast floors, CSS validity of every emitted value, and Google-Fonts
membership of every family.
"""
import re

from services.design_dna import (
    ARCHETYPES, FONT_PAIRINGS, contrast_ratio, derive_design_dna,
    google_fonts_import, match_archetype, prompt_brief, to_css_variables,
    to_design_spec,
)

HEX = re.compile(r"^#[0-9a-f]{6}$")
LEN = re.compile(r"^(-?\d*\.?\d+(rem|em|px|%)|0|9999px)$")
TRIPLET = re.compile(r"^\d{1,3} \d{1,3}% \d{1,3}%$")

CASES = [
    ("p-cat", "petcare", "cat feeding management"),
    ("p-fin", "fintech", "expense tracking and invoicing"),
    ("p-law", "legal", "contract review for law firms"),
    ("p-dev", "developer tools", "API monitoring and logs"),
    ("p-hot", "hospitality", "boutique hotel booking"),
    ("p-med", "healthcare", "patient appointment scheduling"),
    ("p-gen", None, "a simple task tracker"),
]


def _dna(pid="p1", dom="petcare", ctx="cat app"):
    return derive_design_dna(project_id=pid, domain=dom, context=ctx)


class TestArchetypeMatching:
    def test_domain_keywords_route_correctly(self):
        assert match_archetype("petcare", "cat feeding") == "consumer-warm"
        assert match_archetype("fintech", "invoices") == "fintech"
        assert match_archetype("legal", "contracts") == "legal"
        assert match_archetype(None, "API monitoring and deploy logs") == "developer"
        assert match_archetype(None, "something entirely novel") == "default-saas"

    def test_every_archetype_is_complete(self):
        for name, arch in ARCHETYPES.items():
            assert arch["hues"], name
            assert arch["pairings"], name
            for p in arch["pairings"]:
                assert p in FONT_PAIRINGS, f"{name} references unknown pairing {p}"
            assert arch["radius"] and arch["elevation"] and arch["density"], name
            assert arch["rail"], name
            assert arch["principles"], name


class TestDeterminismAndVariety:
    def test_same_inputs_same_dna(self):
        assert _dna() == _dna()

    def test_cross_domain_distinctness(self):
        """Different domains must produce recognizably different identities."""
        seen = set()
        for pid, dom, ctx in CASES:
            d = derive_design_dna(project_id=pid, domain=dom, context=ctx)
            key = (d["typography"]["pairing"], d["color"]["primary"],
                   d["shape"]["radiusScale"], d["shell"]["rail"])
            assert key not in seen, f"duplicate identity for {dom}: {key}"
            seen.add(key)

    def test_same_domain_projects_differ(self):
        """Six petcare apps must not share one look."""
        prims = {_dna(pid=f"p{i}")["color"]["primary"] for i in range(6)}
        assert len(prims) >= 4, f"too little same-domain variety: {prims}"


class TestQualityFloors:
    def test_primary_button_label_contrast(self):
        """The FILLED control's label must read — white on dark-enough
        primaries (light mode), and on dark-mode apps (bright primaries)
        whichever label to_css_variables actually picks must clear the bar."""
        from services.design_dna import _fg_for
        for pid, dom, ctx in CASES:
            d = derive_design_dna(project_id=pid, domain=dom, context=ctx)
            primary = d["color"]["primary"]
            if d["mode"] == "dark":
                # Bright-on-dark primary: canvas contrast is the floor…
                assert contrast_ratio(primary, d["color"]["background"]) >= 4.2, (
                    dom, primary, d["color"]["background"])
                # …and the picked label (white OR ink) must read on the fill.
                label = "#ffffff" if _fg_for(primary) == "0 0% 100%" else "#0d1117"
                assert contrast_ratio(label, primary) >= 3.5, (dom, primary, label)
            else:
                assert contrast_ratio("#ffffff", primary) >= 3.9, (
                    dom, primary, contrast_ratio("#ffffff", primary))

    def test_ink_on_background_contrast(self):
        for pid, dom, ctx in CASES:
            d = derive_design_dna(project_id=pid, domain=dom, context=ctx)
            ratio = contrast_ratio(d["color"]["textPrimary"], d["color"]["background"])
            assert ratio >= 7.0, (dom, ratio)

    def test_rail_text_contrast(self):
        for pid, dom, ctx in CASES:
            d = derive_design_dna(project_id=pid, domain=dom, context=ctx)
            ratio = contrast_ratio(d["color"]["sidebarText"], d["color"]["sidebarBg"])
            assert ratio >= 4.0, (dom, d["shell"]["rail"], ratio)

    def test_all_colors_are_clean_hex(self):
        for pid, dom, ctx in CASES:
            d = derive_design_dna(project_id=pid, domain=dom, context=ctx)
            for k, v in d["color"].items():
                if k == "neutralTemperature":
                    continue
                assert HEX.match(v), (dom, k, v)


class TestSpecEmission:
    def test_design_spec_is_machine_valid(self):
        for pid, dom, ctx in CASES:
            spec = to_design_spec(derive_design_dna(project_id=pid, domain=dom, context=ctx))
            for k, v in spec["colorPalette"].items():
                assert HEX.match(v), (dom, k, v)
            for k, v in spec["borderRadius"].items():
                if k != "scale":
                    assert LEN.match(v), (dom, k, v)
            for k, v in spec["typography"]["scale"].items():
                assert LEN.match(v), (dom, k, v)
            assert spec["radiusScale"] in ("sharp", "soft", "round")
            assert spec["elevation"] in ("flat", "bordered", "layered", "floating")
            assert spec["motionLevel"] in ("none", "subtle", "expressive")
            assert spec["layout"]["density"] in ("compact", "comfortable", "spacious")

    def test_spec_compiles_to_valid_tokens(self):
        """DNA spec → design_compiler → every token value CSS-valid."""
        from services.design_compiler import compile as compile_tokens
        for pid, dom, ctx in CASES:
            dna = derive_design_dna(project_id=pid, domain=dom, context=ctx)
            toks = compile_tokens(to_design_spec(dna))
            assert toks["radius"]["scale"] == dna["shape"]["radiusScale"]
            assert toks["density"] == dna["rhythm"]["density"]
            assert toks["elevation"] == dna["shape"]["elevation"]
            for k, v in toks["typography"]["scale"].items():
                assert LEN.match(v), (dom, k, v)

    def test_css_variables_are_hsl_triplets(self):
        css = to_css_variables(_dna())
        for name, val in css.items():
            if name == "--radius":
                assert LEN.match(val), (name, val)
            elif name.startswith("--"):
                assert TRIPLET.match(val), (name, val)

    def test_google_fonts_import_shape(self):
        for pid, dom, ctx in CASES:
            imp = google_fonts_import(derive_design_dna(project_id=pid, domain=dom, context=ctx))
            assert imp.startswith("@import url('https://fonts.googleapis.com/css2?family=")
            assert imp.endswith("&display=swap');")

    def test_frame_and_icon_stroke_emitted(self):
        for pid, dom, ctx in CASES:
            dna = derive_design_dna(project_id=pid, domain=dom, context=ctx)
            spec = to_design_spec(dna)
            assert spec["layout"]["navigation"] in ("sidebar", "topbar")
            assert spec["layout"]["navigation"] == dna["shell"]["frame"]
            assert 1.0 <= spec["iconStroke"] <= 3.0

    def test_topbar_frame_reachable_for_eligible_archetypes(self):
        frames = {derive_design_dna(project_id=f"p{i}", domain="creative agency",
                                    context="brand studio")["shell"]["frame"]
                  for i in range(10)}
        assert "topbar" in frames  # structure varies, not just paint

    def test_prompt_brief_carries_the_identity(self):
        d = _dna()
        brief = prompt_brief(d)
        assert d["color"]["primary"] in brief
        assert d["archetype"] in brief
        assert "NO prose" in brief


class TestFontBank:
    def test_all_pairings_complete(self):
        for name, p in FONT_PAIRINGS.items():
            assert p["heading"] and p["body"], name
            assert p["import"], name
            assert p["headingWeight"].isdigit(), name
            for imp in p["import"]:
                # css2 families param shape: Family+Name:wght@400;600 or opsz,wght@…
                assert re.match(r"^[A-Za-z0-9+]+:(?:ital,)?(?:opsz,)?wght@[0-9.,;]+$", imp), (name, imp)


class TestCompositionEngine:
    """The layer that makes apps different PRODUCTS, not repaints."""

    WORKOUT = {"visualLanguage": {
        "paletteCharacter": "dark charcoal backgrounds with electric neon-green accents",
        "typographyTone": "technical", "densityPreference": "compact"}}
    LEGAL = {"visualLanguage": {
        "paletteCharacter": "neutral", "typographyTone": "corporate",
        "densityPreference": "comfortable"}}

    def test_dossier_drives_dark_mode(self):
        d = derive_design_dna(project_id="w1", domain="Fitness & Workout Tracking",
                              context="log sets reps", dossier=self.WORKOUT)
        assert d["mode"] == "dark"
        # dark canvas + light ink, not the reverse
        assert contrast_ratio(d["color"]["textPrimary"], d["color"]["background"]) >= 7.0
        assert contrast_ratio(d["color"]["primary"], d["color"]["background"]) >= 4.5

    def test_dossier_neon_hue_reaches_the_palette(self):
        d = derive_design_dna(project_id="w1", domain="fitness", context="gym",
                              dossier=self.WORKOUT)
        from services.design_dna import _hex_to_hsl
        hue, _, _ = _hex_to_hsl(d["color"]["primary"])
        assert 70 <= hue <= 175, f"expected a green/lime hue, got {hue}"

    def test_two_domains_differ_in_composition_not_just_color(self):
        a = derive_design_dna(project_id="w1", domain="Fitness & Workout Tracking",
                              context="workout", dossier=self.WORKOUT)
        b = derive_design_dna(project_id="l1", domain="Legal Technology",
                              context="contracts", dossier=self.LEGAL)
        assert a["mode"] != b["mode"]
        assert a["layout"]["auth"] != b["layout"]["auth"]
        assert a["layout"]["dashboard"] != b["layout"]["dashboard"]
        assert a["archetype"] == "fitness" and b["archetype"] == "legal"

    def test_every_archetype_has_a_layout_recipe(self):
        from services.design_dna import ARCHETYPES, LAYOUT_RECIPES
        for name in ARCHETYPES:
            assert name in LAYOUT_RECIPES, f"{name} has no composition recipe"

    def test_layout_values_are_from_the_known_vocabulary(self):
        from services.design_dna import (AUTH_LAYOUTS, DASHBOARD_LAYOUTS,
                                         LIST_LAYOUTS, DETAIL_LAYOUTS, SHELL_CHROME)
        for i, (dom, ctx) in enumerate([("fintech", "invoices"), ("fitness", "gym"),
                                        ("legal", "contracts"), ("creative", "studio"),
                                        ("healthcare", "patients"), (None, "tasks")]):
            L = derive_design_dna(project_id=f"p{i}", domain=dom, context=ctx)["layout"]
            assert L["auth"] in AUTH_LAYOUTS
            assert L["dashboard"] in DASHBOARD_LAYOUTS
            assert L["list"] in LIST_LAYOUTS
            assert L["detail"] in DETAIL_LAYOUTS
            assert L["chrome"] in SHELL_CHROME

    def test_composition_variety_across_many_projects(self):
        """Across 40 projects we must see genuine structural spread."""
        auths, dashes, modes = set(), set(), set()
        domains = ["fintech", "fitness", "legal", "creative", "healthcare",
                   "commerce", "developer tools", "hospitality", None]
        for i in range(40):
            d = derive_design_dna(project_id=f"proj{i}", domain=domains[i % len(domains)],
                                  context="an app")
            auths.add(d["layout"]["auth"]); dashes.add(d["layout"]["dashboard"])
            modes.add(d["mode"])
        assert len(auths) >= 4, f"only {len(auths)} auth layouts seen"
        assert len(dashes) >= 4, f"only {len(dashes)} dashboard layouts seen"
        assert modes == {"light", "dark"}, "both canvases must occur"

    def test_determinism_holds_with_dossier(self):
        a = derive_design_dna(project_id="x", domain="fitness", context="gym", dossier=self.WORKOUT)
        b = derive_design_dna(project_id="x", domain="fitness", context="gym", dossier=self.WORKOUT)
        assert a == b
