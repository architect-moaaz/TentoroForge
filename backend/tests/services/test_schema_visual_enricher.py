"""Regression tests for the schema visual enricher post-pass."""
from services.schema_visual_enricher import (
    enrich_schema_visuals,
    _infer_feature_icon,
    _DEFAULT_FACE_POOL,
    _DEFAULT_HERO_BG,
    _DEFAULT_LOGIN_BG,
)


def _page(*children):
    return {"schemaVersion": "2", "id": "p", "children": list(children)}


def _avatar(node_id="a1", **props):
    return {"id": node_id, "type": "Avatar", "props": dict(props)}


def _hero(node_id="h1", **props):
    return {"id": node_id, "type": "Hero", "props": dict(props)}


def _feature(node_id="f1", title="Feature", **props):
    return {"id": node_id, "type": "FeatureCard", "props": {"title": title, **props}}


# ── Avatar enrichment ──────────────────────────────────────────────────────

def test_avatar_without_photo_gets_unsplash_url():
    sch = _page(_avatar("av1", name="Sarah"))
    n = enrich_schema_visuals(sch)
    assert n == 1
    avatar = sch["children"][0]
    photo = avatar["props"]["photoUrl"]
    assert photo.startswith("https://images.unsplash.com/"), photo


def test_avatar_with_photo_url_is_left_alone():
    """photoUrl already set → enricher must not overwrite."""
    original = "https://example.com/me.png"
    sch = _page(_avatar("av1", name="Sarah", photoUrl=original))
    n = enrich_schema_visuals(sch)
    assert n == 0
    assert sch["children"][0]["props"]["photoUrl"] == original


def test_avatar_with_legacy_src_is_left_alone():
    """src is the legacy prop — treat it as already-set so we don't double-emit."""
    sch = _page(_avatar("av1", name="Sarah", src="https://example.com/me.png"))
    n = enrich_schema_visuals(sch)
    assert n == 0
    assert "photoUrl" not in sch["children"][0]["props"]


def test_avatar_photo_is_stable_across_runs():
    """Re-running the enricher on the same schema produces the same URL —
    the hash-from-id picks the same bucket each time."""
    sch1 = _page(_avatar("av1", name="Sarah"))
    sch2 = _page(_avatar("av1", name="Sarah"))
    enrich_schema_visuals(sch1)
    enrich_schema_visuals(sch2)
    assert sch1["children"][0]["props"]["photoUrl"] == sch2["children"][0]["props"]["photoUrl"]


def test_design_spec_face_pool_overrides_default():
    custom_pool = ["https://example.com/face1.jpg", "https://example.com/face2.jpg"]
    sch = _page(_avatar("av1", name="X"))
    enrich_schema_visuals(sch, design_spec={"facePool": custom_pool})
    photo = sch["children"][0]["props"]["photoUrl"]
    assert photo in custom_pool


# ── Hero enrichment ────────────────────────────────────────────────────────

def test_hero_without_background_gets_one():
    sch = _page(_hero("h1", headline="Welcome"))
    n = enrich_schema_visuals(sch)
    assert n == 1
    bg = sch["children"][0]["props"]["backgroundImage"]
    assert isinstance(bg, dict) and bg["url"].startswith("https://images.unsplash.com/")
    assert bg["overlay"] == 0.4


def test_hero_uses_login_bg_when_route_is_auth():
    sch = _page(_hero("h1", headline="Sign in"))
    enrich_schema_visuals(sch, route="/login")
    bg = sch["children"][0]["props"]["backgroundImage"]["url"]
    assert bg == _DEFAULT_LOGIN_BG


def test_hero_uses_design_spec_dashboard_hero():
    custom = "https://example.com/branded-hero.jpg"
    sch = _page(_hero("h1", headline="Dashboard"))
    enrich_schema_visuals(sch, design_spec={"dashboardHero": custom}, route="/dashboard")
    bg = sch["children"][0]["props"]["backgroundImage"]["url"]
    assert bg == custom


def test_hero_with_existing_background_left_alone():
    existing = {"url": "https://example.com/keep.jpg", "overlay": 0.6}
    sch = _page(_hero("h1", headline="Hi", backgroundImage=existing))
    n = enrich_schema_visuals(sch)
    assert n == 0
    assert sch["children"][0]["props"]["backgroundImage"] == existing


def test_hero_with_media_prop_left_alone():
    """media is the alt prop name used by some heroes — treat it as
    already-supplying-imagery so backgroundImage isn't added."""
    sch = _page(_hero("h1", headline="Hi", media={"type": "video"}))
    n = enrich_schema_visuals(sch)
    assert n == 0
    assert "backgroundImage" not in sch["children"][0]["props"]


# ── FeatureCard icon inference ─────────────────────────────────────────────

def test_feature_card_security_title_gets_shield_icon():
    sch = _page(_feature("f1", title="Bank-grade security"))
    n = enrich_schema_visuals(sch)
    assert n == 1
    assert sch["children"][0]["props"]["icon"] == "shield"


def test_feature_card_realtime_title_gets_zap_icon():
    sch = _page(_feature("f1", title="Real-time updates"))
    enrich_schema_visuals(sch)
    assert sch["children"][0]["props"]["icon"] == "zap"


def test_feature_card_analytics_title_gets_chart_icon():
    sch = _page(_feature("f1", title="Powerful analytics"))
    enrich_schema_visuals(sch)
    assert sch["children"][0]["props"]["icon"] == "bar-chart"


def test_feature_card_with_icon_left_alone():
    sch = _page(_feature("f1", title="Security", icon="lock"))
    n = enrich_schema_visuals(sch)
    assert n == 0
    assert sch["children"][0]["props"]["icon"] == "lock"


def test_feature_card_unmatched_title_gets_no_icon():
    """Title with no keyword match is left untouched (better than a
    misleading icon)."""
    sch = _page(_feature("f1", title="Lorem ipsum fooblet"))
    enrich_schema_visuals(sch)
    assert "icon" not in sch["children"][0]["props"]


def test_infer_feature_icon_keyword_examples():
    assert _infer_feature_icon("Lightning fast") == "zap"
    assert _infer_feature_icon("Trusted by 10,000 teams") == "users"
    assert _infer_feature_icon("Custom workflows for your team") == "users"
    assert _infer_feature_icon("") is None


# ── Nested + mixed schema ─────────────────────────────────────────────────

def test_enricher_descends_into_nested_children():
    sch = _page({
        "id": "stack1", "type": "Stack",
        "children": [
            {"id": "card1", "type": "Card", "children": [
                _avatar("av1", name="Inner"),
                _feature("f1", title="Built for speed"),
            ]},
        ],
    })
    n = enrich_schema_visuals(sch)
    assert n == 2


def test_enricher_returns_zero_when_nothing_to_enrich():
    sch = _page({"id": "t", "type": "Text", "props": {"content": "Hello"}})
    n = enrich_schema_visuals(sch)
    assert n == 0


def test_default_face_pool_is_non_empty():
    assert len(_DEFAULT_FACE_POOL) > 0
    assert all(u.startswith("https://") for u in _DEFAULT_FACE_POOL)


def test_default_hero_urls_are_https():
    assert _DEFAULT_HERO_BG.startswith("https://")
    assert _DEFAULT_LOGIN_BG.startswith("https://")
