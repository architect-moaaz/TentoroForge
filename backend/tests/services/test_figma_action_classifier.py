from services.figma_action_classifier import classify_button_action, infer_input_name, _slugify


def test_signin_button():
    # Only emits workflow — no hardcoded navigate; runtime reads post_login_redirect
    assert classify_button_action("Sign in") == {"workflow": "auth.signIn"}
    assert "navigate" not in classify_button_action("Sign in")

def test_signup_variants():
    result_up = classify_button_action("Sign up")
    assert result_up == {"workflow": "auth.signUp"}
    assert "navigate" not in result_up
    result_reg = classify_button_action("Register")
    assert result_reg == {"workflow": "auth.signUp"}
    assert "navigate" not in result_reg

def test_signout_variants():
    # Only emits workflow — no hardcoded navigate; runtime reads post_logout_redirect
    for label in ("Sign out", "Log out", "Logout"):
        result = classify_button_action(label)
        assert result == {"workflow": "auth.signOut"}, f"failed for {label!r}"
        assert "navigate" not in result, f"unexpected navigate for {label!r}"

def test_forgot_password():
    assert classify_button_action("Forgot password?") == {"navigate": "/forgot-password"}

def test_reset_filters():
    assert classify_button_action("Reset Filters")["workflow"] == "filters.reset"

def test_dashboard_nav():
    assert classify_button_action("Dashboard") == {"navigate": "/dashboard"}

def test_view_analytics():
    assert classify_button_action("View Analytics") == {"navigate": "/analytics"}

def test_view_unknown_workflow():
    out = classify_button_action("View Context")
    assert "workflow" in out
    assert out["workflow"].startswith("view.")

def test_unknown_label_default_workflow():
    out = classify_button_action("Convert to Lead")
    assert out["workflow"] == "convert.toLead"

def test_empty_label():
    assert classify_button_action("") == {}

def test_infer_input_name_from_data_name():
    assert infer_input_name("Email Input", "email") == "email"
    assert infer_input_name("Password Input", "password") == "password"
    assert infer_input_name("Phone Number Input", "text") == "phoneNumber"

def test_infer_input_name_fallback():
    assert infer_input_name("", "email") == "email"
    assert infer_input_name("", "password") == "password"
    assert infer_input_name("", "text", placeholder="Search signals...") == "search"

def test_slugify():
    assert _slugify("Convert to Lead") == "convert.toLead"
    assert _slugify("Start Outreach") == "start.Outreach"
    assert _slugify("hello") == "hello"
