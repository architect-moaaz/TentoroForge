"""Tests for services.humanize_nav_flow_labels — the post-gen pass that
rewrites raw class-name labels (e.g. ``MemberSchedulePage``) in
``src/contracts/nav-flow.json`` to their route-derived human forms
(``Schedule``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.humanize_nav_flow_labels import (
    _humanize_route,
    _humanized_or_none,
    _looks_like_raw_classname,
    run,
)


def _write_nav(tmp_path: Path, nav: dict) -> Path:
    out = tmp_path / "output" / "app_test"
    p = out / "src" / "contracts"
    p.mkdir(parents=True, exist_ok=True)
    (p / "nav-flow.json").write_text(json.dumps(nav), encoding="utf-8")
    return out


# ── Pure helpers ────────────────────────────────────────────────────────────

def test_humanize_route_yoga_examples():
    assert _humanize_route("/schedule") == "Schedule"
    assert _humanize_route("/member/bookings") == "Bookings"
    assert _humanize_route("/instructor/sessions") == "Sessions"
    assert _humanize_route("/admin/dashboard") == "Dashboard"


def test_humanize_route_skips_dynamic_segments():
    """Next.js [id] and :param dynamic segments are not meaningful nouns."""
    assert _humanize_route("/instructor/sessions/[id]/roster") == "Roster"
    assert _humanize_route("/users/:id/profile") == "Profile"
    assert _humanize_route("/orders/[orderId]") == "Orders"


def test_humanize_route_kebab_snake_and_acronyms():
    assert _humanize_route("/team-members") == "Team Members"
    assert _humanize_route("/my_bookings") == "My Bookings"
    assert _humanize_route("/kpis/api-usage") == "API Usage"
    assert _humanize_route("/settings/url-config") == "URL Config"


def test_humanize_route_root_and_empty():
    assert _humanize_route("/") == "Home"
    assert _humanize_route("") == "Home"


def test_looks_like_raw_classname():
    assert _looks_like_raw_classname("MemberSchedulePage")
    assert _looks_like_raw_classname("AdminDashboardPage")
    # Not a class-name — human-authored label.
    assert not _looks_like_raw_classname("My Schedule")
    # Missing "Page" suffix.
    assert not _looks_like_raw_classname("MemberSchedule")
    # Non-string.
    assert not _looks_like_raw_classname(None)


def test_humanized_or_none_leaves_authored_labels_alone():
    """A genuinely authored label (not matching ^[A-Z][a-zA-Z0-9]*Page$)
    passes through as None (== no replacement)."""
    assert _humanized_or_none("My Schedule", "/schedule") is None


def test_humanized_or_none_rewrites_raw_classname():
    assert _humanized_or_none("MemberSchedulePage", "/schedule") == "Schedule"
    assert _humanized_or_none("AdminDashboardPage", "/admin/dashboard") == "Dashboard"


def test_humanized_or_none_falls_back_to_stripped_classname():
    """When the route yields no meaningful token, fall back to stripping
    'Page' and camelCase-splitting the class-name itself."""
    assert _humanized_or_none("MemberSchedulePage", "/") == "Member Schedule"


# ── Full end-to-end (run + file IO) ─────────────────────────────────────────

def test_run_rewrites_persona_screen_labels(tmp_path: Path):
    """The yoga-app regression: persona.screens labels are raw class-names."""
    out = _write_nav(tmp_path, {
        "personas": [{
            "id": "member", "name": "Member",
            "screens": [
                {"label": "MemberSchedulePage",   "route": "/schedule"},
                {"label": "MemberBookingsPage",   "route": "/member/bookings"},
                {"label": "MemberMembershipPage", "route": "/member/membership"},
                {"label": "MemberReviewsPage",    "route": "/member/reviews"},
            ],
        }],
    })
    res = run(str(out))
    assert res == {"rewritten": 4}
    nf = json.loads((out / "src" / "contracts" / "nav-flow.json").read_text(encoding="utf-8"))
    labels = [s["label"] for s in nf["personas"][0]["screens"]]
    assert labels == ["Schedule", "Bookings", "Membership", "Reviews"]


def test_run_leaves_authored_labels_alone(tmp_path: Path):
    """Human-authored labels are preserved verbatim."""
    out = _write_nav(tmp_path, {
        "personas": [{
            "id": "member", "name": "Member",
            "screens": [
                {"label": "My Schedule",    "route": "/schedule"},
                {"label": "Membership",     "route": "/member/membership"},
            ],
        }],
    })
    res = run(str(out))
    assert res == {"rewritten": 0}
    nf = json.loads((out / "src" / "contracts" / "nav-flow.json").read_text(encoding="utf-8"))
    labels = [s["label"] for s in nf["personas"][0]["screens"]]
    assert labels == ["My Schedule", "Membership"]


def test_run_also_repairs_pages_title_and_jobs(tmp_path: Path):
    """The same class-name leak can appear on pages[].title and on
    personas[].jobs[].label. Repair everywhere for symmetry."""
    out = _write_nav(tmp_path, {
        "pages": [
            {"id": "schedule", "route": "/schedule", "title": "MemberSchedulePage"},
        ],
        "personas": [{
            "id": "admin", "name": "Admin",
            "jobs": [{"id": "dash", "label": "AdminDashboardPage",
                       "route": "/admin/dashboard"}],
        }],
    })
    res = run(str(out))
    assert res == {"rewritten": 2}
    nf = json.loads((out / "src" / "contracts" / "nav-flow.json").read_text(encoding="utf-8"))
    assert nf["pages"][0]["title"] == "Schedule"
    assert nf["personas"][0]["jobs"][0]["label"] == "Dashboard"


def test_run_idempotent(tmp_path: Path):
    out = _write_nav(tmp_path, {
        "personas": [{"id": "m", "name": "Member",
                      "screens": [{"label": "MemberSchedulePage", "route": "/schedule"}]}],
    })
    run(str(out))
    assert run(str(out)) == {"rewritten": 0}


def test_run_missing_nav_flow_is_noop(tmp_path: Path):
    out = tmp_path / "output" / "empty_app"
    out.mkdir(parents=True)
    assert run(str(out)) == {"rewritten": 0}


def test_run_survives_malformed_json(tmp_path: Path):
    out = tmp_path / "output" / "bad_app"
    (out / "src" / "contracts").mkdir(parents=True)
    (out / "src" / "contracts" / "nav-flow.json").write_text("not json{", encoding="utf-8")
    assert run(str(out)) == {"rewritten": 0}
