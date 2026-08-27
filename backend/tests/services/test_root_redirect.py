"""Regression lock for the generated-app root-redirect landing derivation.

Guards the class of bug where the app's `/` redirect targeted a dynamic route
(`redirect("/invite/[token]")` → 404). `derive_root_redirect` must never return
a dynamic / auth / form / non-shell route.
"""
from services.app_emitter import derive_root_redirect, _is_safe_landing


def _nav(pages, **extra):
    return {"pages": pages, **extra}


class TestIsSafeLanding:
    def test_rejects_dynamic_param_routes(self):
        assert not _is_safe_landing("/invite/[token]")
        assert not _is_safe_landing("/cats/[id]")
        assert not _is_safe_landing("/inventory/[id]/adjust")

    def test_rejects_root_auth_and_form_routes(self):
        assert not _is_safe_landing("/")
        assert not _is_safe_landing("/login")
        assert not _is_safe_landing("/signup")
        assert not _is_safe_landing("/register")
        assert not _is_safe_landing("/signin/callback")  # auth-prefix subpath
        assert not _is_safe_landing("/cats/new")
        assert not _is_safe_landing("/cats/[id]/edit")

    def test_rejects_non_shell_pages(self):
        assert not _is_safe_landing("/standalone", {"shell": False})

    def test_accepts_static_shell_content_routes(self):
        assert _is_safe_landing("/dashboard", {"shell": True})
        assert _is_safe_landing("/cats", {"shell": True})
        assert _is_safe_landing("/settings/household", {"shell": True})
        # shell flag absent (older nav-flow) is still eligible
        assert _is_safe_landing("/reports")


class TestDeriveRootRedirect:
    def test_the_exact_shipped_bug(self):
        """g4e8ksop's shape: initialPage=login, post_login=/signup (auth),
        invite-detail is the first non-auth page — must NOT be chosen."""
        nav = _nav(
            [
                {"id": "signup", "route": "/signup", "shell": True},
                {"id": "login", "route": "/login", "shell": True},
                {"id": "invite-detail", "route": "/invite/[token]", "shell": True},
                {"id": "dashboard", "route": "/dashboard", "shell": True},
                {"id": "cats", "route": "/cats", "shell": True},
            ],
            initialPage="login",
            initialFor=None,
            post_login_redirect="/signup",
        )
        initial_for, default = derive_root_redirect(nav)
        assert default == "/dashboard"
        assert "[" not in default
        assert initial_for == {}

    def test_prefers_dashboard_over_post_login(self):
        nav = _nav(
            [
                {"id": "orders", "route": "/orders", "shell": True},
                {"id": "dashboard", "route": "/dashboard", "shell": True},
            ],
            post_login_redirect="/orders",
        )
        _, default = derive_root_redirect(nav)
        assert default == "/dashboard"

    def test_uses_post_login_when_no_dashboard(self):
        nav = _nav(
            [{"id": "orders", "route": "/orders", "shell": True}],
            post_login_redirect="/orders",
        )
        _, default = derive_root_redirect(nav)
        assert default == "/orders"

    def test_dynamic_post_login_redirect_is_rejected(self):
        nav = _nav(
            [
                {"id": "w", "route": "/workspace/[id]", "shell": True},
                {"id": "list", "route": "/workspace", "shell": True},
            ],
            post_login_redirect="/workspace/[id]",
        )
        _, default = derive_root_redirect(nav)
        assert default == "/workspace"  # falls through to the first static shell page

    def test_falls_back_to_root_when_no_safe_page(self):
        """Only auth + dynamic + form pages → no safe landing → "/"."""
        nav = _nav(
            [
                {"id": "login", "route": "/login", "shell": True},
                {"id": "detail", "route": "/thing/[id]", "shell": True},
                {"id": "new", "route": "/thing/new", "shell": True},
            ],
            initialPage="login",
        )
        _, default = derive_root_redirect(nav)
        assert default == "/"

    def test_per_role_map_rejects_dynamic_targets(self):
        nav = _nav(
            [
                {"id": "dashboard", "route": "/dashboard", "shell": True},
                {"id": "profile", "route": "/profile/[id]", "shell": True},
            ],
            initialFor={"admin": "/dashboard", "member": "/profile/[id]"},
        )
        initial_for, default = derive_root_redirect(nav)
        assert initial_for == {"admin": "/dashboard"}  # dynamic member target dropped
        assert default == "/dashboard"

    def test_dashboard_string_never_chosen_if_no_such_page(self):
        """A phantom /dashboard (not a real page) must not be returned."""
        nav = _nav([{"id": "cats", "route": "/cats", "shell": True}])
        _, default = derive_root_redirect(nav)
        assert default == "/cats"

    def test_empty_nav_is_safe(self):
        initial_for, default = derive_root_redirect({"pages": []})
        assert default == "/"
        assert initial_for == {}
