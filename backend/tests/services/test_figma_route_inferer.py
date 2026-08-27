import pytest
from services.figma_route_inferer import infer_route_from_frame_name


@pytest.mark.parametrize("name, expected", [
    # Auth
    ("Login", "/login"),
    ("Sign in", "/login"),
    ("Sign up", "/signup"),
    ("Signup", "/signup"),
    ("Forgot password", "/forgot-password"),
    ("Reset password", "/reset-password"),
    # Dashboards
    ("Home", "/"),
    ("Dashboard", "/"),
    ("Overview", "/"),
    # List + form
    ("Users list", "/users"),
    ("Users / List", "/users"),
    ("New user", "/users/new"),
    ("Create user", "/users/new"),
    ("Edit user", "/users/[id]/edit"),
    ("User detail", "/users/[id]"),
    # Real-world with product prefixes
    ("Commitbiz_intentai_login", "/login"),
    ("Commitbiz_intentai_signup", "/signup"),
    ("01 - Login screen", "/login"),
    # Snake / camel → kebab
    ("user_settings", "/user-settings"),
    ("UserSettings", "/user-settings"),
    # Numeric / unnamed fallback
    ("Frame 32", "/page-32"),
    # Empty / whitespace
    ("", "/page"),
    ("   ", "/page"),
])
def test_infer_route(name, expected):
    assert infer_route_from_frame_name(name) == expected


def test_idempotent_on_clean_input():
    """A frame already named 'login' produces '/login'."""
    assert infer_route_from_frame_name("login") == "/login"


def test_handles_leading_trailing_whitespace():
    assert infer_route_from_frame_name("  Login  ") == "/login"
