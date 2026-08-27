from services.crud_workflow_generator import build_crud_workflow

_FIELDS = [
    {"name": "id"}, {"name": "address"}, {"name": "createdAt"},
    {"name": "updatedAt"}, {"name": "deletedAt"},
]


def test_create_excludes_system_and_deletedat():
    wf = build_crud_workflow("Property", "properties", _FIELDS, "create")
    node = wf["definition"]["nodes"][1]
    values = node["data"]["config"]["values"]
    assert "address" in values
    for sys in ("id", "createdAt", "updatedAt", "deletedAt"):
        assert sys not in values, f"{sys} leaked into insert values"
    pvar_names = {p["name"] for p in wf["processVariables"]}
    assert "deletedAt" not in pvar_names
