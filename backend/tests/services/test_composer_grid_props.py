"""The composers emit a grid the renderer can actually read.

Two of them emitted `cols`. Grid reads `p.columns`, as a NUMBER, and falls back
to 1 when it is absent — so `{"cols": 4}` and `{"cols": {"base":1,"lg":3}}` both
rendered a single stacked column. Nothing warned: `cols` is a plausible name,
it just isn't the one, and the drift only shows up as a look.

They also emitted no `density`, so every card took the loose padding whatever
its share of the row. The composer knows the column count at the moment it
builds the grid, so it is the one that should say — same rule as the
post-generate pass, imported from it rather than restated.
"""

from services.dashboard_composer import _grid
from services.section_layout import density_for_columns


def _card(i=0):
    return {"type": "Card", "props": {}, "children": []}


class TestDashboardComposerGrid:
    def test_it_emits_the_prop_the_renderer_reads(self):
        g = _grid([_card(), _card(), _card()], 3)
        assert g["props"]["columns"] == 3
        assert "cols" not in g["props"], "Grid never read `cols`"

    def test_the_column_count_is_a_number(self):
        """Grid ignores anything that is not a number and falls back to 1."""
        assert isinstance(_grid([_card()], 4)["props"]["columns"], int)

    def test_cards_are_told_their_share_of_the_row(self):
        g = _grid([_card(), _card(), _card()], 3)
        assert [c["props"]["density"] for c in g["children"]] == ["tight"] * 3

    def test_a_two_up_grid_gets_the_middle_setting(self):
        g = _grid([_card(), _card()], 2)
        assert [c["props"]["density"] for c in g["children"]] == ["regular"] * 2

    def test_a_single_column_grid_leaves_the_card_spacious(self):
        g = _grid([_card()], 1)
        assert "density" not in g["children"][0]["props"]

    def test_it_agrees_with_the_post_generate_pass(self):
        """If these ever disagree, a page changes shape depending on which one
        got there first. They must read the same rule."""
        for n in (1, 2, 3, 4, 5):
            g = _grid([_card() for _ in range(n)], n)
            got = {c["props"].get("density") for c in g["children"]}
            assert got == {density_for_columns(n)}

    def test_peers_share_height_and_width(self):
        g = _grid([_card(), _card()], 2)
        assert g["props"]["equalRows"] is True
        assert g["props"]["equalCols"] is True

    def test_non_card_children_carry_no_density(self):
        g = _grid([{"type": "MetricTile", "props": {}}], 3)
        assert "density" not in g["children"][0]["props"]


class TestCollectionCardGrid:
    """The collection card grid emitted `cols: {"base":1,"sm":2,"lg":3}` — a
    responsive object. Grid takes a NUMBER and owns its own responsive ladder
    (columns=3 -> `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3`), which is the
    very ladder that object was describing. So it rendered one column while
    asking for the thing the renderer already does.

    Its children are a single Repeat that fans out at runtime, so the column
    count cannot come from the child count — it has to be stated.
    """

    def _grid_node(self):
        from services.apply_collection_maquette import _card_grid_node
        return _card_grid_node("orders", "/orders/{{item.id}}", [])

    def test_it_states_a_numeric_column_count(self):
        g = self._grid_node()
        assert isinstance(g["props"]["columns"], int)
        assert "cols" not in g["props"], "Grid never read `cols`"

    def test_the_column_count_is_stated_not_inferred(self):
        """The only child is a Repeat that fans out at runtime, so nothing
        downstream can count the cards for us."""
        g = self._grid_node()
        assert g["children"][0]["type"] == "Repeat"
        assert g["props"]["columns"] > 1

    def test_the_repeated_card_is_told_its_share(self):
        g = self._grid_node()
        card = g["children"][0]["children"][0]
        assert card["props"]["density"] == density_for_columns(g["props"]["columns"])

    def test_the_repeat_still_binds_by_bare_name(self):
        """Guarding the fix this grid already carried."""
        assert self._grid_node()["children"][0]["bind"] == "orders"
