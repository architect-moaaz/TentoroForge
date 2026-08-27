"""Section layout, enforced once over whatever composed the page.

A2UI says 'side by side'. Forge's Row says 'size each child to its content'.

Nothing reconciled the two, so a dashboard section holding three Cards rendered
them hugging the left edge with ~40% of the viewport dead — the live symptom on
1xbse9xr. `Row` is `flex flex-row` and a flex child defaults to `flex: 0 1 auto`,
so a Card with no width, basis or grow is exactly as wide as its text.

`Grid` already solves this: it owns a responsive column ladder
(columns=3 -> `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3`). The deterministic
dashboard composer learned to reach for it; the A2UI binder mapped Row -> Row
verbatim and never did.

So these tests pin the discriminator, not the styling. A row of content cards is
a LAYOUT of equal peers and becomes a Grid. A row of chrome — a greeting beside
a date picker — is a genuine row and must be left alone, because a Grid would
give the date picker half the page.
"""

import json

from services.section_layout import (
    density_for_columns, normalize_section_layout, shape_sections,
)


def _row(*kids, **props):
    return {"type": "Row", "props": props,
            "children": [dict(k) for k in kids]}


def _card(cid="c"):
    return {"type": "Card", "id": cid, "props": {}}


def test_a_row_of_cards_becomes_a_responsive_grid():
    """The live defect: row-mid / row-lists / row-bottom on 1xbse9xr."""
    out = shape_sections(_row(_card("a"), _card("b"), _card("c"), gap="md"))
    assert out["type"] == "Grid"
    assert out["props"]["columns"] == 3, "one column per peer"
    assert out["props"]["gap"] == "md", "the authored gap survives"
    assert [k["id"] for k in out["children"]] == ["a", "b", "c"]


def test_the_header_row_is_left_alone():
    """Greeting + date picker. A Grid would hand the picker half the page."""
    src = _row({"type": "Heading", "props": {}},
               {"type": "DateRangePicker", "props": {}},
               justify="between", align="center")
    assert shape_sections(src)["type"] == "Row"


def test_row_props_the_grid_cannot_honour_are_dropped():
    """Grid reads neither `justify` nor `align` nor `wrap` — carrying them
    over would leave dead props that read as intent nobody implements."""
    out = shape_sections(_row(_card("a"), _card("b"),
                              justify="between", align="stretch", wrap=True))
    assert "justify" not in out["props"]
    assert "align" not in out["props"]
    assert "wrap" not in out["props"]


def test_cards_in_a_converted_section_share_height_and_width():
    """Mixed content (a 3-row table beside a 9-row one) otherwise renders
    ragged, and a wide table otherwise steals its neighbours' share."""
    out = shape_sections(_row(_card("a"), _card("b")))
    assert out["props"]["equalRows"] is True
    assert out["props"]["equalCols"] is True


def test_an_explicit_single_line_row_is_respected():
    """`wrap: False` is the composer saying 'these belong on one line'.
    A Grid would wrap them at the first breakpoint."""
    out = shape_sections(_row(_card("a"), _card("b"), wrap=False))
    assert out["type"] == "Row"


def test_a_lone_card_stays_a_row():
    """A one-column Grid is a Row with extra words."""
    assert shape_sections(_row(_card("a")))["type"] == "Row"


def test_a_mixed_row_stays_a_row():
    """A Card beside a Button is not a set of peers."""
    src = _row(_card("a"), {"type": "Button", "props": {}})
    assert shape_sections(src)["type"] == "Row"


def test_a_grid_without_columns_gets_one_per_child():
    """`Grid sec-kpis {"gap":"md"}` with five MetricTiles — the renderer
    defaults `columns` to 1, so the KPI strip rendered as a single stacked
    column. The A2UI grid never carried the prop at all."""
    src = {"type": "Grid", "props": {"gap": "md"},
           "children": [{"type": "MetricTile", "props": {}} for _ in range(5)]}
    assert shape_sections(src)["props"]["columns"] == 5


def test_an_authored_column_count_is_never_overridden():
    src = {"type": "Grid", "props": {"columns": 2},
           "children": [{"type": "Card", "props": {}} for _ in range(4)]}
    assert shape_sections(src)["props"]["columns"] == 2


def test_sections_nested_under_the_page_stack_are_reached():
    """The real tree is Stack > Row > Card, never a bare Row."""
    page = {"type": "Stack", "props": {},
            "children": [_row(_card("a"), _card("b"))]}
    assert shape_sections(page)["children"][0]["type"] == "Grid"


def test_the_input_is_not_mutated():
    src = _row(_card("a"), _card("b"))
    shape_sections(src)
    assert src["type"] == "Row", "callers may still hold the original"


# ── density ──────────────────────────────────────────────────────────────
# Card picks its padding from a VIEWPORT breakpoint (`p-5 sm:p-8 md:p-10`), so
# on a wide desktop every card takes the loose 40px alike — the full-bleed one
# and the one-third-of-a-row one. 80px of a 467px card is 17% of it, and it is
# what pushed a five-column table past its own box on 1xbse9xr.
#
# A card cannot know how wide it is going to be. This function does: it has
# just decided how many columns the section has. So it is the one that says.
# Same authority shape as everything else here — the component that holds the
# knowledge makes the call, instead of two halves guessing past each other.


def test_a_three_up_section_tightens_its_cards():
    out = shape_sections(_row(_card("a"), _card("b"), _card("c")))
    assert [k["props"]["density"] for k in out["children"]] == ["tight"] * 3


def test_a_two_up_section_gets_the_middle_setting():
    out = shape_sections(_row(_card("a"), _card("b")))
    assert [k["props"]["density"] for k in out["children"]] == ["regular"] * 2


def test_a_full_width_card_is_left_spacious():
    """One card across the page has the room the loose default assumes."""
    page = {"type": "Stack", "props": {}, "children": [_card("solo")]}
    assert "density" not in shape_sections(page)["children"][0]["props"]


def test_an_authored_density_is_never_overridden():
    src = _row(dict(_card("a"), props={"density": "loose"}), _card("b"), _card("c"))
    assert shape_sections(src)["children"][0]["props"]["density"] == "loose"


def test_density_lands_on_an_existing_grid_too():
    """A Grid the composer already emitted has the same problem."""
    src = {"type": "Grid", "props": {"columns": 3},
           "children": [_card(f"c{i}") for i in range(3)]}
    assert shape_sections(src)["children"][0]["props"]["density"] == "tight"


def test_only_cards_carry_density():
    """MetricTile has no such prop — setting it would be a dead prop."""
    src = {"type": "Grid", "props": {"columns": 3},
           "children": [{"type": "MetricTile", "props": {}} for _ in range(3)]}
    assert all("density" not in k["props"] for k in shape_sections(src)["children"])


# ── the pass ─────────────────────────────────────────────────────────────
# These rules first lived inside the A2UI binder, so the deterministic
# composers — which own every dashboard A2UI declines, plus sub-dashboards,
# collections and records — shipped the cramped version of the same page. A
# layout invariant that lives inside one writer has to be re-learned by every
# other writer. These tests pin that it now applies to a schema on disk no
# matter who wrote it.


def _write(tmp_path, name, root):
    d = tmp_path / "src" / "schemas"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps({"schemaVersion": "2", "root": root}))
    return d / name


def test_it_reshapes_a_page_no_matter_who_composed_it(tmp_path):
    f = _write(tmp_path, "home.json", _row(_card("a"), _card("b"), _card("c")))
    res = normalize_section_layout(str(tmp_path))
    assert res["changed"] == 1
    root = json.loads(f.read_text())["root"]
    assert root["type"] == "Grid" and root["props"]["columns"] == 3
    assert root["children"][0]["props"]["density"] == "tight"


def test_nested_schema_directories_are_reached(tmp_path):
    """Larger apps nest schemas a level down; a flat glob would skip exactly
    the pages big enough to be cramped."""
    d = tmp_path / "src" / "schemas" / "reports"
    d.mkdir(parents=True)
    (d / "spend.json").write_text(json.dumps(
        {"schemaVersion": "2", "root": _row(_card("a"), _card("b"))}))
    assert normalize_section_layout(str(tmp_path))["changed"] == 1


def test_a_second_pass_changes_nothing(tmp_path):
    """Post-generate passes re-run; this one must be a fixed point."""
    _write(tmp_path, "home.json", _row(_card("a"), _card("b"), _card("c")))
    assert normalize_section_layout(str(tmp_path))["changed"] == 1
    assert normalize_section_layout(str(tmp_path))["changed"] == 0


def test_a_page_needing_nothing_is_not_rewritten(tmp_path):
    """Rewriting an unchanged file churns the diff and the mtime for nothing."""
    _write(tmp_path, "login.json", {"type": "Stack", "props": {},
                                    "children": [_card("solo")]})
    assert normalize_section_layout(str(tmp_path))["changed"] == 0


def test_an_unreadable_page_never_fails_the_build(tmp_path):
    d = tmp_path / "src" / "schemas"
    d.mkdir(parents=True)
    (d / "broken.json").write_text("{not json")
    (d / "ok.json").write_text(json.dumps(
        {"schemaVersion": "2", "root": _row(_card("a"), _card("b"))}))
    assert normalize_section_layout(str(tmp_path))["changed"] == 1


def test_no_schemas_directory_is_not_an_error(tmp_path):
    assert normalize_section_layout(str(tmp_path)) == {"changed": 0, "files": 0}


# ── runtime-expanded grids ───────────────────────────────────────────────
# A card grid is usually one Repeat that fans out to N cards when the data
# arrives. Its column count is NOT its child count, and inferring one would
# cement `columns: 1` — the single-stacked-column look — while making it read
# as a deliberate choice.


def test_a_repeat_grid_does_not_take_its_column_count_from_one_child():
    src = {"type": "Grid", "props": {"gap": "md"},
           "children": [{"type": "Repeat", "bind": "orders", "props": {}}]}
    assert "columns" not in shape_sections(src)["props"]


def test_an_authored_column_count_on_a_repeat_grid_is_kept():
    src = {"type": "Grid", "props": {"columns": 3},
           "children": [{"type": "Repeat", "bind": "orders", "props": {}}]}
    assert shape_sections(src)["props"]["columns"] == 3


def test_the_shared_density_rule_is_callable_by_the_composers():
    """Composers emit density at author time; the rule stays stated once."""
    assert density_for_columns(1) is None
    assert density_for_columns(2) == "regular"
    assert density_for_columns(3) == "tight"
    assert density_for_columns(5) == "tight"
