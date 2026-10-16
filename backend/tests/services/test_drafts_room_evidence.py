"""Evidence with standings: what a study saw stays seen; a guess never
promotes itself; the surface study's dossier becomes evidence too."""
from __future__ import annotations

import pytest

from services.drafts_room import evidence as ev


def _obs(text, kind="field", source=None):
    return ev.item("r1", kind, text, standing="observed", source=source or {"type": "response", "ref": "GET /x"})


def _inf(text, kind="field"):
    return ev.item("r1", kind, text, standing="inferred", source={"type": "dossier", "ref": "j1"})


def test_a_standing_is_raised_only_by_a_captured_source_and_never_lowered():
    items, notes = ev.merge([], [_inf("Order.total")])
    assert items[0]["standing"] == "inferred"
    # A captured fact raises it…
    items, notes = ev.merge(items, [_obs("order.total")])
    assert len(items) == 1 and items[0]["standing"] == "observed" and len(items[0]["sources"]) == 2
    # …a later guess does not lower it…
    items, notes = ev.merge(items, [_inf("Order.total")])
    assert items[0]["standing"] == "observed" and not notes
    # …and an "observed" claim without a captured source does not raise one.
    claim = ev.item("r1", "field", "Order.status", standing="observed", source={"type": "dossier", "ref": "j1"})
    items, notes = ev.merge([_inf("Order.status")], [claim])
    assert items[0]["standing"] == "inferred" and "does not raise it" in notes[0]


def test_identity_is_the_reference_the_kind_and_the_text():
    a = _obs("Order", kind="record")
    b = ev.item("r2", "record", "Order", standing="observed", source={"type": "response", "ref": "x"})
    c = _obs("order", kind="screen")
    items, _ = ev.merge([a], [b, c])
    assert len(items) == 3


def test_a_bad_standing_or_kind_is_refused():
    with pytest.raises(ValueError):
        ev.item("r", "field", "x", standing="seen", source={})
    with pytest.raises(ValueError):
        ev.item("r", "thing", "x", standing="observed", source={})


def test_the_dossier_becomes_evidence_by_what_it_can_point_at():
    job = {"id": "j1", "reference_id": "r1", "dossier": {
        "screens": [{"name": "Cart", "url": "https://x.test/cart", "shot": "s1", "shows": ["items"]},
                    {"name": "Wishlist"}],
        "features": [{"name": "Save for later", "source": "https://x.test/help"}],
        "entities": [{"name": "Order", "fields": [{"name": "total", "type": "money"}]}],
        "rules": [{"text": "Returns within 30 days", "source": "https://x.test/returns"}, {"text": "Free shipping over 50"}],
        "roles": [{"name": "Shopper"}], "flows": [{"name": "Buy", "steps": [{"screen": "Cart"}]}],
        "voices": [{"text": "love the fit finder", "kind": "love"}], "gaps": [{"text": "seller side not seen"}]}}
    items = ev.from_dossier(job)
    by = {(i["kind"], i["text"]): i["standing"] for i in items}
    assert by[("screen", "Cart")] == "observed" and by[("screen", "Wishlist")] == "inferred"
    assert by[("action", "Save for later")] == "observed"
    assert by[("record", "Order")] == "inferred" and by[("role", "Shopper")] == "inferred"
    assert by[("rule", "Returns within 30 days")] == "observed" and by[("rule", "Free shipping over 50")] == "inferred"
    assert by[("flow", "Buy")] == "derived" and by[("gap", "seller side not seen")] == "unknown"
    assert all(i["reference"] == "r1" for i in items)


def test_the_brief_quotes_names_with_their_standing_and_id():
    items, _ = ev.merge([], [_obs("Order", kind="record"), _inf("Order.note")])
    text = ev.brief(items)
    assert "## record (1)" in text and f"[observed] #{items[0]['id']} Order" in text
    assert "[inferred]" in text and "Order.note" in text
    assert ev.counts(items) == {"observed": 1, "derived": 0, "inferred": 1, "unknown": 0}
