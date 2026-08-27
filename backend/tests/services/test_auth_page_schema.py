"""TDD tests for auth_page_schema.py — SP1.5-F4.

Tests verify:
  - build_login_schema() produces a valid PageV2 envelope with no dashboard
    components and correct form fields (email + password).
  - emit_auth_page_schemas() writes login.json + signup.json for auth pages
    and leaves non-auth pages untouched. Returns the slugs written.
  - Regression guard: login.json declared route is "/login" (not "/leave-requests").
"""
from __future__ import annotations
import json
import os


# ── Helpers ───────────────────────────────────────────────────────────────────

def _all_nodes(obj: object) -> list[dict]:
    """Recursively collect every dict node in the schema tree."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _all_nodes(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _all_nodes(item)


def _has_type(schema: dict, type_name: str) -> bool:
    return any(n.get("type") == type_name for n in _all_nodes(schema))


def _find_form_fields(schema: dict) -> list[dict]:
    """Return the 'fields' list from the first Form node found."""
    for node in _all_nodes(schema):
        if node.get("type") == "Form":
            return node.get("props", {}).get("fields") or []
    return []


# ── build_login_schema ────────────────────────────────────────────────────────

class TestBuildLoginSchema:
    def setup_method(self):
        from services.auth_page_schema import build_login_schema
        self.schema = build_login_schema()

    def test_schema_version_is_2(self):
        assert self.schema["schemaVersion"] == "2"

    def test_route_is_login(self):
        """Regression guard: route must be /login, not /leave-requests or anything else."""
        assert self.schema.get("route") == "/login"

    def test_data_sources_empty(self):
        """Auth pages have no entity data sources."""
        assert self.schema.get("dataSources") == []

    def test_has_form_node(self):
        """Schema must contain a Form node somewhere in the tree."""
        assert _has_type(self.schema, "Form"), "Expected a Form node"

    def test_form_has_email_field(self):
        fields = _find_form_fields(self.schema)
        names = [f.get("name") for f in fields]
        assert "email" in names, f"email field not found; got {names}"

    def test_email_field_kind_is_email(self):
        fields = _find_form_fields(self.schema)
        email_fields = [f for f in fields if f.get("name") == "email"]
        assert email_fields, "email field missing"
        assert email_fields[0].get("kind") == "email"

    def test_form_has_password_field(self):
        fields = _find_form_fields(self.schema)
        names = [f.get("name") for f in fields]
        assert "password" in names, f"password field not found; got {names}"

    def test_password_field_kind_is_text(self):
        """Form schema has no 'password' kind — must use 'text'."""
        fields = _find_form_fields(self.schema)
        pw_fields = [f for f in fields if f.get("name") == "password"]
        assert pw_fields, "password field missing"
        assert pw_fields[0].get("kind") == "text", (
            "password field must use kind='text' (no 'password' kind in Form schema)"
        )

    def test_no_metric_tile(self):
        assert not _has_type(self.schema, "MetricTile"), "Dashboard MetricTile must not appear"

    def test_no_data_grid(self):
        assert not _has_type(self.schema, "DataGrid"), "Dashboard DataGrid must not appear"

    def test_no_grid(self):
        assert not _has_type(self.schema, "Grid"), "Dashboard Grid must not appear"

    def test_no_leave_request_string(self):
        dump = json.dumps(self.schema)
        assert "LeaveRequest" not in dump, "LeaveRequest must not appear in login schema"

    def test_submit_label_present(self):
        """Form must have a submitLabel so the user knows what to press."""
        for node in _all_nodes(self.schema):
            if node.get("type") == "Form":
                assert node.get("props", {}).get("submitLabel"), "submitLabel must be set"
                return
        raise AssertionError("No Form node found")

    def test_has_root_key(self):
        """Schema uses the PageV2 root-keyed envelope."""
        assert "root" in self.schema, "PageV2 schema must have a 'root' key"


# ── build_signup_schema ────────────────────────────────────────────────────────

class TestBuildSignupSchema:
    def setup_method(self):
        from services.auth_page_schema import build_signup_schema
        self.schema = build_signup_schema()

    def test_route_is_signup(self):
        assert self.schema.get("route") == "/signup"

    def test_schema_version_is_2(self):
        assert self.schema["schemaVersion"] == "2"

    def test_data_sources_empty(self):
        assert self.schema.get("dataSources") == []

    def test_has_form_node(self):
        assert _has_type(self.schema, "Form"), "Expected a Form node in signup schema"

    def test_form_has_password_field(self):
        fields = _find_form_fields(self.schema)
        names = [f.get("name") for f in fields]
        assert "password" in names, f"password field not found in signup; got {names}"

    def test_no_metric_tile(self):
        assert not _has_type(self.schema, "MetricTile")

    def test_has_root_key(self):
        assert "root" in self.schema


# ── emit_auth_page_schemas ────────────────────────────────────────────────────

SAMPLE_PLAN = {
    "pages": [
        {"route": "/login",          "type": "auth",  "name": "Login"},
        {"route": "/signup",         "type": "auth",  "name": "Signup"},
        {"route": "/leave-requests", "type": "list",  "name": "Leave Requests"},
    ]
}


class TestEmitAuthPageSchemas:
    def test_writes_login_and_signup_only(self, tmp_path):
        from services.auth_page_schema import emit_auth_page_schemas
        slugs = emit_auth_page_schemas(str(tmp_path), SAMPLE_PLAN)
        assert sorted(slugs) == ["login", "signup"]

    def test_login_json_exists(self, tmp_path):
        from services.auth_page_schema import emit_auth_page_schemas
        emit_auth_page_schemas(str(tmp_path), SAMPLE_PLAN)
        assert (tmp_path / "src" / "schemas" / "login.json").exists()

    def test_signup_json_exists(self, tmp_path):
        from services.auth_page_schema import emit_auth_page_schemas
        emit_auth_page_schemas(str(tmp_path), SAMPLE_PLAN)
        assert (tmp_path / "src" / "schemas" / "signup.json").exists()

    def test_leave_requests_not_written(self, tmp_path):
        from services.auth_page_schema import emit_auth_page_schemas
        emit_auth_page_schemas(str(tmp_path), SAMPLE_PLAN)
        assert not (tmp_path / "src" / "schemas" / "leave-requests.json").exists()

    def test_login_json_has_password_field(self, tmp_path):
        from services.auth_page_schema import emit_auth_page_schemas
        emit_auth_page_schemas(str(tmp_path), SAMPLE_PLAN)
        data = json.loads((tmp_path / "src" / "schemas" / "login.json").read_text())
        fields = _find_form_fields(data)
        names = [f.get("name") for f in fields]
        assert "password" in names

    def test_signup_json_has_password_field(self, tmp_path):
        from services.auth_page_schema import emit_auth_page_schemas
        emit_auth_page_schemas(str(tmp_path), SAMPLE_PLAN)
        data = json.loads((tmp_path / "src" / "schemas" / "signup.json").read_text())
        fields = _find_form_fields(data)
        names = [f.get("name") for f in fields]
        assert "password" in names

    def test_login_json_declared_route_is_login(self, tmp_path):
        """Regression guard: login.json must declare route '/login', not something else."""
        from services.auth_page_schema import emit_auth_page_schemas
        emit_auth_page_schemas(str(tmp_path), SAMPLE_PLAN)
        data = json.loads((tmp_path / "src" / "schemas" / "login.json").read_text())
        assert data.get("route") == "/login", (
            f"login.json declared wrong route: {data.get('route')!r}"
        )

    def test_signup_json_declared_route_is_signup(self, tmp_path):
        from services.auth_page_schema import emit_auth_page_schemas
        emit_auth_page_schemas(str(tmp_path), SAMPLE_PLAN)
        data = json.loads((tmp_path / "src" / "schemas" / "signup.json").read_text())
        assert data.get("route") == "/signup"

    def test_defensive_bad_plan_does_not_raise(self, tmp_path):
        """emit_auth_page_schemas is defensive — bad input must not raise."""
        from services.auth_page_schema import emit_auth_page_schemas
        # None plan
        result = emit_auth_page_schemas(str(tmp_path), None)
        assert isinstance(result, list)

    def test_defensive_empty_pages_does_not_raise(self, tmp_path):
        from services.auth_page_schema import emit_auth_page_schemas
        result = emit_auth_page_schemas(str(tmp_path), {"pages": []})
        assert result == []

    def test_only_auth_pages_written_with_mixed_plan(self, tmp_path):
        from services.auth_page_schema import emit_auth_page_schemas
        plan = {
            "pages": [
                {"route": "/login", "type": "auth", "name": "Login"},
                {"route": "/dashboard", "type": "dashboard", "name": "Dashboard"},
                {"route": "/users", "type": "list", "name": "Users"},
            ]
        }
        slugs = emit_auth_page_schemas(str(tmp_path), plan)
        assert slugs == ["login"]
        assert not (tmp_path / "src" / "schemas" / "dashboard.json").exists()
