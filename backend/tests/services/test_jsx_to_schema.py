import pathlib
import pytest
from services.jsx_to_schema import parse_jsx_tree, JSXElement


# ── Basics ──

def test_parses_simple_div():
    src = '<div className="flex">hello</div>'
    tree = parse_jsx_tree(src)
    assert tree.tag == "div"
    assert tree.attrs["className"] == "flex"
    assert tree.children == ["hello"]


def test_parses_self_closing():
    src = '<img src="x" alt="y" />'
    tree = parse_jsx_tree(src)
    assert tree.tag == "img"
    assert tree.attrs == {"src": "x", "alt": "y"}
    assert tree.children == []


def test_parses_nested_elements():
    src = '<div><p>hi</p><img src="x" /></div>'
    tree = parse_jsx_tree(src)
    assert tree.tag == "div"
    assert len(tree.children) == 2
    assert isinstance(tree.children[0], JSXElement) and tree.children[0].tag == "p"
    assert isinstance(tree.children[1], JSXElement) and tree.children[1].tag == "img"


def test_parses_text_around_children():
    """JSX can have text before/after child elements."""
    src = '<div>before<p>x</p>after</div>'
    tree = parse_jsx_tree(src)
    assert tree.children[0] == "before"
    assert tree.children[1].tag == "p"
    assert tree.children[2] == "after"


# ── Attributes ──

def test_parses_data_attrs():
    src = '<div data-node-id="1:2" data-name="Login">x</div>'
    tree = parse_jsx_tree(src)
    assert tree.attrs["data-node-id"] == "1:2"
    assert tree.attrs["data-name"] == "Login"


def test_parses_style_object():
    src = '<div style={{ backgroundColor: "red", color: "white" }}>x</div>'
    tree = parse_jsx_tree(src)
    assert isinstance(tree.attrs["style"], dict)
    assert tree.attrs["style"]["backgroundColor"] == "red"
    assert tree.attrs["style"]["color"] == "white"


def test_parses_style_with_complex_value():
    """linear-gradient strings have parens and commas — must not break parse."""
    src = '<div style={{ backgroundImage: "linear-gradient(146deg, rgb(239,246,255) 0%, rgb(238,242,255) 100%)" }}>x</div>'
    tree = parse_jsx_tree(src)
    assert "linear-gradient" in tree.attrs["style"]["backgroundImage"]
    assert "146deg" in tree.attrs["style"]["backgroundImage"]


def test_parses_multiple_attributes():
    src = '<div className="a" style={{ color: "red" }} data-name="x">hi</div>'
    tree = parse_jsx_tree(src)
    assert tree.attrs["className"] == "a"
    assert tree.attrs["style"]["color"] == "red"
    assert tree.attrs["data-name"] == "x"


# ── src interpolation against const declarations ──

def test_parses_src_interpolation():
    src = '''
    const imgLogo = "https://cdn/abc.png";
    function App() { return <img src={imgLogo} alt="" />; }
    '''
    tree = parse_jsx_tree(src)
    img = tree.find_descendant(lambda n: hasattr(n, "tag") and n.tag == "img")
    assert img is not None
    assert img.attrs["src"] == "https://cdn/abc.png"


def test_multiple_const_declarations():
    src = '''
    const imgA = "https://cdn/a.png";
    const imgB = "https://cdn/b.png";
    function App() {
      return (<div><img src={imgA} /><img src={imgB} /></div>);
    }
    '''
    tree = parse_jsx_tree(src)
    imgs = []
    def collect(n):
        if isinstance(n, JSXElement):
            if n.tag == "img": imgs.append(n)
            for c in n.children: collect(c)
    collect(tree)
    assert len(imgs) == 2
    assert imgs[0].attrs["src"] == "https://cdn/a.png"
    assert imgs[1].attrs["src"] == "https://cdn/b.png"


def test_unresolved_var_kept_as_marker():
    """A {var} reference with no matching const should stay as something
    recognisable so downstream transformer can warn. Empty string OK."""
    src = '<img src={imgMissing} />'
    tree = parse_jsx_tree(src)
    # Either empty, or the original `{imgMissing}` string — both acceptable
    src_val = tree.attrs.get("src", "")
    assert src_val == "" or src_val.startswith("{") or src_val == "imgMissing"


# ── Template literal contents ──

def test_template_literal_in_text():
    """JSX text can be a template literal: {`Social Intent Detection & `}"""
    src = '<p>{`Social Intent Detection & `}</p>'
    tree = parse_jsx_tree(src)
    assert isinstance(tree.children[0], str)
    assert "Social Intent Detection" in tree.children[0]


# ── Real-world fixture ──

FIXTURE = pathlib.Path(__file__).parent.parent / "fixtures" / "figma" / "commitbiz_login_design_context.tsx"


def test_parses_full_commitbiz_fixture():
    src = FIXTURE.read_text()
    tree = parse_jsx_tree(src)
    assert tree.tag == "div"
    # Root has data-node-id="1:2" data-name="Commitbiz_intentai_login"
    assert tree.attrs.get("data-node-id") == "1:2"
    assert tree.attrs.get("data-name") == "Commitbiz_intentai_login"
    # Background gradient should be in style
    assert "linear-gradient" in (tree.attrs.get("style") or {}).get("backgroundImage", "")
    # At least one img descendant with a resolved src
    img = tree.find_descendant(lambda n: hasattr(n, "tag") and n.tag == "img")
    assert img is not None
    assert img.attrs["src"].startswith("https://www.figma.com/api/mcp/asset/")


def test_fixture_descendant_count():
    """The fixture has many elements; ensure the parser doesn't lose them."""
    src = FIXTURE.read_text()
    tree = parse_jsx_tree(src)
    count = [0]
    def walk(n):
        count[0] += 1
        if isinstance(n, JSXElement):
            for c in n.children:
                if isinstance(c, JSXElement): walk(c)
    walk(tree)
    # Eyeballing the fixture: well over 30 elements
    assert count[0] >= 30


def test_find_descendant_button():
    """The fixture has a Button at data-node-id 1:72. Verify we can find it."""
    src = FIXTURE.read_text()
    tree = parse_jsx_tree(src)
    button = tree.find_descendant(
        lambda n: hasattr(n, "tag") and n.attrs.get("data-name") == "Button"
    )
    assert button is not None
    assert button.attrs.get("data-node-id") == "1:72"


def test_find_descendant_sign_in_text():
    """Inside the Button there should be a <p>Sign in</p>."""
    src = FIXTURE.read_text()
    tree = parse_jsx_tree(src)
    button = tree.find_descendant(lambda n: hasattr(n, "tag") and n.attrs.get("data-name") == "Button")
    p = button.find_descendant(lambda n: hasattr(n, "tag") and n.tag == "p")
    assert p is not None
    # Concatenate children text
    text = "".join(c for c in p.children if isinstance(c, str))
    assert "Sign in" in text


# =============================================================================
# A.2 — transform_jsx_to_schema tests
# =============================================================================

from services.jsx_to_schema import transform_jsx_to_schema


# ── Type classification ──

def test_div_flex_col_becomes_stack():
    src = '<div className="flex flex-col gap-4">hi</div>'
    schema = transform_jsx_to_schema(src)
    root = schema["children"][0]
    assert root["type"] == "Stack"
    assert root["props"]["className"] == "flex flex-col gap-4"


def test_div_flex_only_becomes_row():
    src = '<div className="flex items-center">hi</div>'
    schema = transform_jsx_to_schema(src)
    assert schema["children"][0]["type"] == "Row"


def test_div_grid_becomes_grid():
    src = '<div className="grid grid-cols-2 gap-4">hi</div>'
    schema = transform_jsx_to_schema(src)
    assert schema["children"][0]["type"] == "Grid"


def test_div_unclassified_becomes_container():
    src = '<div className="relative h-12">hi</div>'
    schema = transform_jsx_to_schema(src)
    assert schema["children"][0]["type"] == "Container"
    # 'relative' is stripped; 'h-12' is a non-absolute sizing utility, kept
    assert schema["children"][0]["props"].get("className", "") == "h-12"


# ── Paragraph → Heading vs Text ──

def test_p_large_text_becomes_heading():
    src = '<p className="text-[30px] font-bold">IntentAI</p>'
    schema = transform_jsx_to_schema(src)
    root = schema["children"][0]
    assert root["type"] == "Heading"
    assert root["props"]["content"] == "IntentAI"
    assert root["props"]["level"] == 2  # 30px → level 2


def test_p_medium_text_with_bold_becomes_heading_3():
    src = '<p className="text-[16px] font-bold">Hello</p>'
    schema = transform_jsx_to_schema(src)
    assert schema["children"][0]["type"] == "Heading"
    assert schema["children"][0]["props"]["level"] == 3


def test_p_small_text_becomes_text():
    src = '<p className="text-[14px]">Description</p>'
    schema = transform_jsx_to_schema(src)
    root = schema["children"][0]
    assert root["type"] == "Text"
    assert root["props"]["content"] == "Description"


def test_p_with_text_24px_becomes_heading_level_4():
    """24-30px range → level 4 (sub-headline)."""
    src = '<p className="text-[24px]">Welcome</p>'
    schema = transform_jsx_to_schema(src)
    root = schema["children"][0]
    assert root["type"] == "Heading"
    assert root["props"]["level"] == 4


def test_p_with_text_18px_becomes_heading_level_4():
    src = '<p className="text-[18px]">Subheading</p>'
    schema = transform_jsx_to_schema(src)
    assert schema["children"][0]["type"] == "Heading"


# ── img → Image ──

def test_img_becomes_image():
    src = '<img src="https://cdn/x.png" alt="Logo" />'
    schema = transform_jsx_to_schema(src)
    root = schema["children"][0]
    assert root["type"] == "Image"
    assert root["props"]["src"] == "https://cdn/x.png"
    assert root["props"]["alt"] == "Logo"


# ── Composite recognition via data-name ──

def test_email_input_composite():
    src = '<div data-name="Email Input"><p>demo@x.com</p></div>'
    schema = transform_jsx_to_schema(src)
    root = schema["children"][0]
    assert root["type"] == "Input"
    assert root["props"]["type"] == "email"
    assert root["props"]["placeholder"] == "demo@x.com"
    assert root["children"] == []


def test_password_input_composite():
    src = '<div data-name="Password Input"><p>password</p></div>'
    schema = transform_jsx_to_schema(src)
    root = schema["children"][0]
    assert root["type"] == "Input"
    assert root["props"]["type"] == "password"
    assert root["props"]["placeholder"] == "password"


def test_button_composite():
    src = '<div data-name="Button"><p>Sign in</p></div>'
    schema = transform_jsx_to_schema(src)
    root = schema["children"][0]
    assert root["type"] == "Button"
    assert root["props"]["label"] == "Sign in"
    assert root["children"] == []


def test_checkbox_composite():
    src = '<div data-name="Checkbox" />'
    schema = transform_jsx_to_schema(src)
    assert schema["children"][0]["type"] == "Checkbox"


def test_link_composite():
    src = '<div data-name="Link"><p>Forgot password?</p></div>'
    schema = transform_jsx_to_schema(src)
    root = schema["children"][0]
    assert root["type"] == "Link"
    assert root["props"]["label"] == "Forgot password?"


def test_form_composite_recurses():
    """Form must recurse — its children are the inputs."""
    src = '<div data-name="Sign in Form"><div data-name="Email Input"><p>x</p></div></div>'
    schema = transform_jsx_to_schema(src)
    root = schema["children"][0]
    assert root["type"] == "Form"
    assert len(root["children"]) == 1
    assert root["children"][0]["type"] == "Input"


def test_heading_n_composite():
    src = '<div data-name="Heading 1"><p>Title</p></div>'
    schema = transform_jsx_to_schema(src)
    root = schema["children"][0]
    assert root["type"] == "Heading"
    assert root["props"]["level"] == 1
    assert root["props"]["content"] == "Title"


def test_primitive_label_composite():
    src = '<div data-name="Primitive.label"><p>Email</p></div>'
    schema = transform_jsx_to_schema(src)
    root = schema["children"][0]
    assert root["type"] == "Text"
    assert root["props"]["role"] == "label"
    assert root["props"]["content"] == "Email"


def test_logo_image_composite():
    src = '<div data-name="Logo Image"><img src="https://cdn/logo.png" alt="" /></div>'
    schema = transform_jsx_to_schema(src)
    root = schema["children"][0]
    assert root["type"] == "Image"
    assert root["props"]["src"] == "https://cdn/logo.png"
    assert root["props"]["alt"] == "Logo"


# ── Style + className passthrough ──

def test_className_passthrough():
    src = '<div className="bg-red-500 p-4">x</div>'
    schema = transform_jsx_to_schema(src)
    assert schema["children"][0]["props"]["className"] == "bg-red-500 p-4"


def test_style_passthrough():
    src = '<div style={{ backgroundColor: "red" }}>x</div>'
    schema = transform_jsx_to_schema(src)
    assert schema["children"][0]["props"]["style"]["backgroundColor"] == "red"


def test_data_node_id_preserved_as_figma_node_id():
    src = '<div data-node-id="1:5">x</div>'
    schema = transform_jsx_to_schema(src)
    assert schema["children"][0]["props"]["_figmaNodeId"] == "1:5"


# ── Asset path rewriting ──

def test_asset_path_rewriting():
    src = '<img src="https://cdn/abc.png" alt="" />'
    asset_paths = {"https://cdn/abc.png": "/figma/abc.png"}
    schema = transform_jsx_to_schema(src, asset_paths)
    assert schema["children"][0]["props"]["src"] == "/figma/abc.png"


def test_asset_path_rewriting_logo_image():
    src = '<div data-name="Logo Image"><img src="https://cdn/logo.png" /></div>'
    asset_paths = {"https://cdn/logo.png": "/figma/logo.png"}
    schema = transform_jsx_to_schema(src, asset_paths)
    assert schema["children"][0]["props"]["src"] == "/figma/logo.png"


# ── PageV2 envelope ──

def test_returns_pagev2_envelope():
    schema = transform_jsx_to_schema('<div>x</div>')
    assert schema["schemaVersion"] == "2.0"
    assert "children" in schema
    assert "dataSources" in schema


# ── Fixture round-trip ──

import pathlib
FIXTURE = pathlib.Path(__file__).parent.parent / "fixtures" / "figma" / "commitbiz_login_design_context.tsx"


def test_fixture_round_trip_expected_types():
    src = FIXTURE.read_text()
    schema = transform_jsx_to_schema(src)
    types: dict[str, int] = {}
    def walk(n):
        if isinstance(n, dict):
            t = n.get("type")
            if t: types[t] = types.get(t, 0) + 1
            for c in n.get("children") or []: walk(c)
    walk(schema)
    print("[fixture types]", types)
    assert types.get("Heading", 0) >= 2, f"need 2+ Heading, got {types}"
    assert types.get("Input", 0) >= 2, f"need 2+ Input, got {types}"
    assert types.get("Button", 0) >= 1
    assert types.get("Checkbox", 0) >= 1
    assert types.get("Image", 0) >= 1
    assert types.get("Text", 0) >= 3
    has_two_col = types.get("Grid", 0) >= 1 or types.get("Row", 0) >= 1
    assert has_two_col, f"need Grid or Row for two-column layout, got {types}"


def test_fixture_button_has_label():
    src = FIXTURE.read_text()
    schema = transform_jsx_to_schema(src)
    button = None
    def find(n):
        nonlocal button
        if isinstance(n, dict) and n.get("type") == "Button":
            button = n; return
        if isinstance(n, dict):
            for c in n.get("children") or []: find(c)
    find(schema)
    assert button is not None
    assert button["props"].get("label") == "Sign in"


def test_fixture_email_input_has_placeholder():
    src = FIXTURE.read_text()
    schema = transform_jsx_to_schema(src)
    email_input = None
    def find(n):
        nonlocal email_input
        if isinstance(n, dict) and n.get("type") == "Input" and n.get("props",{}).get("type") == "email":
            email_input = n; return
        if isinstance(n, dict):
            for c in n.get("children") or []: find(c)
    find(schema)
    assert email_input is not None
    assert "demo@" in email_input["props"].get("placeholder", "")


# =============================================================================
# C.4 — _filter_position_classes tests
# =============================================================================

from services.jsx_to_schema import _filter_position_classes


def test_filter_strips_absolute_positioning():
    # absolute + arbitrary px positioning
    assert _filter_position_classes("absolute left-[123px] top-[456px] bg-white") == "bg-white"
    # relative is stripped; flex utilities preserved
    filtered = _filter_position_classes("relative shrink-0 flex flex-col gap-4")
    assert "flex" in filtered
    assert "relative" not in filtered
    # z-index stripped
    assert "z-10" not in _filter_position_classes("flex z-10 bg-white")
    # The POSITION goes and the SIZE stays, whether or not absolute is present.
    # Stripping the size too left absolutely-positioned image cards with
    # neither offsets nor dimensions, and a thirty-card dashboard frame
    # rendered three of them — see
    # tests/services/test_a_designed_card_keeps_its_size.py.
    assert "w-[200px]" in _filter_position_classes("absolute w-[200px] h-[40px]")
    assert "w-[200px]" in _filter_position_classes("flex w-[200px] gap-4")
    # bg-[rgb(...)] preserved even when absolute is present
    assert "bg-[rgb(132,16,19)]" in _filter_position_classes("absolute bg-[rgb(132,16,19)] left-0")


def test_filter_strips_fixed():
    result = _filter_position_classes("fixed inset-0 bg-black")
    assert "fixed" not in result
    assert "inset-0" not in result
    assert "bg-black" in result


def test_filter_strips_inset_variants():
    assert "inset-x-0" not in _filter_position_classes("inset-x-0 inset-y-4 p-4")
    assert "p-4" in _filter_position_classes("inset-x-0 inset-y-4 p-4")


def test_filter_strips_translate():
    result = _filter_position_classes("translate-x-1/2 translate-y-[-50%] flex")
    assert "translate-x-1/2" not in result
    assert "translate-y-[-50%]" not in result
    assert "flex" in result


def test_filter_strips_transform():
    result = _filter_position_classes("transform translate-x-4 bg-white")
    assert "transform" not in result
    assert "bg-white" in result


def test_filter_preserves_flex_grid_utilities():
    cn = "flex flex-col grid grid-cols-2 gap-4 gap-x-2"
    result = _filter_position_classes(cn)
    for cls in ["flex", "flex-col", "grid", "grid-cols-2", "gap-4", "gap-x-2"]:
        assert cls in result, f"{cls!r} should be preserved"


def test_filter_preserves_bg_text_border():
    cn = "bg-red-500 text-white border border-gray-200 rounded-lg"
    assert _filter_position_classes(cn) == cn


def test_filter_preserves_padding_margin():
    cn = "p-4 px-6 py-2 m-auto mx-4"
    assert _filter_position_classes(cn) == cn


def test_filter_preserves_w_full_h_full():
    cn = "w-full h-full min-h-screen max-w-lg"
    assert _filter_position_classes(cn) == cn


def test_filter_empty_string():
    assert _filter_position_classes("") == ""


def test_filter_keeps_h_px_with_or_without_absolute():
    """A fixed height survives the position filter either way.

    This asserted the reverse — that `absolute h-[40px]` lost its height. That
    rule is what emptied Figma pages: the offsets are re-inferred as a flex
    flow by `_infer_absolute_flow`, but a dimension cannot be re-inferred from
    an image, so removing both left nothing to draw.
    """
    assert "h-[40px]" in _filter_position_classes("absolute h-[40px] bg-white")
    assert "h-[40px]" in _filter_position_classes("flex h-[40px] bg-white")
    # The position itself is still stripped — only the size was rescued.
    assert "absolute" not in _filter_position_classes("absolute h-[40px] bg-white")


# ── Integration: no absolute classes in fixture schema ──

def test_fixture_no_flow_absolute_in_classnames():
    """After transform, no className prop should contain pixel-offset 'absolute'
    (flow-layout abuse like left-0 top-[74px]).

    Decorative SVG layers with percentage-based offsets (inset-[8.33%], etc.)
    ARE allowed — those are intentionally preserved by Fix 1 (C.7).
    """
    import json
    src = FIXTURE.read_text()
    schema = transform_jsx_to_schema(src)
    schema_text = json.dumps(schema)

    import re
    from services.jsx_to_schema import _is_decorative_positioned
    classnames = re.findall(r'"className"\s*:\s*"([^"]*)"', schema_text)
    for cn in classnames:
        if "absolute" in cn.split():
            # Decorative SVG layers are allowed to keep absolute + pct offsets
            assert _is_decorative_positioned(cn), \
                f"Found non-decorative 'absolute' in className: {cn!r}"
        # left-[ with pixel values should still be stripped for non-decorative nodes
        tokens = cn.split()
        for t in tokens:
            if t.startswith("left-[") and "px" in t:
                # Only allowed if this node is decorative
                assert _is_decorative_positioned(cn), \
                    f"Found pixel left-[ in non-decorative className: {cn!r}"


# =============================================================================
# C.7 — Fix 1: decorative absolute positioning preserved; parent gets relative
# =============================================================================

from services.jsx_to_schema import _is_decorative_positioned, _filter_position_classes, transform_jsx_to_schema


def test_is_decorative_positioned_inset_pct():
    """absolute + inset-[8.33%] → decorative (percentage-based SVG layer)."""
    assert _is_decorative_positioned("absolute inset-[8.33%] bg-transparent") is True


def test_is_decorative_positioned_negative_inset_pct():
    """absolute + inset-[-5%] → decorative."""
    assert _is_decorative_positioned("absolute inset-[-5%]") is True


def test_is_decorative_positioned_fraction_left():
    """absolute + left-1/2 → decorative (fraction offset)."""
    assert _is_decorative_positioned("absolute left-1/2 top-[8.3%]") is True


def test_is_decorative_positioned_bottom_quarter():
    """absolute + bottom-1/4 → decorative."""
    assert _is_decorative_positioned("absolute bottom-1/4 left-[16.8%]") is True


def test_is_decorative_positioned_pixel_offset_not_decorative():
    """absolute + left-0 top-[74px] → NOT decorative (flow-layout abuse)."""
    assert _is_decorative_positioned("absolute left-0 top-[74px] w-[404px]") is False


def test_is_decorative_positioned_px_width_only():
    """absolute + w-[351px] (text wrapper) → NOT decorative (pixel, not percent)."""
    assert _is_decorative_positioned("absolute left-0 top-[0.25px] w-[351px]") is False


def test_is_decorative_positioned_no_absolute():
    """Percentage inset without absolute → NOT decorative."""
    assert _is_decorative_positioned("inset-[8.33%] bg-white") is False


def test_filter_position_classes_preserve_absolute():
    """When preserve_absolute=True, absolute + offsets are kept."""
    cn = "absolute inset-[8.33%] bg-transparent"
    result = _filter_position_classes(cn, preserve_absolute=True)
    assert "absolute" in result
    assert "inset-[8.33%]" in result


def test_filter_position_classes_preserve_strips_leading_zero_only():
    """preserve_absolute only strips leading-[0], keeps everything else."""
    cn = "absolute left-[4px] top-[8px] leading-[0] bg-white"
    result = _filter_position_classes(cn, preserve_absolute=True)
    assert "absolute" in result
    assert "left-[4px]" in result
    assert "leading-[0]" not in result


def test_filter_position_classes_normal_strips():
    """Without preserve_absolute, absolute+offsets still stripped."""
    cn = "absolute left-[4px] top-[8px] bg-white"
    result = _filter_position_classes(cn, preserve_absolute=False)
    assert "absolute" not in result
    assert "left-[4px]" not in result
    assert "bg-white" in result


def test_parent_gets_relative_when_children_absolute():
    """A container whose child is absolute-positioned should gain `relative`."""
    src = '''
    <div className="shrink-0 size-[56px] bg-white">
      <div className="absolute inset-[8.33%]">
        <img src="x.png" />
      </div>
    </div>
    '''
    schema = transform_jsx_to_schema(src)
    root = schema["children"][0]
    cn = root["props"].get("className", "")
    assert "relative" in cn.split(), f"Expected 'relative' in parent className, got: {cn!r}"


def test_parent_does_not_double_relative():
    """A parent that already has a position keyword should not get a second one."""
    src = '''
    <div className="relative shrink-0 size-[56px]">
      <div className="absolute inset-[8.33%]">
        <img src="x.png" />
      </div>
    </div>
    '''
    schema = transform_jsx_to_schema(src)
    root = schema["children"][0]
    cn = root["props"].get("className", "")
    # 'relative' should appear only once
    assert cn.split().count("relative") == 1, f"Expected exactly one 'relative' in: {cn!r}"


def test_decorative_child_keeps_absolute_offsets():
    """Decorative SVG layers (absolute + inset-%) keep their offsets in the schema."""
    src = '''
    <div className="relative size-[32px]">
      <div className="absolute inset-[8.33%]">
        <div className="absolute inset-[-5%]">
          <img alt="" className="size-full" src="x.png" />
        </div>
      </div>
    </div>
    '''
    schema = transform_jsx_to_schema(src)
    # Recursively collect all classNames
    import json
    schema_text = json.dumps(schema)
    import re
    classnames = re.findall(r'"className"\s*:\s*"([^"]*)"', schema_text)
    # At least one className should still have absolute with inset
    has_preserved = any("absolute" in cn and "inset-" in cn for cn in classnames)
    assert has_preserved, f"Expected at least one preserved absolute+inset in classnames: {classnames}"


# =============================================================================
# C.7 — Fix 2: Heading N wrapper reads leaf <p> text size
# =============================================================================

def test_heading4_wrapper_with_24px_leaf():
    """data-name='Heading 4' with leaf p text-[24px] should get className with text-[24px]."""
    src = '''
    <div data-name="Heading 4">
      <p className="text-[24px] font-medium tracking-[0.07px]">Welcome</p>
    </div>
    '''
    schema = transform_jsx_to_schema(src)
    root = schema["children"][0]
    assert root["type"] == "Heading"
    assert root["props"]["content"] == "Welcome"
    cn = root["props"].get("className", "")
    assert "text-[24px]" in cn, f"Expected text-[24px] in className, got: {cn!r}"
    assert "font-medium" in cn, f"Expected font-medium in className, got: {cn!r}"


def test_heading4_wrapper_30px_leaf_upgrades_level():
    """Leaf p text-[30px] should upgrade the heading to level 2."""
    src = '''
    <div data-name="Heading 4">
      <p className="text-[30px] font-bold">BigTitle</p>
    </div>
    '''
    schema = transform_jsx_to_schema(src)
    root = schema["children"][0]
    assert root["type"] == "Heading"
    assert root["props"]["level"] == 2


def test_heading_wrapper_no_leaf_p_unchanged():
    """Heading wrapper with no leaf <p> should still emit correctly."""
    src = '<div data-name="Heading 2">Title Text</div>'
    schema = transform_jsx_to_schema(src)
    root = schema["children"][0]
    assert root["type"] == "Heading"
    assert root["props"]["level"] == 2
    assert root["props"]["content"] == "Title Text"


# =============================================================================
# C.7 — Fix 3: fixture subtitle text has className (not purple after re-transform)
# =============================================================================

def test_fixture_subtitle_has_classname():
    """The 'Sign in to access your workspace' <p> should emit className with color."""
    src = FIXTURE.read_text()
    schema = transform_jsx_to_schema(src)
    # Find the Text node with that content
    subtitle = None
    def find(n):
        nonlocal subtitle
        if isinstance(n, dict):
            if n.get("type") == "Text" and "Sign in" in str(n.get("props", {}).get("content", "")):
                subtitle = n; return
            for c in n.get("children") or []: find(c)
    find(schema)
    # The subtitle is a bare <p> — it should become a Text with className passthrough
    # (The Figma src has text-[#6e2574] on it which the transformer now passes through)
    assert subtitle is not None, "Subtitle Text node not found"
    # The className should exist (even if it has the purple color from design)
    assert "className" in subtitle["props"], \
        f"Expected className on subtitle Text, got props: {subtitle['props']}"


# =============================================================================
# C.8 — Generalised absolute-flow detection
# =============================================================================

def test_absolute_col_flow_becomes_stack_with_gap():
    src = '''
    function App() { return (
      <div data-name="X">
        <div className="absolute top-0 left-0">A</div>
        <div className="absolute top-[74px] left-0">B</div>
        <div className="absolute top-[148px] left-0">C</div>
      </div>
    ); }
    '''
    schema = transform_jsx_to_schema(src)
    root = schema["children"][0]
    assert root["type"] == "Stack"
    assert "flex-col" in root["props"]["className"]
    assert "gap-[" in root["props"]["className"]


def test_absolute_row_flow_becomes_row_with_gap():
    src = '''
    function App() { return (
      <div data-name="X">
        <div className="absolute top-0 left-0">A</div>
        <div className="absolute top-0 left-[120px]">B</div>
        <div className="absolute top-0 left-[240px]">C</div>
      </div>
    ); }
    '''
    schema = transform_jsx_to_schema(src)
    root = schema["children"][0]
    assert root["type"] == "Row"


def test_decorative_overlap_not_treated_as_flow():
    # All children at same top — overlapping decorative layout, not flowed
    src = '''
    function App() { return (
      <div className="size-[32px]">
        <div className="absolute inset-[8.33%]"><img src="a"/></div>
        <div className="absolute inset-1/4"><img src="b"/></div>
      </div>
    ); }
    '''
    schema = transform_jsx_to_schema(src)
    root = schema["children"][0]
    # Should still be Container (decorative), not Stack/Row
    assert root["type"] == "Container"


def test_grid_not_overridden():
    src = '''
    function App() { return (
      <div className="grid grid-cols-[repeat(2,1fr)]">
        <div className="absolute top-0 left-0">A</div>
        <div className="absolute top-[74px] left-0">B</div>
      </div>
    ); }
    '''
    schema = transform_jsx_to_schema(src)
    # Grid is preserved
    root = schema["children"][0]
    assert root["type"] == "Grid"
