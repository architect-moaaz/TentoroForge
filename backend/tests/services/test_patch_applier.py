# backend/tests/services/test_patch_applier.py
import pytest
from services.patch_applier import validate_patches, ValidationError


SCHEMA = {
    "schemaVersion": "2",
    "id": "users/list",
    "route": "/users",
    "meta": {"title": "Users"},
    "dataSources": [],
    "root": {
        "id": "root",
        "type": "Stack",
        "props": {"gap": "md"},
        "children": [
            {"id": "hero", "type": "Hero", "props": {"headline": "Users"}, "children": []},
            {"id": "table", "type": "Table", "props": {"columns": [
                {"key": "name", "label": "Name"},
                {"key": "email", "label": "Email"},
            ]}}
        ]
    }
}


def test_valid_replace_passes():
    patches = [{"op": "replace", "path": "/root/children/0/props/headline", "value": "Team"}]
    errors = validate_patches(patches, SCHEMA)
    assert errors == []


def test_unresolved_path_returns_error():
    patches = [{"op": "replace", "path": "/root/children/99/props/x", "value": "y"}]
    errors = validate_patches(patches, SCHEMA)
    assert len(errors) == 1
    assert errors[0].kind == "path_unresolved"


def test_add_to_array_end_is_valid():
    patches = [{"op": "add", "path": "/root/children/-", "value": {"id": "x", "type": "Card", "props": {}}}]
    errors = validate_patches(patches, SCHEMA)
    assert errors == []


def test_remove_root_is_rejected():
    patches = [{"op": "remove", "path": "/root"}]
    errors = validate_patches(patches, SCHEMA)
    assert len(errors) == 1
    assert errors[0].kind == "cannot_remove_required"


def test_multiple_patches_collect_multiple_errors():
    patches = [
        {"op": "replace", "path": "/root/children/0/props/headline", "value": "Team"},  # ok
        {"op": "replace", "path": "/root/children/99/props/x", "value": "y"},           # unresolved
        {"op": "remove", "path": "/root"},                                                # cannot_remove_required
    ]
    errors = validate_patches(patches, SCHEMA)
    assert len(errors) == 2
    kinds = {e.kind for e in errors}
    assert kinds == {"path_unresolved", "cannot_remove_required"}


def test_malformed_patch_missing_op():
    patches = [{"path": "/root/children/0", "value": "x"}]  # missing 'op'
    errors = validate_patches(patches, SCHEMA)
    assert len(errors) == 1
    assert errors[0].kind == "malformed_patch"


from services.patch_applier import apply_patches_transactional, PatchApplyError


def test_apply_replace_returns_new_schema_unchanged_input():
    schema_before = {"a": {"b": 1}}
    patches = [{"op": "replace", "path": "/a/b", "value": 2}]
    after = apply_patches_transactional(patches, schema_before, validate_zod=False)
    assert after == {"a": {"b": 2}}
    assert schema_before == {"a": {"b": 1}}  # input untouched


def test_apply_add_to_array():
    schema_before = {"items": [1, 2]}
    patches = [{"op": "add", "path": "/items/-", "value": 3}]
    after = apply_patches_transactional(patches, schema_before, validate_zod=False)
    assert after == {"items": [1, 2, 3]}


def test_apply_multiple_patches_in_order():
    schema_before = {"a": 1, "b": 2}
    patches = [
        {"op": "replace", "path": "/a", "value": 10},
        {"op": "replace", "path": "/b", "value": 20},
    ]
    after = apply_patches_transactional(patches, schema_before, validate_zod=False)
    assert after == {"a": 10, "b": 20}


def test_apply_failure_mid_sequence_raises_no_disk_writes():
    schema_before = {"a": 1}
    patches = [
        {"op": "replace", "path": "/a", "value": 99},          # would succeed
        {"op": "replace", "path": "/missing", "value": "x"},   # would fail (path doesn't exist)
    ]
    with pytest.raises(PatchApplyError):
        apply_patches_transactional(patches, schema_before, validate_zod=False)
    # input untouched — caller still sees the original schema
    assert schema_before == {"a": 1}


def test_zod_validation_failure_raises():
    """When validate_zod=True and the result schema doesn't match PageV1|PageV2."""
    schema_before = {
        "schemaVersion": "2",
        "id": "x", "route": "/x", "meta": {"title": "X"},
        "dataSources": [],
        "root": {"id": "r", "type": "Stack", "props": {}, "children": []}
    }
    patches = [{"op": "remove", "path": "/route"}]
    with pytest.raises(PatchApplyError, match="invalid schema"):
        apply_patches_transactional(patches, schema_before, validate_zod=True)
