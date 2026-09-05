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

def test_view_unknown_infers_nothing():
    """"View Context" used to become the workflow `view.context`.

    No such workflow exists, and the Blueprint validator rejects a page whose
    button targets one that is not defined."""
    assert classify_button_action("View Context") == {}


def test_unknown_label_infers_nothing():
    """The default was `{"workflow": _slugify(label)}` — a workflow id named
    after whatever the button said.

    It cost a real 15-screen design every one of its pages: "Dashboard",
    "Front Desk" and "New Case" each invented a target, the validator refused
    each page with "targets workflow 'dashboard', which this application does
    not define", and the run finished with no layouts — frontend, testing and
    preview all skipped behind them.

    A button with no action renders and can be wired later; a button pointing
    at a workflow that was never defined cannot be part of any valid page."""
    assert classify_button_action("Convert to Lead") == {}


def test_a_label_that_does_match_still_infers():
    """The floor stays: declining is for what did NOT match, not for
    everything."""
    assert classify_button_action("Sign in") != {}

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
