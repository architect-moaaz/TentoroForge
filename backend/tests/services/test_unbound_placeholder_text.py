"""A field name is not a label. Text that is a bare column name never bound.

"Leave Balance by Type" on opmk18qr /dashboard reads, three times over:

    leaveTypeName
    Used: used / Allocated: allocated

Those are not values and not labels — they are the column names, sitting in
`Text.content` with no `{{ }}` around them. The node ids say what happened:
`balance-item-tpl-0`, `-tpl-1`, `-tpl-2`. A template was duplicated three
times and its placeholders were never bound to anything.

Wrapping them in braces would not help: there is no Repeat above them, so
there is no row to read a field from. The binding never existed. What the card
can honestly show is that it has nothing to show, so the placeholders are
replaced with the ordinary empty state — a card that admits it is empty beats
one that displays its own schema and looks like data.
"""
from services.unbound_placeholder_text import (
    is_unbound_placeholder, find_placeholder_cards, repair_unbound_templates,
)


class TestSpottingAFieldNameWhereALabelShouldBe:
    def test_a_camelcase_column_name_is_a_placeholder(self):
        assert is_unbound_placeholder("leaveTypeName") is True

    def test_a_bare_lowercase_column_name_is_a_placeholder(self):
        assert is_unbound_placeholder("used") is True
        assert is_unbound_placeholder("allocated") is True

    def test_a_real_binding_is_not(self):
        assert is_unbound_placeholder("{{leaveTypeName}}") is False

    def test_a_written_label_is_not(self):
        for good in ("Used:", "Leave Balance", "Total days remaining", "Allocated:"):
            assert is_unbound_placeholder(good) is False, good

    def test_a_number_or_symbol_is_not(self):
        for good in ("12", "—", "0%", "$4,200"):
            assert is_unbound_placeholder(good) is False, good

    def test_a_single_ordinary_word_is_not_assumed_to_be_a_column(self):
        # "Pending" is a plausible label. Only camelCase, or a word that also
        # names a column of a dataSource on the page, is evidence.
        assert is_unbound_placeholder("Pending") is False


class TestFindingTheCardsThatAreAllPlaceholder:
    def _card(self):
        return {"type": "Card", "props": {"title": "Leave Balance by Type"},
                "children": [{"type": "Stack", "children": [
                    {"type": "Stack", "id": "balance-item-tpl-0", "children": [
                        {"type": "Text", "props": {"content": "leaveTypeName"}},
                        {"type": "Text", "props": {"content": "Used:"}},
                        {"type": "Text", "props": {"content": "used"}},
                    ]},
                ]}]}

    def test_it_finds_the_live_card(self):
        page = {"root": {"children": [self._card()]}}
        found = find_placeholder_cards(page)
        assert len(found) == 1
        assert found[0]["props"]["title"] == "Leave Balance by Type"

    def test_a_card_with_real_bindings_is_left_alone(self):
        card = {"type": "Card", "props": {"title": "Real"}, "children": [
            {"type": "Text", "props": {"content": "{{leaveTypeName}}"}}]}
        assert find_placeholder_cards({"root": {"children": [card]}}) == []

    def test_a_card_of_prose_is_left_alone(self):
        card = {"type": "Card", "props": {"title": "Notes"}, "children": [
            {"type": "Text", "props": {"content": "Nothing to report today."}}]}
        assert find_placeholder_cards({"root": {"children": [card]}}) == []


class TestRepairingThem:
    def _page(self):
        return {"root": {"children": [
            {"type": "Card", "props": {"title": "Leave Balance by Type"},
             "children": [{"type": "Stack", "id": "balance-item-tpl-0", "children": [
                 {"type": "Text", "props": {"content": "leaveTypeName"}}]}]},
        ]}}

    def test_the_placeholders_are_gone(self):
        page = self._page()
        repair_unbound_templates(page)
        assert "leaveTypeName" not in str(page)

    def test_an_empty_state_takes_their_place(self):
        page = self._page()
        repair_unbound_templates(page)
        card = page["root"]["children"][0]
        assert card["children"], "the card must not be left blank"
        assert "EmptyState" in str(card) or "No " in str(card)

    def test_the_card_keeps_its_title(self):
        page = self._page()
        repair_unbound_templates(page)
        assert page["root"]["children"][0]["props"]["title"] == "Leave Balance by Type"

    def test_it_is_idempotent(self):
        page = self._page()
        repair_unbound_templates(page)
        assert repair_unbound_templates(page)["changed"] == 0

    def test_it_reports_what_it_replaced(self):
        page = self._page()
        report = repair_unbound_templates(page)
        assert "Leave Balance by Type" in str(report["notes"])
