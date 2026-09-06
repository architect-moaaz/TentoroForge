"""`font-['Inter:Medium']` names no family; the text fell back to Times.

Dev Mode attaches the style to the family name in the class it writes on
every text node. A family called "Inter:Medium" exists nowhere, so a whole
design drawn in Inter rendered in the browser's default serif while its
`--font-body` token said Inter. The weight already travels separately as
`font-medium`; the family class gets its real name and a generic behind it.
"""
from services.jsx_to_schema import _font_class, transform_jsx_to_schema

JSX = '''
export default function F() {
  return (
    <div className="relative size-full" data-node-id="1:1">
      <p className="font-['Inter:Medium'] font-medium text-[12px]" data-node-id="1:2">OPEN CASES</p>
      <p className="font-['Fraunces:Regular'] text-[28px]" data-node-id="1:3">Operations Dashboard</p>
      <p className="font-['JetBrains_Mono:Regular'] text-[14px]" data-node-id="1:4">CAS-2024-0441</p>
    </div>
  );
}
'''


def _cls(root, node_id):
    if isinstance(root, dict):
        p = root.get("props") or {}
        if p.get("_figmaNodeId") == node_id:
            return p.get("className") or ""
        for c in root.get("children") or []:
            hit = _cls(c, node_id)
            if hit is not None:
                return hit
    return None


def test_the_style_suffix_is_dropped_and_a_generic_added():
    assert _font_class("font-['Inter:Medium']") == "font-['Inter',ui-sans-serif,system-ui,sans-serif]"


def test_a_mono_face_falls_back_to_monospace():
    assert _font_class("font-['JetBrains_Mono:Regular']") == "font-['JetBrains Mono',ui-monospace,monospace]"


def test_other_classes_pass_untouched():
    assert _font_class("font-medium") == "font-medium"
    assert _font_class("text-[12px]") == "text-[12px]"


def test_every_text_node_carries_a_real_family():
    root = transform_jsx_to_schema(JSX, {}, canvas=(1387.0, 982.0))
    assert "font-['Inter',ui-sans-serif,system-ui,sans-serif]" in _cls(root, "1:2")
    assert "font-medium" in _cls(root, "1:2"), "the weight still travels"
    assert "font-['Fraunces',ui-sans-serif,system-ui,sans-serif]" in _cls(root, "1:3")
    assert "Inter:Medium" not in _cls(root, "1:2")
