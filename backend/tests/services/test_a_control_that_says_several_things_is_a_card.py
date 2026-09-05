"""A Button has one label; a clickable frame with several texts is a card.

Designers name a list row "Button" because pressing it opens the detail. Dev
Mode hands over that frame with a title, a status chip, a scope and a version
inside, and the transform consumed all of it into one label. The Policy
Manager's list rendered as

    After-Hours Duty Manager ProtocolActiveAll Brandsv2.1

with the row's layout gone. The rule now: two or more pieces of text make the
element a container that keeps its children and its drawn classes, carrying
the destination — classified from its title — as `navigate` on the container.
When nothing binds, it is a container with no action: what it was on the
drawing. A one-label "Button" is still a Button.
"""
from unittest.mock import patch

from services.jsx_to_schema import transform_jsx_to_schema

CARD = '''
export default function F() {
  return (
    <div className="bg-white relative size-full" data-node-id="1:1">
      <div data-name="Button" className="bg-white border border-[#e8e0cc] rounded-[8px] h-[66px] w-[355px] flex flex-col" data-node-id="1:2">
        <p className="text-[14px]">After-Hours Duty Manager Protocol</p>
        <div className="flex gap-[8px]">
          <p className="text-[11px]">Active</p>
          <p className="text-[11px]">All Brands</p>
          <p className="text-[11px]">v2.1</p>
        </div>
      </div>
      <div data-name="Button" className="bg-[#c9a84c] rounded-[6px]" data-node-id="1:3">
        <p className="text-[13px]">Draft Policy</p>
      </div>
    </div>
  );
}
'''


def _texts(node, out=None):
    out = [] if out is None else out
    if isinstance(node, dict):
        p = node.get("props") or {}
        for k in ("content", "label"):
            if isinstance(p.get(k), str):
                out.append(p[k])
        for c in node.get("children") or []:
            _texts(c, out)
    return out


def _find(node, node_id):
    if isinstance(node, dict):
        if (node.get("props") or {}).get("_figmaNodeId") == node_id:
            return node
        for c in node.get("children") or []:
            hit = _find(c, node_id)
            if hit:
                return hit
    return None


def _bind(label, *_a, **_k):
    return {"navigate": "/policies/[id]"} if "Protocol" in label else \
        {"navigate": "/policies/new"} if "Draft" in label else {}


def test_a_card_keeps_its_texts_apart():
    with patch("services.jsx_to_schema._classify_button_action_with_llm", _bind):
        root = transform_jsx_to_schema(CARD, {}, canvas=(1440.0, 900.0))
    card = _find(root, "1:2")
    assert card["type"] == "Container"
    assert _texts(card) == ["After-Hours Duty Manager Protocol", "Active", "All Brands", "v2.1"]


def test_a_card_carries_its_destination_on_itself():
    with patch("services.jsx_to_schema._classify_button_action_with_llm", _bind):
        root = transform_jsx_to_schema(CARD, {}, canvas=(1440.0, 900.0))
    assert _find(root, "1:2")["props"]["navigate"] == "/policies/[id]"


def test_the_destination_is_classified_from_the_title():
    seen = []
    def spy(label, *a, **k):
        seen.append(label); return _bind(label)
    with patch("services.jsx_to_schema._classify_button_action_with_llm", spy):
        transform_jsx_to_schema(CARD, {}, canvas=(1440.0, 900.0))
    assert "After-Hours Duty Manager Protocol" in seen
    assert not any("Active" in s and "Brands" in s for s in seen), "texts were joined"


def test_a_card_keeps_its_drawn_classes():
    with patch("services.jsx_to_schema._classify_button_action_with_llm", _bind):
        root = transform_jsx_to_schema(CARD, {}, canvas=(1440.0, 900.0))
    cn = _find(root, "1:2")["props"]["className"]
    assert "border-[#e8e0cc]" in cn and "rounded-[8px]" in cn


def test_an_unbound_card_is_a_container_with_no_action():
    with patch("services.jsx_to_schema._classify_button_action_with_llm", lambda *a, **k: {}):
        root = transform_jsx_to_schema(CARD, {}, canvas=(1440.0, 900.0))
    card = _find(root, "1:2")
    assert card["type"] == "Container" and "navigate" not in card["props"]
    assert len(_texts(card)) == 4


def test_a_one_label_button_is_still_a_button():
    with patch("services.jsx_to_schema._classify_button_action_with_llm", _bind):
        root = transform_jsx_to_schema(CARD, {}, canvas=(1440.0, 900.0))
    btn = _find(root, "1:3")
    assert btn["type"] == "Button" and btn["props"]["label"] == "Draft Policy"


def test_the_composed_card_passes_the_validator():
    """The end of it: a Container with `navigate` is legal in the catalog."""
    from services.blueprint.page_planner import load_catalog, validate_props
    with patch("services.jsx_to_schema._classify_button_action_with_llm", _bind):
        root = transform_jsx_to_schema(CARD, {}, canvas=(1440.0, 900.0))
    errors = validate_props({"root": root}, load_catalog())
    assert not [e for e in errors if "navigate" in e or "Container" in e], errors


def test_on_a_fluid_canvas_a_cards_width_is_its_maximum():
    """A card is a container; the drawn width is the most it takes."""
    with patch("services.jsx_to_schema._classify_button_action_with_llm", _bind):
        root = transform_jsx_to_schema(CARD.replace("bg-white relative size-full", "bg-white flex flex-col size-full"), {}, canvas=(1440.0, 900.0))
    cn = _find(root, "1:2")["props"]["className"].split()
    assert "max-w-[355px]" in cn and "w-full" in cn and "w-[355px]" not in cn

