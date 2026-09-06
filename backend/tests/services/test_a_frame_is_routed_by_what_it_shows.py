"""A frame's route comes from what it shows, not from where it sits in a list.

Fifteen frames of one real file all carried the layer name "Refund & Case
Management Platform". The planner was shown names and node ids and nothing
else, so it handed the frames its entity-shaped routes in order: the Ticket
Queue became /login, Front Desk became /cases, Policy Manager became
/users/new — fourteen of fifteen wrong, and the design's nav items were left
route-less because the pages that should have backed them were filed under
other routes.

Each frame's own heading says what it is. `store.connect` now reads it, with
the shared chrome removed (or every heading would be the brand), records it as
`frames[].shows`, and the slot the planner answers carries it ahead of the
layer name.
"""
import json
from pathlib import Path

import jsonschema

from services.blueprint.page_planner import frame_slots, page_slot_prompt, page_slots
from services.figma import store
from services.figma.reference import DesignReference, ScreenRef
from services.figma.url import FigmaTarget

RAIL = '''<div className="bg-[#110f0c] flex flex-col w-[240px]" data-node-id="1:9">
  <p className="text-[14px]">Criterion</p><p className="text-[11px]">OVERVIEW</p>
  <div data-node-id="1:10" data-name="Button"><p>⬡Dashboard</p></div>
  <div data-node-id="1:11" data-name="Button"><p>⌂Front Desk</p></div>
  <div data-node-id="1:12" data-name="Button"><p>◻Ticket Queue</p></div>
</div>'''


def _screen(nid, heading):
    return f'''
export default function F() {{
  return (<div className="bg-[#f7f3eb] relative size-full" data-node-id="{nid}">
    <div className="flex" data-node-id="{nid}1">{RAIL}
      <div className="flex flex-col" data-node-id="{nid}2">
        <p className="font-['Fraunces:Regular'] text-[28px]">{heading}</p>
        <p className="text-[14px]">body</p></div></div></div>);
}}'''


def _ref():
    return DesignReference(target=FigmaTarget(file_key="aBcD1234EfGh"), source_id="FIGMA-001",
                           screens=[ScreenRef(node_id=n, name="Refund & Case Management Platform", canvas="P",
                                              width=1440, height=900,
                                              structure={"source": "design_context_code", "code": _screen(n, h), "assets": []})
                                    for n, h in (("1:2", "Ticket Queue"), ("1:3", "Front Desk"))])


class _Svc:
    def __init__(self, d): self.doc, self.output_dir = d, "/tmp/x"
    def save(self): pass


def test_connect_records_what_each_frame_shows(tmp_path):
    svc = _Svc({}); svc.output_dir = str(tmp_path)
    record = store.connect(svc, _ref(), treat_as="specification")
    shows = {f["nodeId"]: f.get("shows") for f in record["frames"]}
    assert shows == {"1:2": "Ticket Queue", "1:3": "Front Desk"}


def test_the_heading_is_read_with_the_chrome_removed(tmp_path):
    """Or every frame would 'show' the brand — Criterion — first."""
    svc = _Svc({}); svc.output_dir = str(tmp_path)
    record = store.connect(svc, _ref(), treat_as="specification")
    assert all(f["shows"] != "Criterion" for f in record["frames"])


def test_the_record_satisfies_the_contract(tmp_path):
    contract = json.load(open(Path(__file__).resolve().parents[2] / "contracts" / "blueprint.schema.json"))
    svc = _Svc({}); svc.output_dir = str(tmp_path)
    record = store.connect(svc, _ref(), treat_as="specification")
    v = jsonschema.validators.validator_for(contract)(contract).evolve(
        schema=contract["properties"]["designSources"]["items"])
    assert not list(v.iter_errors(record))


def test_a_slot_is_named_by_what_it_shows():
    slots = frame_slots([{"nodeId": "1:2", "name": "Refund & Case Management Platform", "shows": "Ticket Queue"}])
    assert slots[0]["name"] == "Ticket Queue" and slots[0]["shows"] == "Ticket Queue"
    assert "Ticket Queue" in slots[0]["prompt"] and "Ticket Queue" in slots[0]["pages"][0]["prompt"]


def test_a_frame_without_a_heading_keeps_its_layer_name():
    slots = frame_slots([{"nodeId": "1:2", "name": "Login"}])
    assert slots[0]["name"] == "Login" and "shows" not in slots[0]


def test_the_prompts_forbid_routing_by_position():
    doc = {"application": {"description": "d"}, "data": {"entities": []},
           "designSources": [{"id": "FIGMA-001", "treatAs": "specification",
                              "frames": [{"nodeId": "1:2", "shows": "Ticket Queue"}]}]}
    assert "never by its position" in page_slot_prompt(doc)
    doc["designSources"][0]["treatAs"] = "evidence"
    assert "never by its position" in page_slot_prompt(doc)
    assert page_slots(doc)[0]["shows"] == "Ticket Queue"
