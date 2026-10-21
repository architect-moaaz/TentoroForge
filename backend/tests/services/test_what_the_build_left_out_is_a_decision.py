"""The product model's review offered "5 things such products have are not in
the model yet — ask for them, or tell me to leave them out", and the person
pressed Build. Nothing was recorded, so the domain score after hand-over
flagged the five as missing and the fix loop spent its minutes adding
processes to a calculator (Mark 8, cxz95dd1, 2026-10-16). Building past the
offer IS the answer: at the build, every open reference item is declined
with that reason, and the checks hold the app to the model that was approved."""
from __future__ import annotations

from types import SimpleNamespace

from services.blueprint.domain_score import deterministic
from services.blueprint.reference_coverage import UNASKED_REASON, coverage, decline_unasked

DOC = {
    "domainReference": {
        "screens": [{"name": "Calculator", "kind": "tool"}],
        "processes": [{"name": "Perform Calculation", "purpose": "evaluate the expression"},
                      {"name": "Clear Entry", "purpose": "clear the current entry"}],
        "declined": [{"kind": "process", "name": "Clear Entry", "reason": "the person said no", "by": "owner"}],
    },
    "pages": [{"id": "PAGE-001", "name": "Calculator", "route": "/", "pattern": "tool"}],
    "workflows": [],
}


def _svc(doc):
    saved = []
    return SimpleNamespace(doc=doc, save=lambda: saved.append(True)), saved


def test_building_past_the_offer_declines_what_was_offered_and_not_asked_for():
    svc, saved = _svc({**DOC, "domainReference": {**DOC["domainReference"], "declined": list(DOC["domainReference"]["declined"])}})
    before = {c.name: (c.covered_by, c.declined is not None) for c in coverage(svc.doc, ("screen", "process"))}
    assert before == {"Calculator": ("PAGE-001", False), "Perform Calculation": (None, False), "Clear Entry": (None, True)}

    added = decline_unasked(svc, by="build")
    assert [(d["kind"], d["name"], d["by"]) for d in added] == [("process", "Perform Calculation", "build")]
    assert added[0]["reason"] == UNASKED_REASON and saved == [True]
    # The person's own decline stands untouched; a covered item is never declined.
    declined = {d["name"]: d["reason"] for d in svc.doc["domainReference"]["declined"]}
    assert declined["Clear Entry"] == "the person said no" and "Calculator" not in declined

    # The score after hand-over has nothing red for them any more.
    green, red = deterministic(svc.doc)
    assert [g["label"] for g in green] == ["Calculator"] and red == []

    # Done again — a rebuild — it declines nothing more and saves nothing.
    assert decline_unasked(svc, by="build") == [] and saved == [True]


def test_an_app_that_covers_its_reference_declines_nothing():
    svc, saved = _svc({"domainReference": {"screens": [{"name": "Calculator", "kind": "tool"}]},
                       "pages": [{"id": "PAGE-001", "name": "Calculator", "route": "/", "pattern": "tool"}]})
    assert decline_unasked(svc) == [] and saved == []
