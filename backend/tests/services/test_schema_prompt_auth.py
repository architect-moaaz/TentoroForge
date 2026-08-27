from services.schema_prompt import build_schema_prompt


def test_login_route_prompt_includes_auth_exemplar():
    plan = {
        "entity": {"name": "User", "fields": []},
        "page_type": "form",
        "page": {"route": "/login", "name": "Login"}
    }
    prompt = build_schema_prompt(plan, design_spec={"register": "default"})
    assert "auth-split-illustration" in prompt
    # Should mention illustrations / the MCP tool
    assert "illustration" in prompt.lower()


def test_non_auth_form_does_not_get_auth_exemplar():
    plan = {
        "entity": {"name": "Note", "fields": []},
        "page_type": "form",
        "page": {"route": "/notes/new", "name": "New Note"}
    }
    prompt = build_schema_prompt(plan, design_spec={"register": "default"})
    assert "auth-split-illustration" not in prompt
