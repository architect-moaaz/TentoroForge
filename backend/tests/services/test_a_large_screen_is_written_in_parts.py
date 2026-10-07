"""A large screen is written in parts, cut along the planner's sections
(2026-10-07): one reply has a ceiling, and a screen holding five tables with
their dialogs is five of yesterday's pages in one file. The frame (load.ts +
view.tsx) and each part (parts/<key>.tsx) are written, compiled and changed on
their own; a failure goes back to the file it is in."""
import copy
import json

import pytest

from services.blueprint import ui_engineer
from services.blueprint.app_sdk import code_page_files, page_code_text
from services.blueprint.screen_parts import frame_workflows, screen_parts

PAGE = {"id": "PAGE-001", "name": "Marketing", "route": "/ops/marketing", "pattern": "master_detail",
        "access": "authenticated", "data": {"primaryEntity": "ENTITY-001"},
        "sections": [
            {"key": "coupons", "label": "Coupons", "entity": "ENTITY-001", "placement": "tab",
             "addsHere": True, "actions": ["Pause coupon"]},
            {"key": "coupon", "label": "Coupon", "entity": "ENTITY-001", "shows": "record", "placement": "panel",
             "opensFrom": "coupons", "param": "coupon"},
            {"key": "campaigns", "label": "Campaigns", "entity": "ENTITY-002", "placement": "tab"},
            {"key": "Notification templates", "label": "Templates", "entity": "ENTITY-003", "placement": "tab"},
            {"key": "new-template", "label": "New template", "entity": "ENTITY-003", "placement": "dialog"},
        ]}
DOC = {
    "application": {"id": "m", "name": "Mozato"},
    "data": {"entities": [{"id": "ENTITY-001", "name": "Coupon", "fields": []},
                          {"id": "ENTITY-002", "name": "Campaign", "fields": []},
                          {"id": "ENTITY-003", "name": "NotificationTemplate", "fields": []}]},
    "pages": [PAGE],
    "workflows": [
        {"id": "FLOW-001", "name": "Create Coupon", "trigger": {"kind": "manual"}, "launchedFrom": ["PAGE-001"],
         "steps": [{"key": "i", "entity": "ENTITY-001", "config": {"actionType": "db_insert"}}]},
        {"id": "FLOW-002", "name": "Pause Coupon", "trigger": {"kind": "manual"}, "launchedFrom": ["PAGE-001"],
         "steps": [{"key": "u", "entity": "ENTITY-001", "config": {"actionType": "db_update"}}]},
        {"id": "FLOW-003", "name": "Launch Campaign", "trigger": {"kind": "manual"}, "launchedFrom": ["PAGE-001"],
         "steps": [{"key": "u", "entity": "ENTITY-002", "config": {"actionType": "db_update"}}]},
        {"id": "FLOW-004", "name": "Export Everything", "trigger": {"kind": "manual"}, "launchedFrom": ["PAGE-001"],
         "steps": []},
    ],
}


def test_the_cut_follows_the_sections():
    parts = {p["key"]: p for p in screen_parts(DOC, PAGE)}
    assert list(parts) == ["coupons", "campaigns", "notification-templates"]
    assert [s["key"] for s in parts["coupons"]["sections"]] == ["coupons", "coupon"], "a panel goes with what opens it"
    assert [s["key"] for s in parts["notification-templates"]["sections"]][-1] == "new-template", \
        "a dialog goes with the section of its records"
    assert parts["coupons"]["component"] == "CouponsPart"


def test_each_workflow_is_run_by_the_part_it_belongs_to():
    parts = {p["key"]: p for p in screen_parts(DOC, PAGE)}
    assert parts["coupons"]["workflows"] == ["FLOW-001", "FLOW-002"], "the add, and the action it names"
    assert parts["campaigns"]["workflows"] == ["FLOW-003"], "the records it writes"
    assert frame_workflows(DOC, PAGE, list(parts.values())) == ["FLOW-004"], "nobody's: the frame's"


def test_a_small_page_is_one_file():
    small = {**PAGE, "sections": PAGE["sections"][:2]}
    assert screen_parts(DOC, small) == []


def test_the_app_gets_each_part_beside_the_frame():
    row = {"page": "PAGE-001", "load": "export async function load() {}", "view": "x",
           "parts": {"coupons": "c", "campaigns": "d"}}
    files = code_page_files(DOC, row)
    base = next(r for r in files if r.endswith("/view.tsx"))[: -len("/view.tsx")]
    assert files[f"{base}/parts/coupons.tsx"] == "c" and files[f"{base}/parts/campaigns.tsx"] == "d"
    assert "c" in page_code_text(row) and "d" in page_code_text(row), "checks read the parts too"


def test_an_edit_can_change_one_part():
    current = {"load": "L", "view": "V", "parts": {"coupons": "<Table/>", "campaigns": "<List/>"}}
    files = ui_engineer.apply_edits(current, [{"file": "part:coupons", "find": "<Table/>", "replace": "<Table sortable/>"}])
    assert files["part:coupons"] == "<Table sortable/>" and files["part:campaigns"] == "<List/>"
    schema = ui_engineer.edit_schema(current["parts"])
    assert "part:coupons" in schema["properties"]["edits"]["items"]["properties"]["file"]["enum"]
    assert ui_engineer.edit_schema({}) is ui_engineer.PAGE_EDIT_SCHEMA


class Scripted:
    """A model that writes the frame and the parts as asked — and leaves the
    pause action out of the coupons part the first time."""
    def __init__(self):
        self.asked = []
        self.coupon_rounds = 0

    def __call__(self, *, system, user, schema):
        self.asked.append(user)
        if "Decide how to build this page" in user:
            return json.dumps({"state": "a marketing desk", "sections": [], "behaviours": []})
        if user.startswith("Write this SCREEN"):
            imports = "".join(f'import {c} from "./parts/{k}";\n' for k, c in
                              (("coupons", "CouponsPart"), ("campaigns", "CampaignsPart"),
                               ("notification-templates", "NotificationTemplatesPart")))
            return json.dumps({"rationale": "frame", "load": "export async function load() { return {}; }",
                               "view": '"use client";\n' + imports + "export default function View() { workflows.exportEverything; }"})
        key = user.split("parts/", 1)[1].split(".tsx", 1)[0]
        runs = {"coupons": "workflows.createCoupon", "campaigns": "workflows.launchCampaign",
                "notification-templates": ""}[key]
        if key == "coupons":
            self.coupon_rounds += 1
            if self.coupon_rounds > 1:
                runs += " workflows.pauseCoupon"
        return json.dumps({"rationale": key, "code": f'"use client";\nexport default function P() {{ {runs} }}'})


def test_the_screen_is_written_as_a_frame_and_its_parts(monkeypatch, tmp_path):
    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: [])
    monkeypatch.setattr(ui_engineer, "system_prompt", lambda doc: "SYSTEM")
    model = Scripted()
    body, _ = ui_engineer.compose_page(copy.deepcopy(DOC), PAGE, tmp_path, model)
    assert set(body["parts"]) == {"coupons", "campaigns", "notification-templates"}
    assert "workflows.pauseCoupon" in body["parts"]["coupons"], "the missing action went back to its part"
    frame = [u for u in model.asked if u.startswith("Write this SCREEN")]
    parts = [u for u in model.asked if u.startswith("Write ONE PART")]
    assert frame and "Do NOT write the parts' contents" in frame[0] and "workflows.exportEverything" in frame[0]
    assert len(parts) == 4, "three parts, and the coupons part once more for what it missed"
    assert "This part runs: workflows.createCoupon, workflows.pauseCoupon" in next(u for u in parts if "parts/coupons" in u)


def test_a_part_the_screen_no_longer_has_leaves_the_app(tmp_path):
    from services.blueprint.app_sdk import project_code_pages
    doc = copy.deepcopy(DOC)
    doc["pageCode"] = [{"page": "PAGE-001", "load": "L", "view": "V", "parts": {"coupons": "c", "campaigns": "d"}}]
    project_code_pages(doc, tmp_path)
    parts_dir = next(tmp_path.rglob("parts"))
    assert sorted(p.name for p in parts_dir.glob("*.tsx")) == ["campaigns.tsx", "coupons.tsx"]
    doc["pageCode"][0]["parts"] = {"coupons": "c"}
    project_code_pages(doc, tmp_path)
    assert sorted(p.name for p in parts_dir.glob("*.tsx")) == ["coupons.tsx"]
