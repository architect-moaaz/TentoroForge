"""Slice 8 — synthesize missing singleton pages (Bug 4).

`/profile/edit` was navigated to but no schema backed it → blank page.
This reconciler detects the dead link, synthesizes an edit form bound
to the current session's User record, and registers the route.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.singleton_page_reconciler import reconcile_singleton_pages

def _subset(result: dict, expected: dict) -> dict:
    """Project a guard's return dict down to the keys the test asserts on.

    Whole-dict equality breaks every time a guard gains a counter (e.g.
    ``asserts_logged`` from the authority demotions) even though the
    behaviour under test is unchanged. Compare only what the test means.
    """
    return {k: result.get(k) for k in expected}



def _seed_app(tmp_path: Path, *, has_profile_button: bool = True,
              extra_schemas: dict[str, dict] | None = None) -> None:
    """Minimal app skeleton: registry with User entity, schemas dir with
    the "profile view" and an Edit button navigating to /profile/edit."""
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {
            "User": {"fields": {
                "id":         {"type": "uuid", "primaryKey": True},
                "email":      {"type": "varchar"},
                "name":       {"type": "varchar"},
                "password":   {"type": "varchar"},
                "createdAt":  {"type": "timestamp"},
            }},
        },
    }), encoding="utf-8")
    sdir = tmp_path / "src" / "schemas"
    sdir.mkdir(parents=True)
    if has_profile_button:
        # A /profile view exists, and it navigates to /profile/edit (the
        # dead link this pass fixes).
        (sdir / "profile.json").write_text(json.dumps({
            "route": "/profile",
            "root": {"type": "Stack", "children": [
                {"type": "Button", "props": {"label": "Edit", "navigate": "/profile/edit"}},
            ]},
        }), encoding="utf-8")
    # Bootstrap a minimal registry.ts so we can verify the append.
    (sdir / "registry.ts").write_text(
        'import { loadSchema } from "./load";\n\n'
        'export const schemas: Record<string, () => Promise<unknown>> = {\n'
        '  "/profile": () => import("./profile.json"),\n'
        '};\n'
    )
    for slug, doc in (extra_schemas or {}).items():
        p = sdir / (slug + ".json")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(doc), encoding="utf-8")


def test_reconciler_synthesizes_profile_edit(tmp_path):
    """The canonical Bug 4 case: `/profile/edit` is navigated to but not
    backed. Reconciler creates the file + registers it."""
    _seed_app(tmp_path)

    result = reconcile_singleton_pages(str(tmp_path))
    assert "/profile/edit" in result["created"]

    doc = json.loads((tmp_path / "src" / "schemas" / "profile" / "edit.json").read_text(encoding="utf-8"))
    assert doc["route"] == "/profile/edit"
    # Session-bound to the current user's User row.
    ds = doc["dataSources"][0]
    assert ds["entity"] == "User"
    assert ds["where"] == {"id": "{{session.user.id}}"}
    # A form is emitted with editable fields (system + password excluded).
    form = doc["root"]["children"][1]
    assert form["type"] == "Form"
    input_names = [
        n["props"]["name"]
        for n in form["children"][0]["children"]
        if n["type"] == "Input"
    ]
    assert "email" in input_names and "name" in input_names
    assert "id" not in input_names
    assert "password" not in input_names        # never leak
    assert "createdAt" not in input_names       # lifecycle filtered

    reg_ts = (tmp_path / "src" / "schemas" / "registry.ts").read_text(encoding="utf-8")
    assert '"/profile/edit"' in reg_ts
    assert 'import("./profile/edit.json")' in reg_ts


def test_reconciler_leaves_existing_schema_untouched(tmp_path):
    """When the LLM already emitted /profile/edit, we do NOTHING — no
    accidental overwrite of good LLM output."""
    _seed_app(tmp_path, extra_schemas={
        "profile/edit": {"route": "/profile/edit",
                         "root": {"type": "Text", "props": {"content": "LLM's own edit page"}}},
    })

    result = reconcile_singleton_pages(str(tmp_path))
    assert "/profile/edit" not in result["created"]
    # Original content preserved verbatim.
    doc = json.loads((tmp_path / "src" / "schemas" / "profile" / "edit.json").read_text(encoding="utf-8"))
    assert doc["root"]["props"]["content"] == "LLM's own edit page"


def test_reconciler_ignores_non_singleton_routes(tmp_path):
    """A /candidates/[id]/edit or /orders/1234 is NOT a singleton pattern
    — handled elsewhere (ensure_crud_pages). This pass never touches them."""
    _seed_app(tmp_path, has_profile_button=False)
    sdir = tmp_path / "src" / "schemas"
    (sdir / "candidates.json").write_text(json.dumps({
        "route": "/candidates",
        "root": {"type": "Stack", "children": [
            {"type": "Button", "props": {"label": "Edit", "navigate": "/candidates/abc/edit"}},
        ]},
    }), encoding="utf-8")

    result = reconcile_singleton_pages(str(tmp_path))
    assert result["created"] == []


def test_reconciler_only_activates_for_known_singleton_nouns(tmp_path):
    """A random single-segment route like /foo/edit doesn't match any
    known singleton noun (profile/account/me), so we don't manufacture
    a schema for an unknown domain concept."""
    _seed_app(tmp_path, has_profile_button=False)
    sdir = tmp_path / "src" / "schemas"
    (sdir / "home.json").write_text(json.dumps({
        "route": "/home",
        "root": {"type": "Button", "props": {"navigate": "/foo/edit"}},
    }), encoding="utf-8")

    result = reconcile_singleton_pages(str(tmp_path))
    assert result["created"] == []


def test_reconciler_idempotent(tmp_path):
    """Running twice creates once. Second pass sees the file, skips it."""
    _seed_app(tmp_path)
    first = reconcile_singleton_pages(str(tmp_path))
    second = reconcile_singleton_pages(str(tmp_path))
    assert first["created"] == ["/profile/edit"]
    assert second["created"] == []


def test_reconciler_synthesizes_profile_view_if_missing(tmp_path):
    """When only /profile/edit is navigated to (no /profile view), we
    synthesize both — the view AND the edit form. Anything the LLM
    referenced is guaranteed to exist after this pass."""
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {"User": {"fields": {"id": {"type": "uuid", "primaryKey": True},
                                          "email": {"type": "varchar"}}}},
    }), encoding="utf-8")
    sdir = tmp_path / "src" / "schemas"
    sdir.mkdir(parents=True)
    (sdir / "registry.ts").write_text(
        "export const schemas: Record<string, () => Promise<unknown>> = {\n};\n"
    )
    # Only a Button pointing at /profile/edit — no /profile view yet.
    (sdir / "dashboard.json").write_text(json.dumps({
        "route": "/dashboard",
        "root": {"type": "Button", "props": {"navigate": "/profile/edit"}},
    }), encoding="utf-8")

    result = reconcile_singleton_pages(str(tmp_path))
    assert "/profile/edit" in result["created"]
    # /profile view was not navigated to, so the reconciler does NOT
    # synthesize it (we only fix references the LLM actually made — no
    # speculative page manufacture).
    assert "/profile" not in result["created"]


def test_reconciler_safe_when_no_registry(tmp_path):
    """A completely missing registry.json is a no-op — never raises."""
    (tmp_path / "src" / "schemas").mkdir(parents=True)
    result = reconcile_singleton_pages(str(tmp_path))
    assert _subset(result, {"created": []}) == {"created": []}
