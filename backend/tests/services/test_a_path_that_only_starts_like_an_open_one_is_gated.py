"""PR #28 review (2026-10-22). A route is open by its exact route, never by a word it starts with. `install` and `offline` (added for the installable web app)
as words in a negative lookahead left `/installments`, `/installers` and `/offline-orders` open to signed-out visitors, with the role check skipped too;
the older `pay`, `login` and `signup` did the same for `/payroll`, `/payments` and `/loginx`. (The platform's own open routes are now declared whole in
`services/blueprint/platform_routes.py`; these tests read the written middleware the way a request meets it.)

And an app whose pages do not say who may open them is gated, not public: `access` defaults to "authenticated" everywhere. The no-sign-in rule read the
missing value as "public" and took the sign-in away."""
import pytest

from services.blueprint.account_model import has_sign_in
from services.blueprint.projection import project_middleware
from tests.services._middleware_gate import Gate


def _page(pid, route, access="authenticated"):
    return {"id": pid, "name": route, "route": route, "access": access}


@pytest.fixture
def gate(tmp_path):
    doc = {"application": {"name": "Loans"}, "mobile": {"installable": True},
           "pages": [_page("PAGE-001", "/loans"), _page("PAGE-002", "/shop", "public"), _page("PAGE-003", "/shop/[id]", "public")]}
    project_middleware(doc, tmp_path)
    return Gate(tmp_path)


@pytest.mark.parametrize("path", ["/installments", "/installers", "/installations", "/offline-orders", "/payroll", "/payments", "/payouts", "/loginx",
                                  "/signups", "/api/authors", "/api/payments", "/shopping", "/shop-admin", "/api/webhooks-admin", "/set-password-reset"])
def test_a_path_that_only_starts_like_an_open_one_is_gated(gate, path):
    assert not gate.is_public(path), f"{path} must be gated"


@pytest.mark.parametrize("path", ["/install", "/offline", "/pay", "/pay/abc", "/login", "/signup", "/set-password", "/api/auth/session", "/api/cron/tick",
                                  "/shop", "/shop/42", "/_next/static/x.js", "/favicon.ico"])
def test_the_open_ones_and_what_is_under_them_stay_open(gate, path):
    assert gate.is_public(path), f"{path} must stay open"


def test_a_page_that_does_not_say_who_may_open_it_is_gated_so_the_sign_in_stays():
    doc = {"security": {"authentication": "email_password", "rbac": False, "protectedRoutes": []},
           "pages": [{"id": "PAGE-001", "name": "Loans", "route": "/loans"}, {"id": "PAGE-002", "name": "Plan", "route": "/plan"}]}
    assert has_sign_in(doc) is True


def test_only_pages_that_say_public_take_the_sign_in_away():
    doc = {"security": {"authentication": "email_password", "rbac": False, "protectedRoutes": []},
           "pages": [{"id": "PAGE-001", "name": "Loans", "route": "/loans", "access": "public"}]}
    assert has_sign_in(doc) is False
    doc["pages"].append({"id": "PAGE-002", "name": "Plan", "route": "/plan"})
    assert has_sign_in(doc) is True
