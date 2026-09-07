"""Backfill ``visibleTo`` on nav-flow pages from actor names + route
prefixes so `derive_shell_groups` can filter the sidebar per role.

Without this: candidate signs up on the generated ATS, gets a session,
and sees Reports / Team Management / Audit Log in the sidebar because
every page is treated as public."""
from __future__ import annotations

import json
from pathlib import Path

from services.page_visibility_derivation import derive_visible_to


def _write(root: Path, rel: str, doc: dict) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")


def _write_plan(root: Path, actors: list) -> None:
    _write(root, "contracts/plan.json", {"actors": actors})


def _write_nav(root: Path, pages: list, rel: str = "src/contracts/nav-flow.json") -> None:
    _write(root, rel, {"version": "1.0", "pages": pages, "auth_routes": []})


def _read_nav(root: Path, rel: str = "src/contracts/nav-flow.json") -> dict:
    return json.loads((root / rel).read_text(encoding="utf-8"))


# ────────────────────────────────────────────────────────────
# Happy path — route prefix matches actor slug
# ────────────────────────────────────────────────────────────

def test_candidate_prefix_route_scoped_to_candidate(tmp_path):
    _write_plan(tmp_path, [{"name": "Candidate"}, {"name": "Recruiter"}])
    _write_nav(tmp_path, [
        {"route": "/candidate/apply", "shell": True},
        {"route": "/recruiter/candidates", "shell": True},
        {"route": "/dashboard", "shell": True},
    ])
    r = derive_visible_to(tmp_path)
    nav = _read_nav(tmp_path)
    scoped = {p["route"]: p.get("visibleTo") for p in nav["pages"]}
    assert scoped["/candidate/apply"] == ["candidate"]
    assert scoped["/recruiter/candidates"] == ["recruiter"]
    assert scoped["/dashboard"] is None       # public — no actor prefix
    assert r["pages_scoped"] == 2
    assert r["pages_public"] == 1


def test_pluralized_route_matches_actor(tmp_path):
    """Planner sometimes uses plurals (``/candidates/[id]``); an actor
    "Candidate" should still match."""
    _write_plan(tmp_path, [{"name": "Candidate"}])
    _write_nav(tmp_path, [
        {"route": "/candidates/[id]", "shell": True},
        {"route": "/candidates", "shell": True},
    ])
    derive_visible_to(tmp_path)
    nav = _read_nav(tmp_path)
    for p in nav["pages"]:
        assert p["visibleTo"] == ["candidate"], p["route"]


def test_multi_word_actor_slug(tmp_path):
    """"Recruitment Administrator" slugifies to
    ``recruitment-administrator``. A route ``/recruitment-administrator/...``
    matches; ``/admin/...`` does NOT unless the plan names an "Admin"."""
    _write_plan(tmp_path, [{"name": "Recruitment Administrator"}])
    _write_nav(tmp_path, [
        {"route": "/recruitment-administrator/settings", "shell": True},
        {"route": "/admin/things", "shell": True},
    ])
    derive_visible_to(tmp_path)
    nav = _read_nav(tmp_path)
    scoped = {p["route"]: p.get("visibleTo") for p in nav["pages"]}
    assert scoped["/recruitment-administrator/settings"] == ["recruitment-administrator"]
    assert scoped["/admin/things"] is None


def test_pascalcase_actor_role_slug(tmp_path):
    """Planners sometimes emit ``role: "InterviewerPanel"`` — slugify
    should split PascalCase."""
    _write_plan(tmp_path, [{"role": "InterviewerPanel"}])
    _write_nav(tmp_path, [
        {"route": "/interviewer-panel/reviews", "shell": True},
    ])
    derive_visible_to(tmp_path)
    p = _read_nav(tmp_path)["pages"][0]
    assert p["visibleTo"] == ["interviewer-panel"]


# ────────────────────────────────────────────────────────────
# Skip conditions
# ────────────────────────────────────────────────────────────

def test_auth_routes_untouched(tmp_path):
    """Auth routes are already ``shell: false`` (SP1.5-F1); role
    scoping doesn't apply — visibleTo isn't stamped."""
    _write_plan(tmp_path, [{"name": "Candidate"}])
    _write_nav(tmp_path, [
        {"route": "/signup", "shell": False},
        {"route": "/login", "shell": False},
    ])
    derive_visible_to(tmp_path)
    nav = _read_nav(tmp_path)
    for p in nav["pages"]:
        # Not scoped (skipped); visibleTo key NOT added.
        assert "visibleTo" not in p, p["route"]


def test_existing_visible_to_not_overwritten(tmp_path):
    """If the planner already emitted a visibleTo, this pass leaves it
    alone — the backstop is BACKFILL, never STOMP."""
    _write_plan(tmp_path, [{"name": "Candidate"}, {"name": "Admin"}])
    _write_nav(tmp_path, [
        {"route": "/candidate/apply", "shell": True,
         "visibleTo": ["admin", "candidate"]},  # planner's choice
    ])
    derive_visible_to(tmp_path)
    p = _read_nav(tmp_path)["pages"][0]
    # Preserved verbatim; NOT overwritten to just ["candidate"].
    assert set(p["visibleTo"]) == {"admin", "candidate"}


def test_no_actors_leaves_pages_public(tmp_path):
    """No actor list → no way to scope anything; every non-auth page
    stays public."""
    _write_plan(tmp_path, [])
    _write_nav(tmp_path, [
        {"route": "/candidate/apply", "shell": True},
        {"route": "/dashboard", "shell": True},
    ])
    r = derive_visible_to(tmp_path)
    nav = _read_nav(tmp_path)
    for p in nav["pages"]:
        assert p["visibleTo"] is None
    assert r["pages_scoped"] == 0


# ────────────────────────────────────────────────────────────
# Robustness
# ────────────────────────────────────────────────────────────

def test_missing_plan_no_op(tmp_path):
    _write_nav(tmp_path, [{"route": "/candidate/apply", "shell": True}])
    r = derive_visible_to(tmp_path)
    # No plan → no actors → no scoping possible; pages stay public.
    p = _read_nav(tmp_path)["pages"][0]
    assert p["visibleTo"] is None
    assert r["actors_seen"] == []


def test_missing_nav_flow_no_op(tmp_path):
    _write_plan(tmp_path, [{"name": "Candidate"}])
    # No nav-flow → summary shows no scoping.
    r = derive_visible_to(tmp_path)
    assert r["pages_scoped"] == 0
    assert r["pages_public"] == 0


def test_pass_is_idempotent(tmp_path):
    _write_plan(tmp_path, [{"name": "Candidate"}])
    _write_nav(tmp_path, [
        {"route": "/candidate/apply", "shell": True},
        {"route": "/dashboard", "shell": True},
    ])
    first = derive_visible_to(tmp_path)
    second = derive_visible_to(tmp_path)
    # After the first run, /candidate/apply has visibleTo=["candidate"]
    # (skipped by the "existing" branch on second run), and /dashboard
    # has visibleTo=None → re-visited but same result.
    assert second["pages_scoped"] == 1
    assert second["pages_public"] == 1
    nav = _read_nav(tmp_path)
    scoped = {p["route"]: p.get("visibleTo") for p in nav["pages"]}
    assert scoped["/candidate/apply"] == ["candidate"]
    assert scoped["/dashboard"] is None
