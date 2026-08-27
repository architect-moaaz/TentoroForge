"""A design template must (a) clamp to renderable values, (b) expand into a
design_spec, and (c) that spec must compile to real tokens — the "buildable"
guarantee."""
from services import design_compiler
from services.design_templates import (
    guard_template,
    template_to_design_spec,
    seed_design_spec,
    house_templates,
    HOUSE_TEMPLATES,
)


def test_guard_clamps_unbuildable_values():
    dirty = {
        "name": "Wild",
        "palette": {"primary": "not-a-color", "accent": "#ff0000", "mode": "neon"},
        "typography": {"headingFont": "ComicWeb", "bodyFont": "Inter", "scale": "gigantic"},
        "tokens": {"density": "ultra", "radiusScale": "blobby", "elevation": "floaty", "motionLevel": "wild"},
        "shell": {"frame": "carousel", "tone": "rainbow"},
    }
    clean, warn = guard_template(dirty)
    assert clean["palette"]["primary"] == "#3B82F6"      # invalid hex → default
    assert clean["palette"]["mode"] == "light"           # invalid mode → light
    assert clean["typography"]["headingFont"] == "Inter" # non-allowlisted font → Inter
    assert clean["typography"]["scale"] == "balanced"
    assert clean["tokens"]["density"] == "comfortable"
    assert clean["tokens"]["radiusScale"] == "soft"
    assert clean["shell"]["frame"] == "sidebar"
    assert any("primary" in w for w in warn)


def test_template_to_design_spec_shape():
    tpl = HOUSE_TEMPLATES[1]                             # data-console (dark)
    spec = template_to_design_spec(tpl)
    assert spec["colorPalette"]["primary"] == "#14B8A6"
    # The look owns its own ground, so assert it round-trips rather than
    # pinning the shared dark-mode default it used to fall back to — that
    # fallback is now a backfill for sparse templates only.
    assert spec["colorPalette"]["background"] == tpl["palette"]["background"]
    assert spec["layout"]["navigation"] == "topbar-dark"
    assert spec["layout"]["density"] == "compact"
    assert set(spec["borderRadius"]) == {"sm", "md", "lg", "xl", "full"}
    assert spec["typography"]["headingFontFamily"].startswith("IBM Plex Sans")


def test_seed_merges_over_existing_spec():
    existing = {"colorPalette": {"primary": "#000", "brandNote": "keep"},
                "spacing": {"pagePadding": "2rem"}}
    seeded = seed_design_spec(existing, HOUSE_TEMPLATES[0])
    # template overrides the look…
    assert seeded["colorPalette"]["primary"] == "#2563EB"
    # …but preserves unrelated existing keys.
    assert seeded["colorPalette"]["brandNote"] == "keep"
    assert seeded["spacing"]["pagePadding"] == "2rem"


def test_every_house_template_compiles_to_tokens():
    """The buildable guarantee: each preset → design_spec → real tokens, no crash."""
    for t in house_templates(len(HOUSE_TEMPLATES)):
        spec = template_to_design_spec(t)
        tokens = design_compiler.compile(spec)
        assert tokens.get("color", {}).get("primary")       # ramp built
        assert tokens.get("typography", {}).get("font")
        assert tokens.get("radius")


def test_house_templates_count():
    assert len(house_templates(3)) == 3
    assert len(house_templates(99)) == len(HOUSE_TEMPLATES)
