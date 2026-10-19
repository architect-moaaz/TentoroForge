"""A Blueprint application keeps its history in the Blueprint, not in git (its
repository has no commits), so Build history showed only publish records and
no way back (Mark 8 on forge-v3, 2026-10-17). The history now lists every
recorded change and restores any kept version, as a change of its own."""
from __future__ import annotations

from services.blueprint.ids import page_key
from services.blueprint.service import BlueprintService
from services.smith import revert


def _app(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Mark 8", domain="tools")
    s.upsert("pages", {"name": "Calculator", "route": "/", "pattern": "tool", "purpose": "Sums.", "primaryTasks": []},
             natural_key=page_key("/"))
    s.save()
    for name in ("Tax", "Loans"):
        before = s.snapshot()
        s.upsert("pages", {"name": name, "route": f"/{name.lower()}", "pattern": "tool", "purpose": name, "primaryTasks": []},
                 natural_key=page_key(f"/{name.lower()}"))
        s.commit(user_request=f"add a {name.lower()} page", smith_interpretation=f"add /{name.lower()}", before=before)
    return s


def test_every_recorded_change_is_listed_newest_first_with_what_can_be_restored(tmp_path):
    s = _app(tmp_path)
    h = revert.history(s)
    assert h["current"] == 3
    assert [(v["version"], v["request"], v["current"], v["restorable"]) for v in h["versions"]] == [
        (3, "add a loans page", True, False), (2, "add a tax page", False, True)]


def test_a_kept_version_is_restored_as_a_change_of_its_own(tmp_path, monkeypatch):
    s = _app(tmp_path)
    monkeypatch.setattr("services.smith.reproject.everything", lambda svc, root: ["app/src/app/page.tsx"])
    out = revert.restore_to(s, 2)
    assert out["restored"] == 2 and out["version"] == 4
    routes = [p["route"] for p in s.doc["pages"] if p.get("status") != "DEPRECATED"]
    assert routes == ["/", "/tax"]                      # Loans gone: the app as it stood at v2
    last = s.doc["changeHistory"][-1]
    assert last["userRequest"].startswith("restore: back to version 2 (add a tax page)")
    # Nothing is lost: the restore can itself be undone, back to the app with Loans.
    assert revert.history(s)["versions"][0]["undo"] is True
    revert.revert(s)
    assert "/loans" in [p["route"] for p in s.doc["pages"]]
