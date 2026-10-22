"""PR #28 review (2026-10-22). The middleware matcher is a negative lookahead, which only looks at how a path STARTS. `install` and
`offline` (added for the installable web app) left `/installments`, `/installers` and `/offline-orders` open to signed-out visitors,
with the role check skipped too; the older `pay`, `login` and `signup` did the same for `/payroll`, `/payments` and `/loginx`.
Each entry now ends where a piece of the path ends.

And an app whose pages do not say who may open them is gated, not public: `access` defaults to "authenticated" everywhere. The
no-sign-in rule read the missing value as "public" and took the sign-in away."""
import json
import re

import pytest

from services.blueprint.account_model import has_sign_in
from services.blueprint.projection import project_middleware


def _matcher(tmp_path, pages):
    doc = {"application": {"name": "Loans"}, "pages": pages}
    project_middleware(doc, tmp_path)
    text = (tmp_path / "src/middleware.ts").read_text()
    raw = re.search(r'matcher: \[("(?:[^"\\]|\\.)*")\]', text).group(1)
    return re.compile("^" + json.loads(raw) + "$")


def _page(pid, route, access="authenticated"):
    return {"id": pid, "name": route, "route": route, "access": access}


@pytest.fixture
def matcher(tmp_path):
    return _matcher(tmp_path, [_page("PAGE-001", "/loans"), _page("PAGE-002", "/shop", "public"),
                               _page("PAGE-003", "/shop/[id]", "public")])


@pytest.mark.parametrize("path", ["/installments", "/installers", "/installations", "/offline-orders", "/payroll", "/payments",
                                  "/payouts", "/loginx", "/signups", "/api/authors", "/api/payments", "/shopping", "/shop-admin"])
def test_a_path_that_only_starts_like_an_open_one_goes_through_the_gate(matcher, path):
    assert matcher.match(path), f"{path} must be checked by the middleware"


@pytest.mark.parametrize("path", ["/install", "/offline", "/pay", "/pay/abc", "/login", "/signup", "/set-password", "/api/auth/session",
                                  "/_next/static/x.js", "/shop", "/shop/42", "/favicon.ico"])
def test_the_open_ones_and_what_is_under_them_stay_open(matcher, path):
    assert not matcher.match(path), f"{path} must stay open"


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
