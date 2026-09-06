"""HTML reaches the same PageV2 vocabulary Figma JSX does."""
from __future__ import annotations

from services.html_to_schema import (
    extract_html_asset_urls,
    layout_classes,
    parse_html_tree,
    parse_style,
    tokens_from_html,
    transform_html_to_schema,
)

_LOGIN = """<!doctype html>
<html><head><title>Sign in</title>
<style>
  .row { display: flex; gap: 16px; }
  .card { border-radius: 12px; padding: 24px; background: #FFFFFF; }
</style></head>
<body>
<div class="page" style="display:flex; flex-direction:column; gap: 32px; font-family: 'Inter', sans-serif">
  <h1 class="text-[32px] font-bold" style="color:#1F2937">Welcome back</h1>
  <form class="card">
    <label>Email</label>
    <input type="email" placeholder="you@example.com">
    <input type="password" placeholder="Password">
    <button class="rounded-[8px] bg-[#2563EB] text-[14px]">Sign in</button>
  </form>
  <div class="row">
    <div class="card"><p>Fast</p></div>
    <div class="card"><p>Secure</p></div>
  </div>
  <img src="https://cdn.example.com/assets/hero.png" alt="Hero">
</div>
</body></html>"""


def _types(node, acc=None):
    acc = [] if acc is None else acc
    if isinstance(node, dict):
        if "type" in node:
            acc.append(node["type"])
        for c in node.get("children") or []:
            _types(c, acc)
    return acc


def _find(node, t):
    if isinstance(node, dict):
        if node.get("type") == t:
            return node
        for c in node.get("children") or []:
            hit = _find(c, t)
            if hit:
                return hit
    return None


def test_style_parsing_and_layout_classes():
    assert parse_style("color: #fff; font-size:14px; ") == {"color": "#fff", "fontSize": "14px"}
    assert layout_classes({"display": "flex", "flexDirection": "column", "gap": "16px"}) == ["flex", "flex-col", "gap-[16px]"]
    assert layout_classes({"display": "grid", "gridTemplateColumns": "repeat(3, 1fr)"}) == ["grid", "grid-cols-3"]
    assert layout_classes({"display": "grid", "gridTemplateColumns": "1fr 1fr"}) == ["grid", "grid-cols-2"]
    assert layout_classes({"color": "red"}) == []


def test_parse_html_tree_maps_semantic_tags_onto_the_transformer_vocabulary():
    root, styles = parse_html_tree(_LOGIN)
    assert root.tag == "div" and "flex-col" in root.attrs["className"]
    assert len(styles) == 1
    kids = [c for c in root.children if not isinstance(c, str)]
    h1, form, row, img = kids
    assert h1.attrs["data-name"] == "Heading 1"
    assert h1.children[0].tag == "p" and h1.children[0].children == ["Welcome back"]
    assert form.attrs["data-name"] == "Form"
    names = [c.attrs.get("data-name") for c in form.children if not isinstance(c, str)]
    assert names == ["Primitive.label", "Email Input", "Password Input", "Button"]
    # A stylesheet class became layout utilities on the element that carries it.
    assert "flex" in row.attrs["className"] and "gap-[16px]" in row.attrs["className"]
    assert img.tag == "img" and img.attrs["src"].endswith("hero.png")


def test_transform_html_to_schema_yields_page_v2():
    schema = transform_html_to_schema(_LOGIN, {"https://cdn.example.com/assets/hero.png": "/api/asset/p/figma/abc.png"})
    assert schema["schemaVersion"] == "2.0"
    types = _types(schema["children"][0])
    for expected in ("Stack", "Heading", "Form", "Input", "Button", "Row", "Image"):
        assert expected in types, (expected, types)
    heading = _find(schema["children"][0], "Heading")
    assert heading["props"]["content"] == "Welcome back"
    email = _find(schema["children"][0], "Input")
    assert email["props"]["type"] == "email" and email["props"]["placeholder"] == "you@example.com"
    button = _find(schema["children"][0], "Button")
    assert button["props"]["label"] == "Sign in"
    image = _find(schema["children"][0], "Image")
    assert image["props"]["src"] == "/api/asset/p/figma/abc.png"


def test_assets_and_tokens_measured_from_markup():
    assert extract_html_asset_urls(_LOGIN) == ["https://cdn.example.com/assets/hero.png"]
    t = tokens_from_html(_LOGIN)
    assert "#2563EB" in t.colors and "#1F2937" in t.colors and "#FFFFFF" in t.colors
    assert t.fonts == ("Inter",)
    assert 14.0 in t.font_sizes and 32.0 in t.font_sizes
    assert 8.0 in t.border_radii and 12.0 in t.border_radii
    assert {16.0, 24.0, 32.0} <= set(t.spacings)


def test_scripts_and_head_are_dropped_and_unclosed_tags_tolerated():
    html = "<body><script>alert(1)</script><p>one<p>two</body>"
    schema = transform_html_to_schema(html)
    types = _types(schema["children"][0]) if schema["children"] else []
    assert "alert" not in str(schema)
    assert types.count("Text") == 2
