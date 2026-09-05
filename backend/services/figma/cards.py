"""A card on a list page opens the item, not the list it is already on.

The transform gives a clickable drawn card (`Container` with `navigate`) the
destination the action classifier bound from the card's title. The
classifier knows the routes but not which page the card sits on, so a policy
row titled "Refund & Cancellation Policy" bound to `/policies` — the very
page it was drawn on. Pressing it would do nothing, and nothing is worse
than no affordance.

The composer knows the page. When a card's destination is the page's own
route and the application has a detail route beneath it (`/policies/[id]`),
that is where the card goes; when there is no such route, the card keeps its
children and loses the action, which is what it was on the drawing.
"""
from __future__ import annotations

from typing import Iterable


def detail_route_for(route: str, routes: Iterable[str]) -> str | None:
    """`/policies` -> `/policies/[id]` when the application defines it."""
    if not route or route.endswith("]"):
        return None
    wanted = route.rstrip("/") + "/[id]"
    return wanted if wanted in set(routes) else None


def bind_cards(root: dict, page_route: str, routes: Iterable[str]) -> int:
    """Retarget or unbind every card that would navigate to its own page.

    Mutates in place; returns how many cards were changed.
    """
    routes = set(routes)
    detail = detail_route_for(page_route, routes)
    # A DETAIL PAGE DRAWS THE SAME LIST BESIDE THE ITEM. Its cards were bound
    # to the list route too, and from `/policies/[id]` a card that opens
    # `/policies` is the same no-op. On a detail page, a card aimed at the
    # list opens another item: the page's own route.
    own = {page_route}
    if page_route.endswith("/[id]"):
        own.add(page_route[: -len("/[id]")])
        detail = page_route
    changed = 0

    def walk(node: object) -> None:
        nonlocal changed
        if not isinstance(node, dict):
            return
        props = node.get("props") or {}
        if node.get("type") == "Container" and props.get("navigate") in own:
            if detail:
                props["navigate"] = detail
            else:
                props.pop("navigate", None)
            node["props"] = props
            changed += 1
        for child in node.get("children") or []:
            walk(child)

    walk(root)
    return changed
