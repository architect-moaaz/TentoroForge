"""Tests for the artifact validators."""
from __future__ import annotations
from services.artifact_validator import (
    validate_id_uniqueness,
    validate_registry_closure,
    validate_token_closure,
    validate_nav_consistency,
    validate_all,
)


REGISTRY = {
    "Stack": {"props": {"gap": {}, "padding": {}}},
    "Text": {"props": {"text": {}}},
    "Button": {"props": {"label": {}, "variant": {}}},
}


def _minimal_artifacts(root):
    return {
        "pageSchemas": {
            "home": {
                "schemaVersion": "2", "id": "home", "route": "/",
                "root": root,
            }
        },
        "navFlow": {
            "version": "1.0", "initialPage": "home",
            "pages": [{"id": "home", "route": "/", "title": "Home",
                       "schemaFile": "src/schemas/home.json", "params": []}],
            "transitions": [], "guards": {},
        },
        "tokens": {
            "color": {}, "typography": {}, "spacing": {},
            "radius": {}, "shadow": {}, "motion": {}, "breakpoints": {},
        },
    }


def test_id_uniqueness_clean():
    a = _minimal_artifacts({
        "id": "n1", "type": "Stack",
        "children": [{"id": "n2", "type": "Text", "props": {"text": "hi"}}],
    })
    assert validate_id_uniqueness(a) == []


def test_id_uniqueness_detects_duplicate():
    a = _minimal_artifacts({
        "id": "n1", "type": "Stack",
        "children": [
            {"id": "x", "type": "Text", "props": {"text": "a"}},
            {"id": "x", "type": "Text", "props": {"text": "b"}},
        ],
    })
    errs = validate_id_uniqueness(a)
    assert any("duplicate" in e for e in errs)


def test_id_uniqueness_detects_missing_id():
    a = _minimal_artifacts({
        "id": "n1", "type": "Stack",
        "children": [{"type": "Text", "props": {"text": "no id"}}],
    })
    errs = validate_id_uniqueness(a)
    assert any("missing id" in e for e in errs)


def test_registry_closure_unknown_component():
    a = _minimal_artifacts({
        "id": "n1", "type": "TotallyMadeUp", "props": {},
    })
    errs = validate_registry_closure(a, REGISTRY)
    assert any("TotallyMadeUp" in e for e in errs)


def test_registry_closure_unknown_prop():
    a = _minimal_artifacts({
        "id": "n1", "type": "Stack", "props": {"hallucinated": "x"},
    })
    errs = validate_registry_closure(a, REGISTRY)
    assert any("hallucinated" in e for e in errs)


def test_token_closure_detects_raw_hex():
    a = _minimal_artifacts({
        "id": "n1", "type": "Stack", "props": {"gap": "#FF0000"},
    })
    errs = validate_token_closure(a)
    assert any("hex" in e for e in errs)


def test_token_closure_detects_raw_px():
    a = _minimal_artifacts({
        "id": "n1", "type": "Stack", "props": {"padding": "16px"},
    })
    errs = validate_token_closure(a)
    assert any("px" in e for e in errs)


def test_token_closure_clean():
    a = _minimal_artifacts({
        "id": "n1", "type": "Stack", "props": {"gap": "md"},
    })
    assert validate_token_closure(a) == []


def test_nav_consistency_orphan_page_schema():
    a = _minimal_artifacts({"id": "n1", "type": "Stack"})
    a["pageSchemas"]["orphan"] = {
        "schemaVersion": "2", "id": "orphan", "route": "/orphan",
        "root": {"id": "orphan_root", "type": "Stack"},
    }
    errs = validate_nav_consistency(a)
    assert any("orphan" in e for e in errs)


def test_nav_consistency_unknown_transition_target():
    a = _minimal_artifacts({"id": "n1", "type": "Stack"})
    a["navFlow"]["transitions"] = [{"id": "t1", "from": "home", "trigger": "go", "to": "nowhere"}]
    errs = validate_nav_consistency(a)
    assert any("nowhere" in e for e in errs)


def test_validate_all_combines_errors():
    a = _minimal_artifacts({
        "id": "n1", "type": "Bogus", "props": {"gap": "#FF0000"},
    })
    errs = validate_all(a, REGISTRY)
    assert any("Bogus" in e for e in errs)
    assert any("hex" in e for e in errs)
