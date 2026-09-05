"""A drawn card on a list page opens the item, never the page it is on.

The classifier bound "Refund & Cancellation Policy" to `/policies` — the
page the card was drawn on — because it knows the routes but not the page.
The composer knows the page: a card aimed at its own route is retargeted to
the detail route beneath it when one exists, and unbound when none does.
"""
from services.figma.cards import bind_cards, detail_route_for

ROUTES = ["/policies", "/policies/[id]", "/write-offs", "/dashboard"]


def _card(navigate=None, *texts):
    props = {"className": "bg-white"}
    if navigate:
        props["navigate"] = navigate
    return {"type": "Container", "props": props,
            "children": [{"type": "Text", "props": {"content": t}} for t in texts]}


def test_the_detail_route_is_the_id_route_beneath():
    assert detail_route_for("/policies", ROUTES) == "/policies/[id]"


def test_a_page_with_no_detail_route_has_none():
    assert detail_route_for("/dashboard", ROUTES) is None
    assert detail_route_for("/policies/[id]", ROUTES) is None


def test_a_card_aimed_at_its_own_page_opens_the_item():
    root = {"type": "Stack", "props": {}, "children": [_card("/policies", "Refund Policy", "v3.2")]}
    assert bind_cards(root, "/policies", ROUTES) == 1
    assert root["children"][0]["props"]["navigate"] == "/policies/[id]"


def test_a_card_aimed_elsewhere_is_left_alone():
    root = {"type": "Stack", "props": {}, "children": [_card("/write-offs", "Write-off", "Zedwell")]}
    assert bind_cards(root, "/policies", ROUTES) == 0
    assert root["children"][0]["props"]["navigate"] == "/write-offs"


def test_with_no_detail_route_the_card_keeps_its_children_and_loses_the_action():
    root = {"type": "Stack", "props": {}, "children": [_card("/dashboard", "Open cases", "4")]}
    assert bind_cards(root, "/dashboard", ROUTES) == 1
    card = root["children"][0]
    assert "navigate" not in card["props"]
    assert [c["props"]["content"] for c in card["children"]] == ["Open cases", "4"]


def test_the_composer_runs_it_after_the_chrome_split():
    import inspect
    from services.blueprint import figma_layout
    src = inspect.getsource(figma_layout.compose)
    assert src.index("_chrome.split") < src.index("_cards.bind_cards")


def test_on_a_detail_page_a_card_aimed_at_the_list_opens_another_item():
    """`/policies/[id]` draws the same list beside the item; its cards were
    bound to `/policies`, the same no-op from one step deeper."""
    root = {"type": "Stack", "props": {}, "children": [_card("/policies", "Legal Hold", "v1.4")]}
    assert bind_cards(root, "/policies/[id]", ROUTES) == 1
    assert root["children"][0]["props"]["navigate"] == "/policies/[id]"
