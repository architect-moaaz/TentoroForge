"""A control is known by the evidence a designer left, not by one layer name.

The transform sent only a layer named exactly `Button` to the action
classifier. On a real dashboard the row action was the text "View →" inside
a `Table Cell`, and on the notifications screen "View Case" sat in a layer
called `Btn`; neither was ever asked about, and both rendered as text that
did nothing. The evidence now counts: a layer named with any spelling of
button, or a label that points somewhere with an arrow, is a candidate. The
classifier still decides — unbound, it stays the text it was.

And "View →" says nothing about what is viewed. The heading above it does,
so the classifier is told which heading a control sits under.
"""
from unittest.mock import patch

from services.jsx_to_schema import _looks_like_a_control, transform_jsx_to_schema

JSX = '''
export default function F() {
  return (
    <div className="relative size-full" data-node-id="1:1">
      <p className="text-[28px]" data-node-id="1:9">Operations Dashboard</p>
      <div className="bg-white border border-[#e8e0cc] flex flex-col" data-node-id="1:10">
        <p className="text-[14px] font-semibold" data-node-id="1:2">Active Cases</p>
        <p className="text-[28px]" data-node-id="1:11">4</p>
        <p className="text-[12px] font-semibold uppercase" data-node-id="1:8">Created</p>
        <div className="absolute border-[#e8e0cc] border-b-2 left-0 top-0 w-[400px]" data-name="Table Row" data-node-id="1:12"><p className="uppercase font-semibold">Case No</p></div>
        <p data-node-id="1:13">✓</p>
        <div className="absolute border-[#f0ebe0] border-b left-0 top-[53px] w-[80px] h-[40px]" data-name="Table Cell" data-node-id="1:3">
          <p className="text-[12px] text-[#c9a84c]" data-node-id="1:4">View →</p>
        </div>
      </div>
      <div className="bg-white border px-[12px]" data-name="Btn" data-node-id="1:5">
        <p className="text-[12px]" data-node-id="1:6">View Case</p>
      </div>
      <p className="text-[12px]" data-node-id="1:7">Across all properties</p>
    </div>
  );
}
'''


def _find(node, node_id):
    if isinstance(node, dict):
        if (node.get("props") or {}).get("_figmaNodeId") == node_id:
            return node
        for c in node.get("children") or []:
            hit = _find(c, node_id)
            if hit:
                return hit
    return None


def _saying(node, text):
    """The node that carries a label or content — a cell wrapping one
    paragraph collapses into a single node, which keeps the wrapper's id."""
    if isinstance(node, dict):
        p = node.get("props") or {}
        if (p.get("label") or p.get("content")) == text:
            return node
        for c in node.get("children") or []:
            hit = _saying(c, text)
            if hit:
                return hit
    return None


def _bind(label, *_a, **_k):
    return {"navigate": "/cases/[id]"} if label.startswith("View") else {}


def test_the_evidence_that_makes_a_candidate():
    assert _looks_like_a_control("Btn", "View Case")
    assert _looks_like_a_control("Table Cell", "View →")
    assert _looks_like_a_control("primary-button", "Save")
    assert not _looks_like_a_control("Table Cell", "CAS-2024-0441")
    assert not _looks_like_a_control("Btn", "")
    assert not _looks_like_a_control("Table", "Case No Type … View →", leaves=54), "an arrow at the end of a whole table is not a control"


def test_a_layer_called_btn_is_a_button():
    with patch("services.jsx_to_schema._classify_button_action_with_llm", _bind):
        node = _find(transform_jsx_to_schema(JSX, {}, canvas=(1387.0, 982.0)), "1:5")
    assert node["type"] == "Button"
    assert node["props"]["label"] == "View Case" and node["props"]["navigate"] == "/cases/[id]"


def test_a_row_action_drawn_as_text_is_a_button_when_it_binds():
    with patch("services.jsx_to_schema._classify_button_action_with_llm", _bind):
        node = _saying(transform_jsx_to_schema(JSX, {}, canvas=(1387.0, 982.0)), "View →")
    assert node["type"] == "Button" and node["props"]["navigate"] == "/cases/[id]"


def test_unbound_it_stays_the_text_it_was():
    with patch("services.jsx_to_schema._classify_button_action_with_llm", lambda *a, **k: {}):
        root = transform_jsx_to_schema(JSX, {}, canvas=(1387.0, 982.0))
    assert _saying(root, "View →")["type"] == "Text"
    assert _saying(root, "View Case")["type"] == "Text", "an unbound button is a caption drawn to look like one"


def test_plain_text_is_never_asked_about():
    seen = []
    with patch("services.jsx_to_schema._classify_button_action_with_llm",
               lambda label, *a, **k: seen.append(label) or {}):
        transform_jsx_to_schema(JSX, {}, canvas=(1387.0, 982.0))
    assert "Across all properties" not in seen
    assert "View →" in seen and "View Case" in seen


def test_the_classifier_is_told_the_card_the_control_sits_in():
    """The table's title is the first text of the card that holds it — a
    14px semi-bold line no size rule would call a heading — and a KPI's
    28px number, which the size rule does call one, is not the context."""
    from services import jsx_to_schema
    jsx_to_schema._ACTION_MEMO.clear()
    seen = {}
    def spy(label, data_name, class_name, heading=""):
        seen[label] = heading; return {}
    with patch("services.jsx_to_schema._classify_button_action_uncached", spy):
        transform_jsx_to_schema(JSX, {}, canvas=(1387.0, 982.0))
    assert seen["View →"] == "Active Cases"


def test_neither_a_column_label_nor_a_big_number_displaces_the_card_title():
    from services import jsx_to_schema
    jsx_to_schema._ACTION_MEMO.clear()
    seen = {}
    def spy(label, data_name, class_name, heading=""):
        seen[label] = heading; return {}
    with patch("services.jsx_to_schema._classify_button_action_uncached", spy):
        transform_jsx_to_schema(JSX, {}, canvas=(1387.0, 982.0))
    assert seen["View →"] == "Active Cases"


def test_outside_any_card_the_pages_heading_is_the_context():
    from services import jsx_to_schema
    jsx_to_schema._ACTION_MEMO.clear()
    seen = {}
    def spy(label, data_name, class_name, heading=""):
        seen[label] = heading; return {}
    with patch("services.jsx_to_schema._classify_button_action_uncached", spy):
        transform_jsx_to_schema(JSX, {}, canvas=(1387.0, 982.0))
    assert seen["View Case"] == "Operations Dashboard"


def test_a_bordered_row_is_not_a_card_and_a_glyph_is_not_a_title():
    """The table's header row and cells carry borders; only a fill makes a
    card. The card's first text may be an icon glyph; its title is the
    first line with a word in it."""
    from services import jsx_to_schema
    jsx_to_schema._ACTION_MEMO.clear()
    seen = {}
    def spy(label, data_name, class_name, heading=""):
        seen[label] = heading; return {}
    with patch("services.jsx_to_schema._classify_button_action_uncached", spy):
        transform_jsx_to_schema(JSX.replace('<p className="text-[14px] font-semibold" data-node-id="1:2">Active Cases</p>',
                                            '<p data-node-id="1:14">◎</p><p className="text-[14px] font-semibold" data-node-id="1:2">Active Cases</p>'),
                                {}, canvas=(1387.0, 982.0))
    assert seen["View →"] == "Active Cases"


def test_a_row_action_keeps_the_place_its_cell_was_drawn_at():
    """Six "View →" buttons piled at the table's top-left when the cell's
    offsets were stripped; on a canvas a positioned cell stays positioned."""
    with patch("services.jsx_to_schema._classify_button_action_with_llm", _bind):
        cn = _saying(transform_jsx_to_schema(JSX, {}, canvas=(1387.0, 982.0)), "View →")["props"]["className"].split()
    assert "absolute" in cn and "top-[53px]" in cn


def test_a_control_drawn_as_plain_text_is_a_quiet_control():
    with patch("services.jsx_to_schema._classify_button_action_with_llm", _bind):
        root = transform_jsx_to_schema(JSX, {}, canvas=(1387.0, 982.0))
    assert _saying(root, "View →")["props"]["variant"] == "ghost"
    assert "variant" not in _saying(root, "View Case")["props"], "a filled button keeps the default"

