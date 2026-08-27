"""Tests for the nav-flow Pydantic shape."""
from contracts.nav_flow import NavFlow, NavFlowPageEntry, NavFlowTransition, NavFlowGuard, empty_nav_flow


def test_parses_canonical_json():
    raw = {
        "version": "1.0",
        "initialPage": "home",
        "pages": [
            {"id": "home", "route": "/", "title": "Home",
             "schemaFile": "src/schemas/home.json", "guard": None, "params": []}
        ],
        "transitions": [
            {"id": "t1", "from": "home", "trigger": "go", "to": "other"}
        ],
        "guards": {
            "requiresAuth": {"redirectTo": "login", "condition": "x == y"}
        }
    }
    nav = NavFlow.model_validate(raw)
    assert nav.initial_page == "home"
    assert nav.pages[0].schema_file == "src/schemas/home.json"
    assert nav.transitions[0].from_page == "home"
    assert nav.guards["requiresAuth"].redirect_to == "login"


def test_round_trips_through_aliases():
    raw = {
        "version": "1.0",
        "initialPage": "home",
        "pages": [{"id":"home","route":"/","title":"Home","schemaFile":"x"}],
        "transitions": [],
        "guards": {}
    }
    nav = NavFlow.model_validate(raw)
    dumped = nav.model_dump(by_alias=True, exclude_none=True)
    assert dumped["initialPage"] == "home"
    assert dumped["pages"][0]["schemaFile"] == "x"
    # Round-trip back to model
    nav2 = NavFlow.model_validate(dumped)
    assert nav2.initial_page == "home"


def test_empty_nav_flow_helper():
    nav = empty_nav_flow()
    assert nav.initial_page == ""
    assert nav.pages == []
    assert nav.transitions == []
    assert nav.guards == {}


def test_optional_fields_have_defaults():
    page = NavFlowPageEntry(id="home", route="/", title="Home", schema_file="x")
    assert page.layout is None
    assert page.guard is None
    assert page.params == []
