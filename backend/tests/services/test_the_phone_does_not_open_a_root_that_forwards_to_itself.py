"""The phone's home is a route it can open.

`app/index.tsx` forwards "/" to `HOME`. An application with no page at "/" and a `HOME` of "/" sent the root to itself
for ever: the loading circle, and "Maximum update depth exceeded" in the log. The phone now lands where the web lands."""
from __future__ import annotations

from services.blueprint.native_projection import config_module, phone_route

PAGES = [
    {"id": "PAGE-001", "name": "Workouts", "route": "/workouts", "pattern": "entity_list"},
    {"id": "PAGE-002", "name": "Progress", "route": "/progress", "pattern": "dashboard"},
]


def doc(pages, initial=None):
    return {"application": {"name": "Iron Log"}, "pages": pages, "navigation": {"initialRoute": initial or {}}}


def test_a_root_with_no_page_goes_to_the_landing_page():
    assert phone_route(doc(PAGES), "/") == "/workouts"


def test_a_declared_landing_page_is_used():
    assert phone_route(doc(PAGES, {"default": "/progress"}), "/") == "/progress"


def test_an_app_with_a_page_at_the_root_keeps_it():
    pages = [{"id": "PAGE-001", "name": "Home", "route": "/", "pattern": "dashboard"}, *PAGES]
    assert phone_route(doc(pages), "/") == "/"


def test_another_route_is_left_alone():
    assert phone_route(doc(PAGES), "/progress") == "/progress"


def test_the_written_config_never_names_a_root_that_forwards_to_itself():
    text = config_module(doc(PAGES))
    assert 'HOME: string = "/workouts"' in text and 'AFTER_SIGNUP: string = "/workouts"' in text
