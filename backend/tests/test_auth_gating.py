"""Auth-gating is a first-class plan decision that guarantees login/signup pages."""
from agents.planner import _decide_auth_gating, _ensure_auth_pages, _annotate_page_types


# ── the decision ────────────────────────────────────────────────────────────
def test_gated_when_app_has_entities():
    assert _decide_auth_gating({"entities": {"Order": {}}}) is True


def test_public_when_no_entities():
    assert _decide_auth_gating({"entities": {}, "pages": []}) is False
    assert _decide_auth_gating({"pages": []}) is False


def test_explicit_flag_respected():
    assert _decide_auth_gating({"authGated": False, "entities": {"X": {}}}) is False
    assert _decide_auth_gating({"authGated": True, "entities": {}}) is True


# ── ensuring pages ──────────────────────────────────────────────────────────
def test_gated_adds_login_and_signup():
    plan = {"pages": [{"route": "/orders", "name": "Orders"}]}
    _ensure_auth_pages(plan, gated=True)
    routes = [p["route"] for p in plan["pages"]]
    assert "/login" in routes and "/signup" in routes
    assert routes[0] == "/orders"                    # existing pages keep position
    assert all(p.get("type") == "auth"
               for p in plan["pages"] if p["route"] in ("/login", "/signup"))


def test_gated_is_idempotent_no_duplicate_auth_pages():
    plan = {"pages": [{"route": "/orders", "name": "Orders"}]}
    _ensure_auth_pages(plan, gated=True)
    _ensure_auth_pages(plan, gated=True)
    routes = [p["route"] for p in plan["pages"]]
    assert routes.count("/login") == 1 and routes.count("/signup") == 1


def test_public_strips_auth_pages():
    plan = {"pages": [
        {"route": "/login", "type": "auth"},
        {"route": "/signup", "type": "auth"},
        {"route": "/home", "name": "Home"},
    ]}
    _ensure_auth_pages(plan, gated=False)
    assert [p["route"] for p in plan["pages"]] == ["/home"]


# ── end-to-end through the sanitizer chain ──────────────────────────────────
def test_annotate_sets_flag_and_auth_pages_for_data_app():
    plan = {"entities": {"Order": {}}, "pages": [{"route": "/orders", "name": "Orders"}]}
    out = _annotate_page_types(plan)
    assert out["authGated"] is True
    routes = [p["route"] for p in out["pages"]]
    assert "/login" in routes and "/signup" in routes


def test_annotate_public_app_has_no_auth_pages():
    plan = {"entities": {}, "pages": [{"route": "/", "name": "Landing"}]}
    out = _annotate_page_types(plan)
    assert out["authGated"] is False
    assert all(p["route"] not in ("/login", "/signup") for p in out["pages"])
