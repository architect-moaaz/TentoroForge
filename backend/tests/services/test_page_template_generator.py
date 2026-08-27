from services.page_template_generator import generate_template_schema


def test_auth_login_template():
    s = generate_template_schema({"id": "login", "route": "/login", "type": "auth", "name": "Sign in"})
    assert s["id"] == "login"
    # Has a Form with email + password Input
    flat = _flatten(s["root"])
    assert any(n["type"] == "Form" for n in flat)
    inputs = [n for n in flat if n["type"] == "Input"]
    assert any(i["props"]["type"] == "email" for i in inputs)
    assert any(i["props"]["type"] == "password" for i in inputs)


def test_auth_signup_route():
    s = generate_template_schema({"id": "signup", "route": "/signup", "type": "auth", "name": "Create account"})
    flat = _flatten(s["root"])
    assert any(n["type"] == "Form" for n in flat)
    inputs = [n for n in flat if n["type"] == "Input"]
    # signup form has a name field
    assert any(i["props"]["name"] == "name" for i in inputs)


def test_list_template_with_entity():
    plan = {"entities": {"LeaveRequest": {"fields": {
        "id": {"type": "text"},
        "user_id": {"type": "text"},
        "status": {"type": "text"},
    }}}}
    s = generate_template_schema(
        {"id": "list", "route": "/leave-requests", "type": "list", "name": "Leave Requests", "entity": "LeaveRequest"},
        plan,
    )
    flat = _flatten(s["root"])
    grid = next(n for n in flat if n["type"] == "DataGrid")
    cols = grid["props"]["columns"]
    assert any(c["key"] == "user_id" for c in cols)


def test_list_template_data_source():
    plan = {"entities": {"Order": {"fields": {"id": {"type": "text"}}}}}
    s = generate_template_schema(
        {"id": "orders", "route": "/orders", "type": "list", "entity": "Order"},
        plan,
    )
    assert s["dataSources"] == [{"name": "items", "entity": "Order", "op": "list"}]


def test_dashboard_template_has_metrics():
    s = generate_template_schema({"id": "home", "route": "/", "type": "dashboard", "name": "Dashboard"})
    flat = _flatten(s["root"])
    metrics = [n for n in flat if n["type"] == "MetricTile"]
    assert len(metrics) >= 3  # Total, Active, Pending at minimum


def test_dashboard_data_sources_with_entity():
    plan = {"entities": {"Task": {"fields": {}}}}
    s = generate_template_schema(
        {"id": "dash", "route": "/dashboard", "type": "dashboard", "entity": "Task"},
        plan,
    )
    ops = [ds["op"] for ds in s["dataSources"]]
    assert "aggregate" in ops
    assert "list" in ops


def test_form_template_uses_entity_fields():
    plan = {"entities": {"User": {"fields": {
        "name": {"type": "text"},
        "email": {"type": "text"},
        "is_active": {"type": "boolean"},
    }}}}
    s = generate_template_schema(
        {"id": "users-new", "route": "/users/new", "type": "form", "name": "New User", "entity": "User"},
        plan,
    )
    flat = _flatten(s["root"])
    inputs = [n for n in flat if n["type"] in ("Input", "Checkbox")]
    assert any(i["props"]["name"] == "email" for i in inputs)
    # Boolean field becomes a Checkbox
    assert any(i["type"] == "Checkbox" and i["props"]["name"] == "is_active" for i in inputs)


def test_form_fallback_no_entity():
    s = generate_template_schema({"id": "new-item", "route": "/items/new", "type": "form", "name": "New Item"})
    flat = _flatten(s["root"])
    assert any(n["type"] == "Form" for n in flat)
    # Falls back to generic name/description inputs
    inputs = [n for n in flat if n["type"] == "Input"]
    assert any(i["props"]["name"] == "name" for i in inputs)


def test_detail_template_field_rows():
    plan = {"entities": {"Product": {"fields": {
        "sku": {"type": "text"},
        "price": {"type": "number"},
    }}}}
    s = generate_template_schema(
        {"id": "product-detail", "route": "/products/:id", "type": "detail", "entity": "Product"},
        plan,
    )
    flat = _flatten(s["root"])
    # Expect template-interpolated values for entity fields
    texts = [n for n in flat if n["type"] == "Text"]
    values = [t["props"]["content"] for t in texts]
    assert any("item.sku" in v for v in values)
    assert any("item.price" in v for v in values)


def test_settings_template():
    s = generate_template_schema({"id": "settings", "route": "/settings", "type": "settings", "name": "Settings"})
    flat = _flatten(s["root"])
    assert any(n["type"] == "Form" for n in flat)
    headings = [n for n in flat if n["type"] == "Heading"]
    assert any(h["props"]["content"] == "General" for h in headings)


def test_unknown_type_falls_back_to_generic():
    s = generate_template_schema({"id": "x", "route": "/x", "type": "weird", "name": "X"})
    assert s["root"]["type"] == "Stack"
    assert s["id"] == "x"


def test_home_type_maps_to_dashboard():
    s = generate_template_schema({"id": "home", "route": "/", "type": "home", "name": "Home"})
    flat = _flatten(s["root"])
    metrics = [n for n in flat if n["type"] == "MetricTile"]
    assert len(metrics) >= 3


def test_schema_version_and_shape():
    s = generate_template_schema({"id": "p", "route": "/p", "type": "list", "name": "P"})
    assert s["schemaVersion"] == "2"
    assert "id" in s
    assert "dataSources" in s
    assert "root" in s


def test_no_entity_context_produces_empty_data_sources():
    s = generate_template_schema({"id": "p", "route": "/p", "type": "list", "name": "P"})
    assert s["dataSources"] == []


def test_list_fallback_columns_when_no_entity():
    s = generate_template_schema({"id": "p", "route": "/p", "type": "list", "name": "P"})
    flat = _flatten(s["root"])
    grid = next(n for n in flat if n["type"] == "DataGrid")
    # Falls back to default id/name/createdAt columns
    keys = [c["key"] for c in grid["props"]["columns"]]
    assert "id" in keys
    assert "name" in keys


def test_field_type_email_inferred():
    plan = {"entities": {"Contact": {"fields": {
        "email_address": {"type": "text"},
    }}}}
    s = generate_template_schema(
        {"id": "c", "route": "/contacts/new", "type": "form", "entity": "Contact"},
        plan,
    )
    flat = _flatten(s["root"])
    inputs = [n for n in flat if n["type"] == "Input"]
    # email_address name triggers email input type
    assert any(i["props"]["type"] == "email" for i in inputs)


def test_textarea_for_long_text_field():
    plan = {"entities": {"Post": {"fields": {
        "body": {"type": "textarea"},
    }}}}
    s = generate_template_schema(
        {"id": "post", "route": "/posts/new", "type": "form", "entity": "Post"},
        plan,
    )
    flat = _flatten(s["root"])
    assert any(n["type"] == "Textarea" and n["props"]["name"] == "body" for n in flat)


def test_fields_as_list_of_dicts():
    plan = {"entities": {"Item": {"fields": [
        {"name": "title", "type": "text"},
        {"name": "qty", "type": "number"},
    ]}}}
    s = generate_template_schema(
        {"id": "item-form", "route": "/items/new", "type": "form", "entity": "Item"},
        plan,
    )
    flat = _flatten(s["root"])
    inputs = [n for n in flat if n["type"] == "Input"]
    assert any(i["props"]["name"] == "title" for i in inputs)
    assert any(i["props"]["name"] == "qty" for i in inputs)


# ── helpers ────────────────────────────────────────────────────────────────

def _flatten(node):
    out = [node]
    for c in (node.get("children") or []):
        if isinstance(c, dict):
            out.extend(_flatten(c))
    return out
