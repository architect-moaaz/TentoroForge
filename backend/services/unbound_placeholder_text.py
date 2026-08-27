"""A field name is not a label — text that is a bare column name never bound.

"Leave Balance by Type" on opmk18qr /dashboard reads, three times over:

    leaveTypeName
    Used: used / Allocated: allocated

Those are column names sitting in ``Text.content`` with no braces round them.
The node ids give the game away — ``balance-item-tpl-0``, ``-tpl-1``,
``-tpl-2``: a template was duplicated three times and its placeholders were
never bound.

Wrapping them in ``{{ }}`` would not fix it. There is no Repeat above them, so
there is no row to read a field from — the binding does not exist, it was
never authored. Inventing one would be guessing at which dataSource and which
row, and a wrong guess ships a card that looks like data and is not.

So the card is told to say what is true: it has nothing to show. An empty
state is a worse-looking card than the designer intended and a far better one
than a card displaying its own schema — that one reads as real numbers to
anybody who is not looking closely.

This is a repair of last resort. The real fix is upstream, where the template
should either be bound to a Repeat or not emitted; this stops the defect
reaching a person in the meantime, and logs each one so the upstream gap
stays visible.
"""

from __future__ import annotations

import re
from typing import Any

# camelCase or snake_case with no spaces — the shape of a column name and not
# of anything a person writes into a UI label.
_CAMEL = re.compile(r"^[a-z]+(?:[A-Z][a-z0-9]*)+$")
_SNAKE = re.compile(r"^[a-z]+(?:_[a-z0-9]+)+$")

# Bare lowercase words that are column names in practice. Deliberately short:
# guessing that any lowercase word is a column would eat real labels.
_BARE_COLUMN_WORDS = {
    "used", "allocated", "remaining", "total", "count", "status", "name",
    "value", "amount", "quantity", "balance", "type", "date", "id",
}


def is_unbound_placeholder(text: Any) -> bool:
    """True when this text is a column name rather than something written."""
    if not isinstance(text, str):
        return False
    s = text.strip()
    if not s or "{{" in s:
        return False
    if s.endswith(":") or " " in s:
        return False           # "Used:" and "Total days" were written
    if _CAMEL.match(s) or _SNAKE.match(s):
        return True
    return s.lower() in _BARE_COLUMN_WORDS and s[:1].islower()


def _texts_under(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        if node.get("type") == "Text":
            c = (node.get("props") or {}).get("content")
            if isinstance(c, str):
                out.append(c)
        for c in (node.get("children") or []):
            _texts_under(c, out)
    elif isinstance(node, list):
        for c in node:
            _texts_under(c, out)


def _is_placeholder_card(card: dict) -> bool:
    texts: list[str] = []
    _texts_under(card, texts)
    placeholders = [t for t in texts if is_unbound_placeholder(t)]
    if not placeholders:
        return False
    # A card is "all placeholder" when nothing in it is a real binding. One
    # stray identifier beside working bindings is not this defect.
    if any("{{" in t for t in texts):
        return False
    return True


def find_placeholder_cards(page: dict) -> list[dict]:
    found: list[dict] = []

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for c in node:
                visit(c)
            return
        if not isinstance(node, dict):
            return
        if node.get("type") == "Card" and _is_placeholder_card(node):
            found.append(node)
            return          # don't descend into a card already condemned
        for c in (node.get("children") or []):
            visit(c)

    visit(page.get("root"))
    return found


def _empty_state_for(title: str) -> dict:
    subject = (title or "this").strip()
    return {
        "type": "EmptyState",
        "props": {
            "title": f"No {subject.lower()} yet",
            "description": "Records will appear here once they exist.",
        },
        "id": "placeholder-repaired-empty",
    }


def repair_unbound_templates(page: dict) -> dict[str, Any]:
    """Replace all-placeholder card bodies with an honest empty state."""
    notes: list[str] = []
    for card in find_placeholder_cards(page):
        title = (card.get("props") or {}).get("title") or "(untitled card)"
        card["children"] = [_empty_state_for(title)]
        notes.append(
            f"{title!r}: card body was unbound template placeholders "
            f"(bare column names as visible text) — replaced with an empty state")
    return {"changed": len(notes), "notes": notes}
