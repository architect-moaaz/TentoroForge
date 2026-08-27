"""List-page Layout DNA — spec.layout.list drives the collection shape.

The sameness bug: every generated list page was the same Table. The Layout
DNA gives each app a list vocabulary (table | card-grid | board | timeline |
split-list); these tests pin the builder's dispatch:

  * no DNA / unknown value  -> Table (byte-stable legacy behaviour)
  * card-grid               -> Grid > Repeat > Card bound via {{item.field}}
  * board + status column   -> the deterministic Kanban page
  * board w/o status column -> Table fallback (a board is impossible)
"""

import json

from services.deterministic_pages import build_list_page

COLS = {
    "id": {"type": "uuid"},
    "title": {"type": "string"},
    "status": {"type": "enum", "values": ["active", "done"]},
    "notes": {"type": "string"},
    "created_at": {"type": "datetime"},
}


def _child_types(page: dict) -> list[str]:
    return [c["type"] for c in page["root"]["children"]]


def test_no_dna_stays_table():
    page = build_list_page("Task", COLS, "/tasks", None)
    assert "Table" in _child_types(page)
    assert page["id"] == "tasks-list"


def test_unknown_composition_stays_table():
    page = build_list_page("Task", COLS, "/tasks", {"layout": {"list": "zigzag"}})
    assert "Table" in _child_types(page)


def test_card_grid_emits_grid_repeat_card():
    page = build_list_page("Task", COLS, "/tasks", {"layout": {"list": "card-grid"}})
    grids = [c for c in page["root"]["children"] if c["type"] == "Grid"]
    assert grids, f"no Grid in {_child_types(page)}"
    repeat = grids[0]["children"][0]
    assert repeat["type"] == "Repeat"
    assert repeat["bind"] == "tasks"  # same convention as apply_list_binding
    card = repeat["children"][0]
    assert card["type"] == "Card"
    # Bound via the Repeat item convention, so the runtime resolves per-row.
    assert card["props"]["title"].startswith("{{item.")
    # Every card links to the detail route with the row's own id.
    link = [c for c in card["children"] if c["type"] == "Link"]
    assert link and link[0]["props"]["navigate"] == "/tasks/{{item.id}}"
    # No Table on a card-grid page.
    assert "Table" not in json.dumps(page)


def test_board_with_status_becomes_kanban():
    page = build_list_page("Task", COLS, "/tasks", {"layout": {"list": "board"}})
    assert '"Kanban"' in json.dumps(page)
    assert '"Table"' not in json.dumps(page)


def test_board_without_status_falls_back_to_table():
    cols = {"id": {"type": "uuid"}, "name": {"type": "string"}}
    page = build_list_page("Exercise", cols, "/exercises", {"layout": {"list": "board"}})
    assert "Table" in _child_types(page)


def test_hero_led_dashboard_hero_props_match_schema():
    """hero-led emits Hero with schema-valid props: headline/subhead/ctas.

    Regression: the first cut emitted "subheadline" (not a Hero prop) and no
    ctas — Hero indexes ctas.length, so the node crashed into its error
    boundary and every hero-led dashboard opened with "Hero: render error".
    """
    from services.deterministic_pages import _compose_dashboard

    out = _compose_dashboard("hero-led", "Ops Dashboard", [], [], "tokens.spacing.4")
    hero = out[0]
    assert hero["type"] == "Hero"
    assert hero["props"]["headline"] == "Ops Dashboard"
    assert "subhead" in hero["props"] and "subheadline" not in hero["props"]
    assert hero["props"]["ctas"] == []
