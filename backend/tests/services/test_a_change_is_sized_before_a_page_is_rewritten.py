"""A whole-page rewrite is the biggest tool in the catalogue, and "change the
background to white" reached it — seventeen minutes for one class (Mark 8,
cxz95dd1, 2026-10-16). The first rewrite in a turn that gives no `because`
is asked, once, to size the change; the reason it then gives is what the
person reads in the status line, beside the step."""
from __future__ import annotations

from services.smith.loop import Observation
from services.smith.writes import WRITES
from services.smith4.turn import SIZE_FIRST, SIZED, _NOT_RUN, size_first, step_line


def test_a_rewrite_without_a_reason_is_asked_to_size_the_change_once():
    held = size_first("write_page_code", {"route": "/", "brief": "make the background white"}, [])
    assert held is not None and held.status == "error" and held.said == SIZE_FIRST
    assert "`edit_file`" in SIZE_FIRST and "`because`" in SIZE_FIRST
    # Heard once, the same call runs: the rule is a question, not a gate.
    assert size_first("write_page_code", {"route": "/"}, [held]) is None
    # A reason lets it through at once; an edit is never asked.
    assert size_first("write_page_code", {"route": "/", "because": "the keypad grid is replaced by a list"}, []) is None
    assert size_first("edit_file", {"path": "src/app/_root/view.tsx"}, []) is None
    assert SIZED == frozenset({"write_page_code", "rewrite_pages"})
    assert SIZE_FIRST in _NOT_RUN   # asking again after it is not a repeat


def test_the_catalogue_asks_the_rewrites_for_the_reason():
    by_name = {n: (d, a) for n, d, a in WRITES}
    for name in ("write_page_code", "rewrite_pages"):
        said, args = by_name[name]
        assert args.get("because") == "string", name
        assert "why an edit" in said and "sent back to size the change" in said, name
    assert "because" not in by_name["edit_file"][1]


def test_the_step_line_names_the_reason_for_a_change():
    assert step_line(6, "write_page_code", {"route": "/", "because": "the keypad layout changes to a grid"}) \
        == "step 6: write_page_code / — the keypad layout changes to a grid"
    assert step_line(4, "edit_file", {"path": "src/app/_root/view.tsx", "why": "make the background white"}) \
        == "step 4: edit_file src/app/_root/view.tsx — make the background white"
    # Reads and tries say what they are about, as before.
    assert step_line(7, "open_page", {"route": "/", "as": "Admin"}) == "step 7: open_page / as Admin"
    # A long reason is cut, never a wall of text in a status line.
    assert len(step_line(1, "write_page_code", {"route": "/", "because": "x" * 500})) < 200
