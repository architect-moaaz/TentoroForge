"""What a process wrote is read back where a person would look for it.

"Add a child" passed every check — the insert ran, the row was there — and
"My Children" showed none; testers added the same child six times (forge-v3,
2026-09-27). After a process passes its trial, each record it created or
changed is looked for, as the same person, on the pages that show it.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from services.blueprint import round_trips as rt
from services.smith import trials

DOC = {
    "roles": [{"id": "ROLE-001", "name": "Admin"}, {"id": "ROLE-002", "name": "Parent"}],
    "data": {"entities": [{"id": "ENTITY-001", "name": "Child", "table": "children", "labelField": "name",
                           "fields": [{"name": "id", "type": "uuid"}, {"name": "name", "type": "string"},
                                      {"name": "dateOfBirth", "type": "date"}]}]},
    "pages": [
        {"id": "PAGE-001", "route": "/children", "users": ["ROLE-002"], "data": {"primaryEntity": "ENTITY-001"}},
        {"id": "PAGE-002", "route": "/children/[id]", "users": ["ROLE-002"], "data": {"primaryEntity": "ENTITY-001"}},
        {"id": "PAGE-003", "route": "/children/new", "users": ["ROLE-002"], "data": {"primaryEntity": "ENTITY-001"}},
        {"id": "PAGE-004", "route": "/children/[id]/edit", "users": ["ROLE-002"], "data": {"primaryEntity": "ENTITY-001"}},
        {"id": "PAGE-005", "route": "/admin/children", "users": ["ROLE-001"], "data": {"primaryEntity": "ENTITY-001"}},
    ],
}
ROW = json.dumps({"id": "c-1", "patient_id": "p-1", "name": "Trial Kid", "date_of_birth": "2024-05-01"})


class _Bench:
    output_dir = "/tmp/x"

    def __init__(self, before, after, said=()):
        self.last_written = (before, after)
        self._said = [[]] + [list(said)]          # nothing before the read-back, `said` during it

    def app(self):
        return SimpleNamespace(base="http://app")

    def server_said(self):
        return self._said.pop(0) if self._said else []


@pytest.fixture()
def pages(monkeypatch):
    """What each route serves: {route: (status, html)}; no browser behind it."""
    served: dict[str, tuple[int, str]] = {}
    asked: list[str] = []

    def http(app, method, path, body, jar):
        asked.append(path)
        status, body_html = served.get(path, (404, "<h1>Not found</h1>"))
        return status, "", body_html
    monkeypatch.setattr(trials, "_http", http)
    monkeypatch.setattr(trials, "_session", lambda app, doc, ref: (f"{ref} (preview)", []))
    monkeypatch.setattr("services.blueprint.page_review._query", lambda app, sql: [["3"]])
    monkeypatch.setattr("services.blueprint.page_review.run_shots",
                        lambda app, entries, out, **k: [{"text": "", "status": 200}])
    return SimpleNamespace(served=served, asked=asked)


def test_what_a_run_wrote_is_read_from_its_snapshots():
    out = rt.written({"children": set(), "big": 900}, {"children": {ROW}, "big": 901})
    assert out == {"children": {"added": [json.loads(ROW)], "removed": []}}


def test_a_record_is_known_by_its_label():
    entity = DOC["data"]["entities"][0]
    assert rt.label_of(entity, json.loads(ROW)) == "Trial Kid"
    assert rt.label_of(entity, {"id": "c-2", "name": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d"}) == ""


def test_the_pages_looked_at_are_the_ones_that_person_opens():
    entity = DOC["data"]["entities"][0]
    assert rt.pages_for(DOC, entity, "Parent") == (["/children"], ["/children/[id]"])
    assert rt.pages_for(DOC, entity, "Admin") == (["/admin/children"], [])


def test_a_saved_record_that_is_seen_is_no_problem(pages):
    pages.served["/children/c-1"] = (200, "<main><h1>Trial Kid</h1><script>x</script></main>")
    pages.served["/children"] = (200, "<ul><li>Trial Kid &middot; 2 yrs</li></ul>")
    assert rt.read_back(_Bench({"children": set()}, {"children": {ROW}}), DOC, "Parent") == []
    assert pages.asked == ["/children/c-1", "/children"]


def test_a_saved_record_nobody_can_see_is_the_problem_add_child_had(pages):
    pages.served["/children/c-1"] = (404, "<h1>This page could not be found</h1>")
    pages.served["/children"] = (200, "<p>No children yet. Add a child to get started.</p>")
    said = ["[forge:swallowed] list Child failed: Unknown entity: Child"]
    problems = rt.read_back(_Bench({"children": set()}, {"children": {ROW}}, said), DOC, "Parent")
    assert any('Child "Trial Kid" was written, but its page /children/c-1' in p and "HTTP 404" in p for p in problems)
    assert any("/children as Parent (preview) does not list it" in p and "No children yet" in p for p in problems)
    assert any("Unknown entity: Child" in p for p in problems)


def test_a_deleted_record_must_be_gone(pages):
    pages.served["/children/c-1"] = (200, "<h1>Trial Kid</h1>")
    problems = rt.read_back(_Bench({"children": {ROW}}, {"children": set()}), DOC, "Parent")
    assert problems == ['Child "Trial Kid" was deleted, but /children/c-1 as Parent (preview) still shows it.']


def test_a_long_list_is_not_held_to_showing_the_new_row(pages, monkeypatch):
    monkeypatch.setattr("services.blueprint.page_review._query", lambda app, sql: [[str(rt.LIST_HOLDS + 5)]])
    pages.served["/children/c-1"] = (200, "<h1>Trial Kid</h1>")
    assert rt.read_back(_Bench({"children": set()}, {"children": {ROW}}), DOC, "Parent") == []
    assert pages.asked == ["/children/c-1"]


def test_a_page_that_draws_its_data_after_loading_is_read_in_a_browser(pages, monkeypatch):
    pages.served["/children/c-1"] = (200, "<div id=root></div>")
    pages.served["/children"] = (200, "<div id=root></div>")
    monkeypatch.setattr("services.blueprint.page_review.run_shots",
                        lambda app, entries, out, **k: [{"text": "My Children Trial Kid", "status": 200}])
    assert rt.read_back(_Bench({"children": set()}, {"children": {ROW}}), DOC, "Parent") == []


def test_a_process_whose_record_cannot_be_seen_goes_to_smith(tmp_path, monkeypatch, pages):
    from services.blueprint import process_trials as pt
    from tests.services.test_every_process_runs_through import DOC as FLOWS_DOC, OK, _Svc, _client, _setup

    doc = {**FLOWS_DOC, "roles": DOC["roles"], "data": DOC["data"], "pages": DOC["pages"]}
    _setup(tmp_path, monkeypatch, {"FLOW-001": [OK] * 3, "FLOW-005": [OK] * 3})

    class Bench(_Bench):
        def __init__(self, _out):
            super().__init__({"children": set()}, {"children": {ROW}})

        def close(self):
            pass
    asks = []

    def smith(project_id, output_dir, message, *, max_steps, unattended):
        asks.append(message)
        pages.served["/children/c-1"] = (200, "<h1>Trial Kid</h1>")
        pages.served["/children"] = (200, "<li>Trial Kid</li>")
        return {"answer": "Registered the Child alias.", "edited_paths": ["app/src/lib/entity-aliases.ts"]}

    out = pt.prove_processes(_Svc(tmp_path, doc), str(tmp_path), client=_client([]), bench_factory=Bench,
                             run_turn=smith)
    assert asks and "looking for it as the person who ran it" in asks[0] and "Trial Kid" in asks[0]
    assert not out["left"] and out["fixed"]
