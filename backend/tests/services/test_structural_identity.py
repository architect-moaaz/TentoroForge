"""Structural-identity round 4 — the post-audit fixes that closed the
"only the color changed" gap. Pins:

  * detail pages consume spec.layout.detail (4 shapes + legacy)
  * form pages consume spec.layout.form (4 shapes + legacy)
  * timeline lists render as a date-anchored Repeat feed
  * list tables drop the raw Id column and carry per-entity emptyText
  * voice microcopy varies the create-button verb
  * DNA emits brand name / authCopy / form layout / voice, all deterministic
  * nav grouping: detail pages demoted, " List" suffix stripped, long flat
    menus clustered into labeled families
  * dark-mode primaries get an ink (not white) button label
"""

import json
import re

from services.deterministic_pages import (
    build_detail_page, build_form_page, build_list_page,
)
from services.design_dna import derive_design_dna, match_archetype, _fg_for
from services.shell_templates import build_sidenav_groups

COLS = {
    "id": {"type": "uuid"},
    "title": {"type": "string"},
    "status": {"type": "enum", "values": ["open", "done"]},
    "notes": {"type": "text"},
    "amount": {"type": "number"},
    "owner": {"type": "string"},
    "created_at": {"type": "datetime"},
}


# ── detail compositions ────────────────────────────────────────────────────

def _detail_tops(comp):
    spec = {"layout": {"detail": comp}} if comp else None
    d = build_detail_page("Task", COLS, "/tasks/[id]", spec)
    return [c["type"] for c in d["root"]["children"]]


def test_detail_layouts_are_structurally_distinct():
    shapes = {comp: tuple(_detail_tops(comp))
              for comp in ("split-detail", "profile-detail", "timeline-detail",
                           "tabbed-hero", None)}
    assert shapes["split-detail"][1] == "Split"
    assert shapes["profile-detail"][1:] == ("Card", "Card")
    assert shapes["timeline-detail"][1] == "Grid"
    assert shapes[None] == ("Row", "Card")  # legacy byte-stable
    # At least 4 distinct silhouettes across the vocabulary.
    assert len(set(shapes.values())) >= 4


def test_profile_detail_uses_avatar_band():
    d = build_detail_page("Task", COLS, "/tasks/[id]",
                          {"layout": {"detail": "profile-detail"}})
    s = json.dumps(d)
    assert '"Avatar"' in s and '"Badge"' in s


# ── form compositions ──────────────────────────────────────────────────────

def _form(comp):
    spec = {"layout": {"form": comp}} if comp else None
    return json.dumps(build_form_page("Task", COLS, "/tasks/new", spec))


def test_form_layouts_differ():
    assert '"Grid"' not in _form("single-column")
    assert '"Grid"' in _form("two-column")
    assert "Basics" in _form("sectioned") and "More detail" in _form("sectioned")
    assert '"Split"' in _form("side-summary")
    # Legacy (no DNA) keeps the historical auto behaviour.
    legacy = _form(None)
    assert "Basics" not in legacy


# ── list voice + de-slop ───────────────────────────────────────────────────

def test_list_table_drops_id_and_carries_empty_text():
    p = build_list_page("Task", COLS, "/tasks", None)
    t = next(c for c in p["root"]["children"] if c["type"] == "Table")
    keys = [c["key"] for c in t["props"]["columns"]]
    assert "id" not in keys
    assert t["props"]["emptyText"].startswith("No task")


def test_voice_changes_create_verb():
    spec = {"voice": {"create": "Add", "view": "Open"}}
    p = build_list_page("Task", COLS, "/tasks", spec)
    assert '"Add Task"' in json.dumps(p)


def test_timeline_list_is_a_repeat_feed():
    p = build_list_page("Task", COLS, "/tasks", {"layout": {"list": "timeline"}})
    s = json.dumps(p)
    assert '"Repeat"' in s and '"Table"' not in s


# ── DNA identity axes ──────────────────────────────────────────────────────

def test_dna_emits_brand_authcopy_voice_form():
    d = derive_design_dna(project_id="p1", domain="law firm", context="matters")
    assert d["brand"]["name"] and d["brand"]["name"][0].isupper()
    assert d["authCopy"]["title"]
    assert d["voice"]["create"] in ("New", "Add", "Create")
    assert d["layout"]["form"] in ("single-column", "two-column",
                                   "sectioned", "side-summary")
    # deterministic
    assert derive_design_dna(project_id="p1", domain="law firm",
                             context="matters") == d


def test_same_domain_brands_differ():
    names = {derive_design_dna(project_id=f"p{i}", domain="law firm")["brand"]["name"]
             for i in range(8)}
    assert len(names) >= 5, names


def test_archetype_matcher_rejects_midword_substrings():
    """Keywords anchor to a word START (not a bare substring).

    Bare substring scoring mis-binned "blog"/"catalog" as developer via the
    keyword "log". Full word-boundary matching over-corrected: "healthcare"
    stopped matching "health", so a doctor-appointment app fell through to
    default-saas — caught on a real generation.
    """
    # mid-word substrings must NOT match
    assert match_archetype("blog platform", "threaded comments") != "developer"
    assert match_archetype("chrome extension", "browser tooling") != "hr-people"
    # …while compounds and plurals that START with the keyword still do
    assert match_archetype("healthcare", "") == "healthcare"
    assert match_archetype("doctor appointment portal", "") == "healthcare"
    assert match_archetype("logistics", "fleet dispatch") == "logistics"


def test_generic_page_words_lose_to_subject_words_for_icons():
    """Role-prefixed dashboards must not collapse to one glyph — four
    identical `home` icons in an icon-only rail is unusable (seen live)."""
    from services.shell_templates import _icon_for
    icons = {_icon_for(lbl) for lbl in
             ("Patient Dashboard", "Doctor Dashboard", "Staff Dashboard")}
    assert len(icons) == 3, icons
    assert _icon_for("Dashboard") == "home"        # bare dashboard keeps home
    assert _icon_for("Dashboard") != _icon_for("Patient Dashboard")


def test_dark_primary_gets_ink_label():
    # A neon-lime fill cannot carry a white label.
    assert _fg_for("#66f91f") != "0 0% 100%"
    assert _fg_for("#1d4ed8") == "0 0% 100%"


# ── nav IA ─────────────────────────────────────────────────────────────────

def _nav(pages):
    nf = {"pages": [{"title": t, "route": r, "shell": True} for t, r in pages]}
    return build_sidenav_groups(nf, None)


def test_nav_demotes_detail_pages_and_strips_list_suffix():
    groups = _nav([("Dashboard", "/dashboard"), ("MattersListPage", "/matters"),
                   ("ContractDetailPage", "/contract-detail"),
                   ("SettingsPage", "/settings")])
    labels = json.dumps(groups)
    assert "Contract" not in labels          # detail page demoted
    assert '"Matters"' in labels             # " List" stripped
    assert "Matters List" not in labels


def test_nav_clusters_long_flat_menus():
    pages = [("Dashboard", "/dashboard")] + [
        (t, f"/{t.lower()}") for t in
        ("Invoices", "Payments", "Expenses", "Clients", "Employees",
         "Documents", "Templates", "Settings", "Notifications")]
    groups = _nav(pages)
    sections = [g["label"] for g in groups if g.get("items")]
    assert sections, "long flat menu should cluster into labeled families"
    # Dashboard stays first and flat.
    assert groups[0].get("route") == "/dashboard"


# ── Component skins (the design-language axis) ─────────────────────────────

def test_composed_language_is_seeded_deterministic_and_register_backed():
    """Every app composes its own language; same project = same language."""
    from services.design_dna import derive_design_dna
    d1 = derive_design_dna(project_id="s1", domain="law firm")
    d2 = derive_design_dna(project_id="s1", domain="law firm")
    assert d1["language"]["signature"] == d2["language"]["signature"]
    assert d1["skin"] == d2["skin"] and d1["skin"].startswith("lang")
    # the register (component DOM variant set) must follow the card treatment
    assert d1["register"] in ("default", "workday", "linear", "notion",
                              "figma", "stripe")
    # the shell chrome must follow the composed nav shape
    assert d1["layout"]["chrome"] == d1["language"]["chrome"]


def test_composer_spreads_across_many_apps():
    """The whole point: 60 apps must not collapse onto a few looks."""
    from services.design_dna import derive_design_dna
    doms = ["law firm", "workout gym", "freight fleet", "clinic", "pet matching",
            "fintech invoices", "developer api", "online store", "hotel booking",
            "school courses", "factory plant", "hr onboarding"]
    sigs = {derive_design_dna(project_id=f"c{i}", domain=doms[i % len(doms)])
            ["language"]["signature"] for i in range(60)}
    assert len(sigs) >= 50, f"only {len(sigs)}/60 distinct languages"


def test_composed_languages_obey_the_taste_model():
    """No forbidden pair, at most one loud move, structurally legal marks."""
    from services.design_dna import derive_design_dna
    from services.design_language import (
        _pair_ok, _mark_allowed, _header_allowed, _loud_count)
    for i in range(80):
        lang = derive_design_dna(project_id=f"t{i}", domain="ops tool")["language"]
        assert _pair_ok(lang["cardTreatment"], lang["radiusRegime"])
        assert _pair_ok(lang["typeClass"], lang["kpiAnatomy"])
        assert _mark_allowed(lang["navShape"], lang["activeMark"])
        assert _header_allowed(lang["navShape"], lang["headerStyle"])
        assert _loud_count(lang) <= 1


def test_component_css_marker_wrapped_and_engine_scoped():
    from services.design_dna import derive_design_dna, to_component_css, SKINS
    for skin in SKINS:
        d = derive_design_dna(project_id=f"x-{skin}", domain="ops tool")
        d["skin"] = skin
        css = to_component_css(d)
        assert css.startswith("/* tentoro:skin */")
        assert css.endswith("/* /tentoro:skin */")
        # every skin rule is scoped under the layout's data-skin stamp
        assert f'[data-skin="{skin}"]' in css
        # icon-tolerant selectors only (icon <span> may precede the label <p>)
        assert "p:first-child" not in css and "p:nth-child(2)" not in css


def test_same_domain_apps_can_draw_different_skins():
    from services.design_dna import derive_design_dna
    skins = {derive_design_dna(project_id=f"p{i}", domain="law firm")["skin"]
             for i in range(10)}
    assert len(skins) >= 2, skins


def test_spec_forwards_register_for_engine_variant_swap():
    from services.design_dna import derive_design_dna, to_design_spec
    d = derive_design_dna(project_id="s2", domain="workout gym")
    spec = to_design_spec(d)
    assert spec["register"] == d["register"]
    assert spec["skin"] == d["skin"]


def test_nav_css_patterns_differ_per_skin():
    from services.design_dna import derive_design_dna, to_nav_css, SKINS, nav_style_for
    styles = {nav_style_for(s) for s in SKINS}
    assert len(styles) == len(SKINS), "every skin needs its own nav grammar"
    d = derive_design_dna(project_id="n1", domain="law firm")
    d.pop("language", None)          # exercise the named-preset path
    d["skin"] = "broadsheet"
    css = to_nav_css(d)
    assert css.startswith("/* tentoro:nav */") and css.endswith("/* /tentoro:nav */")
    assert "counter(navidx" in css                      # numbered index
    d["skin"] = "manuscript"
    assert "display: none" in to_nav_css(d)             # outline hides icons
    d["skin"] = "gridwork"
    assert "uppercase" in to_nav_css(d)                 # compartment cells


def test_skins_own_the_silhouette_levers():
    """The regression that made every app look alike: KPI column count, nav
    width, gutter, card gap and radius all lived on the ARCHETYPE axis, so
    skins could only ever repaint. They must live on the SKIN."""
    from services.design_dna import SKINS
    required = ("navWidth", "gutter", "cardGap", "kpiTemplate", "chartTemplate",
                "radius", "cardBorder", "nav", "kpi")
    for name, s in SKINS.items():
        for k in required:
            assert k in s, f"{name} missing silhouette lever {k}"
    # Silhouette tuples must be unique — no two languages may share the
    # (nav, KPI anatomy, border weight, radius) combination.
    tuples = {(s["nav"], s["kpi"], s["cardBorder"], s["radius"]) for s in SKINS.values()}
    assert len(tuples) == len(SKINS), "two skins share a silhouette"
    # And the loudest lever — KPI column count — must genuinely spread.
    assert len({s["kpiTemplate"] for s in SKINS.values()}) >= 5


# Rules inside the emitted stylesheet; `[^{}]*` keeps @media wrappers out of
# the match, so only innermost `selector { decls }` pairs are returned.
_CSS_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
# The band's own base tile rule — `:where([data-metric-tile], [data-importance])`
# and the zero-gap padding rule that shares that exact selector.
_KPI_TILE_RULE = re.compile(r"\[data-metric-tile\], \[data-importance\]\)\s*\{([^{}]*)\}")
_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}|rgba?\([^)]*\)|transparent")


def _kpi_band_rules(css):
    """Every rule (selector, declarations) that targets the KPI band."""
    return [(sel.strip(), decls) for sel, decls in _CSS_RULE.findall(css)
            if "data-metric-tile" in sel or "data-importance" in sel]


def _kpi_tile_silhouette(css):
    """The band's tile geometry with every colour masked out.

    Masking is the whole point: two languages that differ only in fill/ink
    collapse onto the same signature, so a pure recolour cannot pass as a
    restructure.
    """
    return _COLOUR.sub("C", "|".join(b.strip()
                                     for b in _KPI_TILE_RULE.findall(css)))


def test_component_css_restructures_the_kpi_band():
    """Skin CSS must RESTRUCTURE the KPI band, not just recolour it.

    This used to be pinned by asserting a `grid-template-columns:` override.
    That declaration is gone on purpose: column COUNT belongs to the composer
    (schema Grid columns=N). The skin's `!important` template beat a composed
    4-up band into the anatomy's 2-col mosaic at every width, phones included
    (live on cwx1stzz) — see the KPI band in design_language.py.

    What the band still guarantees is (a) a gap rule, floored at 8px so a
    `gap:0` anatomy can't fuse the tiles into one slab, and (b) a per-anatomy
    tile silhouette. The gap on its own is NOT what distinguishes skins — the
    floor collapses every zero-gap anatomy (shared-strip, glass-ribbon,
    boxless-hairline…) onto the same `gap: 8px`, which is over half the draws.
    So the restructuring claim is carried by the tile geometry below, checked
    colour-blind; the gap is asserted only for the floor it guarantees.
    """
    from services.design_dna import derive_design_dna, to_component_css, SKINS
    for skin in SKINS:
        d = derive_design_dna(project_id=f"k-{skin}", domain="ops")
        d["skin"] = skin
        css = to_component_css(d)
        assert f'[data-skin="{skin}"]' in css
        assert "--sk-nav-w" in css and "--sk-gutter" in css

        band = _kpi_band_rules(css)
        # the band container keeps its rhythm rule, floored
        gaps = [int(px) for sel, decls in band if ".grid:has(" in sel
                for px in re.findall(r"(?<!-)\bgap:\s*(\d+)px", decls)]
        assert gaps, f"{skin}: KPI band emits no gap rule"
        assert min(gaps) >= 8, f"{skin}: KPI gap below the 8px floor: {gaps}"
        # …and no band rule may dictate track count any more
        assert not any("grid-template-columns" in decls for _, decls in band), \
            f"{skin}: skin still overrides the composer's KPI column template"
        # …while the tile itself is genuinely restructured (geometry, not fill)
        assert _kpi_tile_silhouette(css), f"{skin}: band tile is not restructured"


def test_kpi_tile_silhouettes_differ_across_languages():
    """The claim the column template used to carry: the band is a real
    silhouette axis, so composed languages must draw structurally different
    tiles — not the same box in another colour."""
    from services.design_dna import derive_design_dna, to_component_css
    from services.design_language import KPI_ANATOMY
    doms = ["law firm", "gym", "freight", "clinic", "fintech", "store",
            "hr", "analytics"]
    sils = {_kpi_tile_silhouette(to_component_css(derive_design_dna(
        project_id=f"kpi{i}", domain=doms[i % len(doms)]))) for i in range(80)}
    assert len(sils) >= 10, f"only {len(sils)} KPI tile silhouettes: {sils}"
    assert len(sils) <= len(KPI_ANATOMY)
    # every silhouette is geometry — a recolour-only band would carry none
    for s in sils:
        assert any(p in s for p in ("padding", "border", "box-shadow",
                                    "display", "min-height", "clip-path")), s


def test_no_ai_slop_signatures():
    """Research named these as the recurring generated-UI tells. The composer
    must never emit them:
      * hairline border + wide diffuse shadow (the #1 signature)
      * a coloured edge-tab on a card (the most recognisable tell)
      * radius >= 16 on a data-dense ledger anatomy
    """
    from services.design_dna import derive_design_dna, to_component_css
    for i in range(120):
        d = derive_design_dna(project_id=f"slop{i}", domain="ops tool")
        lang = d["language"]
        bordered = lang["cardBorder"] >= 1 and lang["cardTreatment"] in (
            "hairline", "surface-step")
        assert not (bordered and lang["cardShadow"] in ("soft", "layered")), \
            f"{lang['signature']} emits border+diffuse-shadow (AI-slop tell)"
        # no accent-coloured card edge tab anywhere in the emitted CSS
        css = to_component_css(d)
        acc = d["color"]["accent"]
        assert f"border-top:6px solid {acc}" not in css
        assert f"border-left:4px solid {acc}" not in css


def test_every_numeral_face_can_actually_align():
    """Font binaries were inspected: these faces have proportional digits AND
    no `tnum`, so numbers can never align in a ruled column. None of them may
    be a numeral face. (Poppins measures a 31.5% digit-width spread; Fraunces
    20.1%; Marcellus 51.1%.)"""
    from services.design_language import TYPE_CLASSES
    BROKEN = {"Poppins", "DM Sans", "Fraunces", "Oswald", "Lexend", "Marcellus",
              "Albert Sans", "Urbanist", "Quicksand", "Instrument Serif",
              "Roboto Slab", "Playfair Display", "Josefin Sans", "League Spartan"}
    for name, t in TYPE_CLASSES.items():
        face = (t.get("num") or t["display"]).split(",")[0].strip("' ")
        assert face not in BROKEN, f"{name} uses {face} for numerals — cannot align"


def test_table_density_tracks_the_app_rhythm():
    """A 48px toolbar over 32px rows reads broken — row height must follow
    the composed density, not a constant."""
    from services.design_dna import derive_design_dna, to_component_css
    heights = set()
    for i in range(60):
        d = derive_design_dna(project_id=f"row{i}", domain="ops")
        css = to_component_css(d)
        for h in (32, 40, 48, 52, 56):
            if f"height:{h}px" in css:
                heights.add(h)
    assert len(heights) >= 3, f"row heights barely vary: {heights}"


def test_page_surface_varies_and_emits():
    """The ground the app sits on is the widest-reaching axis — a blueprint
    grid, a paper grain and a flat fill read as three different products
    before a single component renders."""
    from services.design_dna import derive_design_dna, to_component_css
    seen = set()
    for i in range(80):
        d = derive_design_dna(project_id=f"surf{i}", domain="analytics")
        lang = d["language"]
        seen.add(lang["surface"])
        css = to_component_css(d)
        if lang["surface"] == "grid-paper":
            assert "linear-gradient(to right" in css
        if lang["surface"] == "grain":
            assert "feTurbulence" in css
    assert len(seen) >= 6, f"only {len(seen)} surfaces drawn: {seen}"


def test_fallback_presets_are_legal():
    """Presets bypass the composer's gates, so they are the one place an
    illegal language could reach a real app. Hand-written ones silently
    violated the structural rules; these are search-derived and re-checked."""
    from services.design_language import _assert_fallbacks_valid, _FALLBACKS
    _assert_fallbacks_valid()
    sigs = {"·".join((f["navShape"], f["kpiAnatomy"], f["cardTreatment"],
                      f["radiusRegime"], f["typeClass"], f["surface"]))
            for f in _FALLBACKS}
    assert len(sigs) == len(_FALLBACKS), "fallback presets collide"


def test_micro_craft_layer_is_always_emitted():
    """Focus ring, selection, scrollbar and reduced-motion are the details
    that separate crafted from generated. WCAG 2.4.11 wants a >=2px ring;
    `outline` (not box-shadow) because box-shadow rings vanish entirely in
    forced-colors mode."""
    from services.design_dna import derive_design_dna, to_component_css
    for i in range(30):
        css = to_component_css(derive_design_dna(project_id=f"mc{i}", domain="hr"))
        assert "outline:2px solid" in css and ":focus-visible" in css
        assert "forced-colors: active" in css
        assert "::selection" in css and "text-shadow:none" in css
        assert "scrollbar-width:thin" in css
        assert "prefers-reduced-motion: reduce" in css


def test_zero_gap_kpi_anatomies_pad_their_cells():
    """Ledger/strip/ribbon anatomies separate cells with rules or a shared
    fill instead of gutters. Without inline padding one cell's delta butts
    straight against the next cell's label — seen rendering a real app."""
    from services.design_dna import derive_design_dna, to_component_css
    from services.design_language import KPI_ANATOMY
    zero = [k for k, v in KPI_ANATOMY.items() if v["gap"] == 0]
    assert zero, "expected some zero-gap anatomies"
    checked = 0
    for i in range(150):
        d = derive_design_dna(project_id=f"gap{i}", domain="fintech")
        if d["language"]["kpiAnatomy"] not in zero:
            continue
        checked += 1
        css = to_component_css(d)
        assert "padding-inline: 18px" in css
        # Order is the whole point: every selector here is :where() with zero
        # specificity, so an anatomy `padding` shorthand emitted later would
        # silently reset it. Asserting presence alone passed while broken.
        assert css.index("padding-inline: 18px") > css.rindex(
            "box-shadow:none; background:transparent"), \
            "zero-gap padding is emitted before the anatomy block and is dead"
    assert checked, "no zero-gap anatomy was drawn to check"


def test_emitted_css_is_brace_balanced_every_app():
    """A malformed @media block (an f-string/plain-string brace-escaping slip)
    emitted a stray `}`, which broke the ENTIRE generated stylesheet with
    'Unexpected }' — the app wouldn't boot. Caught on the first real generation
    (invoice software, 2026-07-28). Every emitted stylesheet, across every
    composed language and surface, must have balanced braces.
    """
    from services.design_dna import derive_design_dna, to_component_css, to_nav_css
    for i in range(200):
        d = derive_design_dna(project_id=f"brace{i}", domain="ops tool")
        for css in (to_component_css(d), to_nav_css(d)):
            assert css.count("{") == css.count("}"), (
                f"unbalanced braces in {d['language']['signature']}: "
                f"{css.count('{')} open vs {css.count('}')} close")
            # no doubled closing brace outside a data-URI (the exact prior bug)
            assert "}} }" not in css.replace("}} }", "", css.count("data:"))


def test_chrome_actually_varies_not_all_rails():
    """Chrome used to be inherited from the nav shape, and 12 of 20 shapes are
    left-rails, so ~60% of every domain's apps were wide-rail and top-nav/dock
    almost never appeared — 'the sidebar looks the same every app'. Chrome is
    now a first-class family draw. Across a domain, no single chrome may exceed
    ~40%, and across mixed domains every chrome family must appear.
    """
    import collections
    from services.design_dna import derive_design_dna

    ch = collections.Counter()
    for i in range(60):
        ch[derive_design_dna(project_id=f"chr{i}", domain="invoice software")
           ["language"]["chrome"]] += 1
    top = ch.most_common(1)[0][1]
    assert top <= 27, f"one chrome dominates ({top}/60): {dict(ch)}"
    assert len(ch) >= 4, f"too few chrome families in one domain: {dict(ch)}"

    allch = collections.Counter()
    doms = ["law firm", "gym", "freight", "clinic", "pets", "fintech",
            "dev api", "store", "hotel", "school", "hr", "consumer app"]
    for i in range(120):
        allch[derive_design_dna(project_id=f"ac{i}", domain=doms[i % len(doms)])
              ["language"]["chrome"]] += 1
    # all seven chrome families reachable across the domain spread
    assert len(allch) >= 6, f"chrome families missing across domains: {dict(allch)}"


def test_flex_kpi_tiles_declare_direction():
    """The MetricTile component ships a `flex-col` Tailwind class. An anatomy
    that sets `display:flex` but not `flex-direction` inherits that column
    direction, and `justify-content:space-between` then blows the label and
    value apart into big vertical gaps (seen live on LedgerFlow — the KPIs
    looked sparse and unfinished). Every tile rule that sets display:flex must
    also set flex-direction so the anatomy owns its own layout.
    """
    import re
    from services.design_dna import derive_design_dna, to_component_css
    for i in range(120):
        css = to_component_css(derive_design_dna(project_id=f"flx{i}",
                                                 domain="invoice software"))
        for block in re.findall(r"\[data-metric-tile[^{]*\{([^}]*)\}", css):
            if "display:flex" in block:
                assert "flex-direction" in block, \
                    f"flex KPI tile without a direction (defeated by flex-col): {block[:70]}"


def test_kpi_targets_data_hooks_not_paragraph_positions():
    """The register variants (linear/workday/…) nest the label in a header
    row, so both label and value are `p:first-of-type` in their own parent.
    The old `p:first-of-type` label selector therefore matched the VALUE too
    and shrank the big number to label size (12px, seen live on LedgerFlow).
    The emitter must target the unambiguous data-metric-label / -value hooks.
    """
    from services.design_dna import derive_design_dna, to_component_css
    css = to_component_css(derive_design_dna(project_id="hook1", domain="fintech"))
    assert "[data-metric-value]" in css and "[data-metric-label]" in css
    # the fragile position selectors must be gone from the KPI band
    assert "p:nth-of-type(2)" not in css
    assert "p:first-of-type" not in css
