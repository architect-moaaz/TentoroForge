"""Login/signup pages must adopt the app's theme (industry-derived palette via shadcn
tokens) + app name, not a generic white card — and redirect to '/' (a real route),
not '/dashboard' (a route group, not a URL)."""
from pathlib import Path

_LOGIN = Path("templates/app-foundation/src/app/login/page.tsx").read_text(encoding="utf-8")
_SIGNUP = Path("templates/app-foundation/src/app/signup/page.tsx").read_text(encoding="utf-8")


def test_login_uses_theme_tokens_and_app_name():
    for tok in ("bg-primary", "text-primary-foreground", "bg-background", "text-muted-foreground"):
        assert tok in _LOGIN, tok
    assert "__APP_NAME__" in _LOGIN          # substituted to the real app name at gen time
    assert "bg-slate-900" not in _LOGIN      # the generic hardcoded button is gone


def test_signup_themed_and_app_name():
    assert "bg-primary" in _SIGNUP and "__APP_NAME__" in _SIGNUP
    assert "bg-slate-900" not in _SIGNUP


def test_post_auth_redirect_is_a_real_route():
    # /dashboard is a route GROUP (no URL); index lives at "/"
    assert '|| "/"' in _LOGIN
    assert 'router.push("/")' in _SIGNUP
    assert "/dashboard" not in _LOGIN and "/dashboard" not in _SIGNUP


def test_login_uses_the_real_hook_contract():
    """The auth pages must destructure useLogin's ACTUAL return keys.

    Regression: the composed template destructured `loading`/`onSubmit`, but the
    hook returns `isLoading`/`handleSubmit`. The handler was therefore undefined,
    the <form> lost its onSubmit, and submitting did a NATIVE GET — the URL
    became "/login?" and sign-in silently did nothing.
    """
    hook = Path("templates/app-foundation/src/hooks/useLogin.ts").read_text(encoding="utf-8")
    # Whatever the hook returns is the contract; the page must match it.
    import re
    returned = set(re.findall(r"\breturn \{([^}]*)\}", hook)[-1].replace(" ", "").split(","))
    assert {"isLoading", "handleSubmit"} <= returned, returned
    assert "handleSubmit" in _LOGIN and "isLoading" in _LOGIN
    # the wrong names must not be bound from the hook
    assert "onSubmit={onSubmit}" not in _LOGIN
    assert "disabled={loading}" not in _LOGIN


def test_auth_layout_placeholder_present():
    """Composition placeholder must survive so runtime_injector can fill it."""
    assert "__AUTH_LAYOUT__" in _LOGIN
    assert "__AUTH_LAYOUT__" in _SIGNUP
