"""MENU-1 — icon_for(label): deterministic label → icon-name heuristic.

Used by :mod:`services.shell_menu_sync` to pick a sensible sidebar icon
for every menu item derived from ``nav-flow.json`` without needing an
LLM call per app rebuild."""
from __future__ import annotations

import pytest

from services.nav_icon_map import icon_for


# --------------------------------------------------------------------------- #
# People-shaped nouns → user
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("label", [
    "Users", "Members", "Candidates", "Recruiters", "Interviewers",
    "People", "Team", "Employees", "Staff",
])
def test_person_nouns_get_user_icon(label):
    assert icon_for(label) == "user"


# --------------------------------------------------------------------------- #
# Calendar-shaped nouns → calendar
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("label", [
    "Interviews", "Meetings", "Appointments", "Schedule",
    "Events", "Sessions",
])
def test_calendar_nouns_get_calendar_icon(label):
    assert icon_for(label) == "calendar"


# --------------------------------------------------------------------------- #
# Campaign / drive → briefcase (project-management vibe)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("label", [
    "Drives", "Recruitment Drives", "Campaigns",
    "Projects", "Missions", "Tasks",
])
def test_campaign_nouns_get_briefcase_icon(label):
    assert icon_for(label) == "briefcase"


# --------------------------------------------------------------------------- #
# Analytics → bar-chart
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("label", [
    "Analytics", "Reports", "Dashboard", "Metrics", "Insights", "Stats",
])
def test_analytics_get_barchart_icon(label):
    assert icon_for(label) == "bar-chart"


# --------------------------------------------------------------------------- #
# Audit / log / communication → clipboard
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("label", [
    "Audit", "Audit Log", "Logs", "Activity", "Communications",
    "Communication Log", "History", "Notifications",
])
def test_log_nouns_get_clipboard_icon(label):
    assert icon_for(label) == "clipboard"


# --------------------------------------------------------------------------- #
# File / document / upload / CV → file
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("label", [
    "Files", "Documents", "Uploads", "Attachments",
    "CVs", "Resumes", "CV Uploads",
])
def test_file_nouns_get_file_icon(label):
    assert icon_for(label) == "file"


# --------------------------------------------------------------------------- #
# Settings → settings
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("label", [
    "Settings", "Configuration", "Preferences", "Admin",
])
def test_settings_nouns_get_settings_icon(label):
    assert icon_for(label) == "settings"


# --------------------------------------------------------------------------- #
# Home / dashboard → home  (a special case beyond generic analytics)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("label", ["Home", "Overview"])
def test_home_gets_home_icon(label):
    assert icon_for(label) == "home"


# --------------------------------------------------------------------------- #
# Case + punctuation resilience
# --------------------------------------------------------------------------- #

def test_case_insensitive():
    assert icon_for("candidates") == "user"
    assert icon_for("CANDIDATES") == "user"
    assert icon_for("Candidates") == "user"


def test_route_input_works_like_label():
    """Callers may pass a bare route slug too."""
    assert icon_for("/candidates") == "user"
    assert icon_for("/recruiters") == "user"
    assert icon_for("/interviews") == "calendar"


def test_multi_word_prefers_most_specific():
    """'Interview Feedback' is calendar-ish (interview wins), not clipboard."""
    assert icon_for("Interview Feedback") == "calendar"


# --------------------------------------------------------------------------- #
# Fallback
# --------------------------------------------------------------------------- #

def test_unknown_falls_back_to_folder():
    assert icon_for("Widgets") == "folder"
    assert icon_for("Frobs") == "folder"
    assert icon_for("") == "folder"
    assert icon_for(None) == "folder"
