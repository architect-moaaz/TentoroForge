"""Tests for services/role_seams.py (Phase 6).

Covers UAT tests #14 (add role), #33 (remove role with impact), #48
(restrict page to role). Tests exercise the pure resolvers with plain
dict fixtures + a couple of round-trip tests through the file wrapper.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.role_seams import (
    add_role,
    add_role_in_file,
    remove_role,
    remove_role_in_file,
    restrict_page_to_role,
    restrict_page_to_role_in_file,
)


# --------------------------------------------------------------------------- #
# add_role                                                                    #
# --------------------------------------------------------------------------- #

class TestAddRole:
    def test_adds_to_empty_plan(self):
        plan = {}
        r = add_role(plan, "Editor")
        assert r["ok"] and r["added"]
        assert plan["actors"] == ["Editor"]

    def test_appends_to_existing_actors(self):
        plan = {"actors": ["Admin", "User"]}
        r = add_role(plan, "Editor")
        assert r["added"]
        assert plan["actors"] == ["Admin", "User", "Editor"]

    def test_idempotent_case_insensitive(self):
        plan = {"actors": ["admin"]}
        r = add_role(plan, "Admin")
        assert r["ok"] and not r["added"]
        assert plan["actors"] == ["admin"]

    def test_rejects_empty_name(self):
        r = add_role({}, "")
        assert not r["ok"]
        assert "required" in r["error"]

    def test_strips_whitespace(self):
        plan = {}
        r = add_role(plan, "  Editor  ")
        assert r["added"]
        assert plan["actors"] == ["Editor"]


# --------------------------------------------------------------------------- #
# remove_role                                                                 #
# --------------------------------------------------------------------------- #

class TestRemoveRole:
    def test_removes_present_role(self):
        plan = {"actors": ["Admin", "Editor", "User"]}
        r = remove_role(plan, "Editor")
        assert r["ok"] and r["removed"]
        assert plan["actors"] == ["Admin", "User"]

    def test_no_op_when_not_present(self):
        plan = {"actors": ["Admin", "User"]}
        r = remove_role(plan, "Editor")
        assert r["ok"] and not r["removed"]
        assert plan["actors"] == ["Admin", "User"]

    def test_reports_affected_pages(self):
        plan = {
            "actors": ["Admin", "Editor"],
            "pages": [
                {"route": "/admin", "access": {"roles": ["Admin", "Editor"]}},
                {"route": "/reports", "access": {"roles": ["Editor"]}},
                {"route": "/public", "access": {}},
                {"route": "/home"},
            ],
        }
        r = remove_role(plan, "Editor")
        assert r["removed"]
        assert set(r["affected_pages"]) == {"/admin", "/reports"}

    def test_reports_affected_pages_case_insensitive(self):
        plan = {
            "actors": ["Editor"],
            "pages": [{"route": "/x", "access": {"roles": ["editor"]}}],
        }
        r = remove_role(plan, "Editor")
        assert "/x" in r["affected_pages"]

    def test_rejects_empty_name(self):
        r = remove_role({}, "")
        assert not r["ok"]


# --------------------------------------------------------------------------- #
# restrict_page_to_role                                                       #
# --------------------------------------------------------------------------- #

class TestRestrictPageToRole:
    def test_sets_access_roles_on_new_page(self):
        plan = {"pages": [{"route": "/admin"}]}
        r = restrict_page_to_role(plan, "/admin", "Admin")
        assert r["ok"]
        assert plan["pages"][0]["access"]["roles"] == ["Admin"]

    def test_appends_to_existing_roles(self):
        plan = {"pages": [{"route": "/admin", "access": {"roles": ["Admin"]}}]}
        r = restrict_page_to_role(plan, "/admin", "Editor")
        assert r["ok"]
        assert plan["pages"][0]["access"]["roles"] == ["Admin", "Editor"]

    def test_idempotent_case_insensitive(self):
        plan = {"pages": [{"route": "/admin", "access": {"roles": ["Admin"]}}]}
        r = restrict_page_to_role(plan, "/admin", "admin")
        assert r["ok"]
        # NOT duplicated.
        assert plan["pages"][0]["access"]["roles"] == ["Admin"]

    def test_page_not_found(self):
        plan = {"pages": [{"route": "/home"}]}
        r = restrict_page_to_role(plan, "/missing", "Admin")
        assert not r["ok"]
        assert "not found" in r["error"]

    def test_rejects_empty_inputs(self):
        assert not restrict_page_to_role({}, "", "Admin")["ok"]
        assert not restrict_page_to_role({}, "/x", "")["ok"]


# --------------------------------------------------------------------------- #
# File wrappers                                                               #
# --------------------------------------------------------------------------- #

def _prep_plan_file(tmp_path: Path, plan: dict) -> str:
    d = tmp_path / "src" / "contracts"
    d.mkdir(parents=True, exist_ok=True)
    (d / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    return str(tmp_path)


class TestFileWrappers:
    def test_add_role_in_file_persists(self, tmp_path: Path):
        out = _prep_plan_file(tmp_path, {"actors": ["Admin"]})
        r = add_role_in_file(out, "Editor")
        assert r["ok"] and r["added"]
        # Read back.
        p = tmp_path / "src" / "contracts" / "plan.json"
        assert json.loads(p.read_text(encoding="utf-8"))["actors"] == ["Admin", "Editor"]

    def test_remove_role_in_file_persists(self, tmp_path: Path):
        out = _prep_plan_file(tmp_path, {
            "actors": ["Admin", "Editor"],
            "pages": [{"route": "/admin", "access": {"roles": ["Editor"]}}],
        })
        r = remove_role_in_file(out, "Editor")
        assert r["ok"] and r["removed"]
        assert r["affected_pages"] == ["/admin"]
        p = tmp_path / "src" / "contracts" / "plan.json"
        assert json.loads(p.read_text(encoding="utf-8"))["actors"] == ["Admin"]

    def test_restrict_page_in_file_persists(self, tmp_path: Path):
        out = _prep_plan_file(tmp_path, {"pages": [{"route": "/admin"}]})
        r = restrict_page_to_role_in_file(out, "/admin", "Admin")
        assert r["ok"]
        p = tmp_path / "src" / "contracts" / "plan.json"
        loaded = json.loads(p.read_text(encoding="utf-8"))
        assert loaded["pages"][0]["access"]["roles"] == ["Admin"]

    def test_missing_plan_reports_error(self, tmp_path: Path):
        r = add_role_in_file(str(tmp_path), "Admin")
        assert not r["ok"]
        assert "plan.json" in r["error"]
