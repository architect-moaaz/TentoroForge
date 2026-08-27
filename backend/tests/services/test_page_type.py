# backend/tests/services/test_page_type.py
from services.page_type import infer_page_type


class FakeBrief:
    def __init__(self, route: str, role: str = ""):
        self.route = route
        self.role = role


def test_list_route():
    assert infer_page_type(FakeBrief("/users/list")) == "list"
    assert infer_page_type(FakeBrief("/index")) == "list"


def test_detail_route_with_id():
    assert infer_page_type(FakeBrief("/users/[id]")) == "detail"
    assert infer_page_type(FakeBrief("/products/{id}/edit")) == "form"  # /edit wins


def test_form_route():
    assert infer_page_type(FakeBrief("/users/new")) == "form"
    assert infer_page_type(FakeBrief("/users/[id]/edit")) == "form"


def test_dashboard_route():
    assert infer_page_type(FakeBrief("/dashboard")) == "dashboard"
    assert infer_page_type(FakeBrief("/admin/overview")) == "dashboard"


def test_settings_route():
    assert infer_page_type(FakeBrief("/settings")) == "settings"
    assert infer_page_type(FakeBrief("/profile")) == "settings"


def test_role_fallback_when_route_is_generic():
    assert infer_page_type(FakeBrief("/x", role="browse all teammates")) == "list"
    assert infer_page_type(FakeBrief("/x", role="create a new entity")) == "form"
    assert infer_page_type(FakeBrief("/x", role="show kpi metrics")) == "dashboard"


def test_generic_when_nothing_matches():
    assert infer_page_type(FakeBrief("/foo", role="bar")) == "generic"


def test_handles_missing_role():
    # role attribute is None
    class NoRole:
        route = "/users/list"
        role = None
    assert infer_page_type(NoRole()) == "list"


# Wave 5 archetype tests

def test_workspace():
    class B: route, role = "/workspace", ""
    assert infer_page_type(B()) == "workspace"


def test_wizard():
    class B: route, role = "/onboarding/step-1", "multi-step"
    assert infer_page_type(B()) == "wizard"


def test_audit_log():
    class B: route, role = "/audit", "compliance log"
    assert infer_page_type(B()) == "audit-log"


def test_report():
    class B: route, role = "/reports/headcount", ""
    assert infer_page_type(B()) == "report"


def test_console():
    class B: route, role = "/console", "operations console"
    assert infer_page_type(B()) == "console"
