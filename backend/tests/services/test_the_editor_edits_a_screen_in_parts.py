"""The Editor tab on a screen written in parts (2026-10-07): the frame and each
part are one tree to select in, an edit lands in the file its element is in,
saving keeps every part — a save that wrote only load and view took the parts
out of the Blueprint and the frame stopped compiling — and history, drafts,
restore and the running app's copy carry the parts too."""
from __future__ import annotations

from services.blueprint.service import BlueprintService
from services.react_editor import files, service
from services.react_editor.adapter import AdapterError, revision_of

LOAD = '''import { list, type PageContext } from "@/sdk/server";
export async function load(ctx: PageContext) {
  return { coupons: await list("Coupon"), campaigns: await list("Campaign") };
}
'''
VIEW = '''"use client";
import CouponsPart from "./parts/coupons";
import CampaignsPart from "./parts/campaigns";

export default function View(props: Props) {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl">Marketing</h1>
      <CouponsPart data={props} />
      <CampaignsPart data={props} />
    </div>
  );
}
'''
COUPONS = '''"use client";
export default function CouponsPart({ data }: { data: Data }) {
  return (
    <section>
      <h2>Coupons</h2>
      <ul>{data.coupons.map((c) => <li key={c.id}>{c.code}</li>)}</ul>
    </section>
  );
}
'''
CAMPAIGNS = '''"use client";
export default function CampaignsPart({ data }: { data: Data }) {
  return <section><h2>Campaigns</h2></section>;
}
'''
PARTS = {"coupons": COUPONS, "campaigns": CAMPAIGNS}


def _project(tmp_path, monkeypatch):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Mozato", domain="food")
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "Marketing", "route": "/marketing", "purpose": "Offers."}]
    svc.doc["pageCode"] = [{"page": "PAGE-001", "load": LOAD, "view": VIEW, "parts": dict(PARTS)}]
    svc.save()
    app = tmp_path / "app"
    (app / "src/app/(dashboard)/marketing").mkdir(parents=True)
    (app / "package.json").write_text("{}")
    checked = []
    monkeypatch.setattr(service, "_check", lambda doc, project, pid, view, load, parts=None:
                        checked.append(dict(parts or {})) or [])
    return service.locate(tmp_path), checked


def _node(model, file, text):
    return next(n for n in model["nodes"].values() if n.get("file") == file and n.get("text") == text)


def test_the_screen_is_one_tree_with_each_part_under_the_element_that_renders_it(tmp_path, monkeypatch):
    project, _ = _project(tmp_path, monkeypatch)
    out = service.open_page(project, "PAGE-001")
    model = out["model"]
    assert out["revision"] == revision_of(VIEW, LOAD, PARTS)
    assert out["source"]["parts"] == PARTS and out["page"]["parts"] == ["campaigns", "coupons"]
    host = next(n for n in model["nodes"].values() if n["type"] == "CouponsPart")
    heading = _node(model, "part:coupons", "Coupons")
    assert heading["id"].startswith("coupons:")
    root = model["nodes"][heading["parent"]]
    assert root["parent"] == host["id"] and root["id"] in host["children"], "the part hangs under its host"
    copy = (tmp_path / "app/src/app/(dashboard)/marketing/parts/coupons.tsx").read_text()
    assert 'data-fid="coupons:r0' in copy, "the running copy's part carries prefixed ids"


def test_an_edit_lands_in_the_file_its_element_is_in(tmp_path, monkeypatch):
    project, checked = _project(tmp_path, monkeypatch)
    model = service.open_page(project, "PAGE-001")["model"]
    heading = _node(model, "part:coupons", "Coupons")
    out = service.apply(project, "PAGE-001", base_revision=revision_of(VIEW, LOAD, PARTS),
                        ops=[{"op": "setText", "id": heading["id"], "text": "Discount codes"}], check=True)
    assert "Discount codes" in out["source"]["parts"]["coupons"]
    assert out["source"]["view"] == VIEW and out["source"]["parts"]["campaigns"] == CAMPAIGNS
    row = service.load_blueprint(project).doc["pageCode"][0]
    assert set(row["parts"]) == {"coupons", "campaigns"}, "saving keeps every part"
    assert "Discount codes" in row["parts"]["coupons"] and checked[-1]["coupons"] == row["parts"]["coupons"]
    frame = _node(out["model"], "view", "Marketing")
    out2 = service.apply(project, "PAGE-001", base_revision=out["revision"],
                         ops=[{"op": "setText", "id": frame["id"], "text": "Promotions"}], check=False)
    assert "Promotions" in out2["source"]["view"] and out2["source"]["parts"] == out["source"]["parts"]


def test_a_change_cannot_span_two_parts():
    try:
        files.split_ops([{"op": "move", "id": "coupons:r0.1", "parentId": "campaigns:r0", "index": 0}])
    except AdapterError as exc:
        assert exc.code == "across-files"
    else:
        raise AssertionError("a move across parts was accepted")
    routed = files.split_ops([{"op": "replaceNode", "id": "coupons:r0.1", "jsx": "<p/>"},
                              {"op": "addImport", "source": "@/components/ui/badge", "names": ["Badge"]}])
    assert set(routed) == {"part:coupons"} and routed["part:coupons"][0]["id"] == "r0.1", \
        "an import goes with the part it is for"


def test_history_drafts_and_restore_carry_the_parts(tmp_path, monkeypatch):
    project, _ = _project(tmp_path, monkeypatch)
    base = revision_of(VIEW, LOAD, PARTS)
    model = service.open_page(project, "PAGE-001")["model"]
    heading = _node(model, "part:campaigns", "Campaigns")
    draft = service.draft_apply(project, "PAGE-001", base_revision=base,
                                ops=[{"op": "setText", "id": heading["id"], "text": "Pushes"}])
    assert draft["dirty"] and "Pushes" in draft["source"]["parts"]["campaigns"]
    assert "Pushes" in (service.open_page(project, "PAGE-001")["source"]["parts"]["campaigns"]), "the draft is what opens"
    saved = service.apply(project, "PAGE-001", base_revision=base, ops=[], source=draft["source"], check=False)
    restored = service.restore(project, "PAGE-001", revision=base, expected=saved["revision"])
    assert restored["source"]["parts"] == PARTS, "restore brings the parts back as they were"
    assert any(e.get("revision") == base for e in service.history(project, "PAGE-001"))
