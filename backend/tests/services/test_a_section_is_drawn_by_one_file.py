"""A section of a screen written in parts is drawn by the file that owns it, and by no other.

The frame and the parts are written apart and do not see each other's files, so the frame drew the Quick Actions panel its Members
summary part also drew, and FitTrackr's dashboard showed it twice (2026-10-26). The copy that is not the owner's is taken out, with no
model call. What is not that is left alone: a repeated button, the page's own title, a heading that is no section's."""
from __future__ import annotations

import shutil

import pytest

from services.blueprint import repeated_sections as rs
from services.blueprint import ui_engineer

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed to read and change the code as a tree")


def section(key, label, placement="main", **more):
    return {"key": key, "label": label, "placement": placement, "shows": "summary", "entity": "ENTITY-001", **more}


PAGE = {"id": "PAGE-001", "name": "Dashboard", "route": "/dashboard", "sections": [
    section("memberSummary", "Membership Overview"),
    section("revenueSummary", "Revenue"),
    section("expiring", "Expiring Memberships"),
    section("quickActions", "Quick Actions", placement="panel"),
]}
DOC = {"pages": [PAGE], "workflows": []}

# The panel the frame draws a second time, in its side column, beside a box that is its own (After a reminder).
FRAME = '''"use client";
import { MembersummaryPart } from "./parts/membersummary";
import { RevenuesummaryPart } from "./parts/revenuesummary";
import { ExpiringPart } from "./parts/expiring";

export default function View(props: { data: unknown }) {
  return (
    <div>
      <h1 className="text-4xl">Dashboard</h1>
      <button>Add Member</button>
      <div className="grid">
        <div>
          <MembersummaryPart data={props} />
          <RevenuesummaryPart data={props} />
          <ExpiringPart data={props} />
        </div>
        <aside>
          <div className="bg-muted p-3">
            <h3>Quick Actions</h3>
            <div><button>Add Member</button><button>Record Payment</button></div>
          </div>
          <div className="bg-muted p-3">
            <h3>After a reminder</h3>
            <p>Check the reports.</p>
          </div>
        </aside>
      </div>
    </div>
  );
}
'''

OVERVIEW = '''"use client";
export function MembersummaryPart(_props: { data: unknown }) {
  return (
    <div className="grid">
      <div className="card">
        <h2>Membership Overview</h2>
        <p>Total members</p>
      </div>
      <div className="rounded-lg">
        <h2>Quick Actions</h2>
        <button>Add Member</button>
      </div>
    </div>
  );
}
'''

REVENUE = '''"use client";
export function RevenuesummaryPart(_props: { data: unknown }) {
  return (
    <div className="card">
      <h2>Revenue</h2>
      <table><thead><tr><th>Quick Actions</th></tr></thead></table>
      <button>Add Member</button>
    </div>
  );
}
'''

EXPIRING = '''"use client";
export function ExpiringPart(_props: { data: unknown }) {
  return <div className="card"><h2>Expiring Memberships</h2></div>;
}
'''

PARTS = {"membersummary": OVERVIEW, "revenuesummary": REVENUE, "expiring": EXPIRING}


def run(view=FRAME, parts=None, doc=DOC, page=PAGE):
    return rs.drop_repeated_sections(doc, page, view, dict(PARTS if parts is None else parts))


def test_the_owner_keeps_the_section_and_the_frames_copy_is_taken_out():
    view, parts, notes = run()
    assert "Quick Actions" not in view
    assert "Quick Actions" in parts["membersummary"], "the part that owns the panel still draws it"
    assert len(notes) == 1 and "view.tsx" in notes[0] and "membersummary" in notes[0]


def test_what_is_not_a_repeated_section_is_left_exactly_as_written():
    view, parts, _ = run()
    assert "After a reminder" in view, "another box in the same column stays"
    assert "<h1 className=\"text-4xl\">Dashboard</h1>" in view, "the page's own title stays"
    assert view.count("Add Member") == 1, "the button in the header stays, and so does any button of the same name elsewhere"
    assert "<MembersummaryPart" in view and "<RevenuesummaryPart" in view and "<ExpiringPart" in view
    assert parts["revenuesummary"] == REVENUE, "a table header with the same words is no section's heading"
    assert parts["expiring"] == EXPIRING


def test_the_changed_code_is_still_code():
    from services.react_editor import adapter
    view, parts, _ = run()
    for code in (view, *parts.values()):
        assert adapter.model(code)["ok"]


def test_a_part_that_draws_another_parts_section_loses_that_copy():
    stray = OVERVIEW.replace('<div className="rounded-lg">\n        <h2>Quick Actions</h2>\n        <button>Add Member</button>\n      </div>',
                             '<div className="rounded-lg">\n        <h2>Expiring Memberships</h2>\n        <button>Open</button>\n      </div>')
    assert "Expiring Memberships" in stray
    _, parts, notes = run(parts={"membersummary": stray, "revenuesummary": REVENUE, "expiring": EXPIRING})
    assert "Expiring Memberships" not in parts["membersummary"] and "Expiring Memberships" in parts["expiring"]
    assert any("parts/membersummary.tsx" in n for n in notes)


def test_a_screen_that_is_not_written_in_parts_is_not_touched():
    small = {"id": "PAGE-002", "route": "/x", "sections": [section("a", "Quick Actions")]}
    view, parts, notes = run(view=FRAME, parts={}, doc={"pages": [small]}, page=small)
    assert (view, parts, notes) == (FRAME, {}, [])


def test_a_box_that_places_parts_or_holds_two_sections_is_not_taken_out():
    wrapper = FRAME.replace('<h3>Quick Actions</h3>\n            <div><button>Add Member</button><button>Record Payment</button></div>',
                            '<h3>Quick Actions</h3>\n            <ExpiringPart data={props} />')
    assert "<ExpiringPart data={props} />\n          </div>" in wrapper or wrapper != FRAME
    view, _, notes = run(view=wrapper)
    assert "Quick Actions" in view and notes == []
    two = FRAME.replace('<h3>After a reminder</h3>', '<h3>Revenue</h3>').replace(
        '<div className="bg-muted p-3">\n            <h3>Quick Actions</h3>', '<div className="bg-muted p-3">\n            <h3>Quick Actions</h3>\n            <h4>Expiring Memberships</h4>')
    view, _, notes = run(view=two)
    assert "Quick Actions" in view


def test_a_label_two_parts_both_own_is_nobodys_trespass():
    twice = {**PAGE, "sections": [*PAGE["sections"], section("quickActionsAgain", "Quick Actions", placement="panel", opensFrom="revenueSummary")]}
    view, _, notes = run(doc={"pages": [twice], "workflows": []}, page=twice)
    assert "Quick Actions" in view and notes == []


def test_the_page_writer_runs_it_before_the_screen_is_compiled():
    source = open(ui_engineer.__file__, encoding="utf-8").read()
    assert source.count("drop_repeated_sections(") >= 2, "both the split path and the edit path call it"
