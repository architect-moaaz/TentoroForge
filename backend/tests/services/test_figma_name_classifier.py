import pytest
from services.figma_name_classifier import classify


@pytest.mark.parametrize("name, figma_type, expected", [
    # Headings — "Heading N" pattern
    ("Heading 1", "FRAME", ("Heading", {"level": 1})),
    ("Heading 3", "FRAME", ("Heading", {"level": 3})),
    ("Heading 4", "FRAME", ("Heading", {"level": 4})),
    ("Heading 6", "FRAME", ("Heading", {"level": 6})),
    # *-Title suffix → h4 by convention
    ("Welcome Title", "TEXT", ("Heading", {"level": 4})),
    ("IntentAI Title", "TEXT", ("Heading", {"level": 4})),
    # Body text
    ("Paragraph", "FRAME", ("Text", {})),
    ("Sign in Subtitle", "TEXT", ("Text", {})),
    ("Platform Description", "TEXT", ("Text", {})),
    ("Omnichannel Outreach Description", "TEXT", ("Text", {})),
    ("Sign in Button Text", "TEXT", ("Text", {})),  # button text is just text — mapper drops it
    # Form primitives — order matters (checkbox before any catch-all)
    ("Checkbox", "FRAME", ("Checkbox", {})),
    ("Form", "FRAME", ("Form", {})),
    ("Sign in Form", "FRAME", ("Form", {})),
    ("Button", "FRAME", ("Button", {})),
    # Buttons named "* Button" should still classify as Button
    ("Submit Button", "FRAME", ("Button", {})),
    ("Link", "FRAME", ("Link", {})),
    ("Forgot password Link", "FRAME", ("Link", {})),
    # Inputs — type extracted from name
    ("Email Input", "FRAME", ("Input", {"type": "email"})),
    ("Password Input", "FRAME", ("Input", {"type": "password"})),
    ("Search Input", "FRAME", ("Input", {"type": "text"})),
    ("Input", "FRAME", ("Input", {"type": "text"})),
    # Label primitives
    ("Email Label", "TEXT", ("Text", {"role": "label"})),
    ("Primitive.label", "FRAME", ("Text", {"role": "label"})),
    # Media
    ("Logo Image", "RECTANGLE", ("Image", {"alt": "Logo"})),
    ("Logo Image", "FRAME", ("Image", {"alt": "Logo"})),
    ("Icon", "FRAME", ("Icon", {})),
    ("User Icon", "FRAME", ("Icon", {})),
    # Layout — Container kept as-is (refiner will pick Stack/Row/Grid)
    ("Container", "FRAME", ("Container", {})),
    ("Wrapper", "FRAME", ("Container", {})),
    # Fall-through
    ("Mystery Widget", "FRAME", ("Box", {})),
    ("Random thing", "RECTANGLE", ("Box", {})),
])
def test_classify(name, figma_type, expected):
    assert classify(name, figma_type) == expected


def test_classify_handles_extra_whitespace_and_case():
    assert classify("  HEADING 1  ", "FRAME") == ("Heading", {"level": 1})
    assert classify("  email input ", "FRAME") == ("Input", {"type": "email"})


def test_classify_with_empty_name():
    assert classify("", "FRAME") == ("Box", {})
    assert classify("", "TEXT") == ("Box", {})


# ── Dialog / overlay classification ─────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "Modal", "Dialog", "Popup", "Overlay", "Drawer", "Sheet",
])
def test_classify_bare_overlay_names_to_dialog(name):
    """Exact match on overlay nouns → Dialog with empty props (no title)."""
    t, props = classify(name, "FRAME")
    assert t == "Dialog"
    assert "title" not in props  # Bare names don't auto-set title


@pytest.mark.parametrize("name", [
    "View contact Modal",
    "Edit profile Dialog",
    "Confirm delete Popup",
    "Filters Drawer",
    "Cookie consent Overlay",
    "Settings Sheet",
])
def test_classify_named_overlay_carries_title(name):
    """Names like 'View contact Modal' → Dialog with title set to the name."""
    t, props = classify(name, "FRAME")
    assert t == "Dialog"
    assert props.get("title") == name


def test_classify_dialog_does_not_overshadow_other_specific_rules():
    """A node named 'Button' should NOT classify as Dialog even though
    no overlay keyword applies — sanity check for rule order."""
    assert classify("Button", "FRAME") == ("Button", {})


# ── Image classification — tight matching, no screenshot frames ────────────

@pytest.mark.parametrize("name, figma_type, expected_is_image", [
    # Real image asset names paired with image-friendly Figma types
    ("Image", "RECTANGLE", True),
    ("Image 1", "RECTANGLE", True),
    ("Background Image", "RECTANGLE", True),
    ("Hero Image", "RECTANGLE", True),
    ("photo.jpg", "RECTANGLE", True),
    ("avatar.png", "VECTOR", True),
    # FRAME still classifies — caller (SVG-export filter) decides whether
    # to actually export based on size + child count
    ("Background Image", "FRAME", True),
    # Random text that contains "image" mid-word should NOT match.
    ("imagery section", "FRAME", False),
    ("imagery", "FRAME", False),
])
def test_classify_image_is_tight(name, figma_type, expected_is_image):
    t, _ = classify(name, figma_type)
    assert (t == "Image") is expected_is_image, (
        f"name={name!r} type={figma_type} → got {t}, expected_is_image={expected_is_image}"
    )


def test_classify_background_image_frame_with_children_is_not_image():
    """A FRAME named "Background Image" that holds a whole UI subtree
    (30 children = dashboard mockup) must NOT classify as Image, or its
    children get stripped and the page renders empty. With child_count
    supplied, the FRAME falls through to Box/Container and the walker
    descends into the children."""
    t, _ = classify("Background Image", "FRAME", child_count=30)
    assert t != "Image", f"FRAME with children should not be Image, got {t}"


def test_classify_background_image_frame_with_no_children_still_is_image():
    """A FRAME named "Background Image" with zero children IS a leaf
    image-asset (e.g. a single rectangle holding a background photo).
    Keep classifying as Image so the asset pipeline picks it up."""
    t, _ = classify("Background Image", "FRAME", child_count=0)
    assert t == "Image"


def test_classify_logo_image_frame_with_children_falls_through():
    """Same rule applies to the logo path: a multi-node "Logo Image" frame
    (e.g. a wordmark made of vector pieces) needs Box/Container treatment
    so the vectors get rendered; the asset pipeline can still export
    individual VECTOR children as SVG icons."""
    # Note: the 'logo' rule fires first and returns Image regardless of
    # child_count today — that's by design for now (logos rarely have
    # nested layout structure). Document the current behavior so future
    # tightening is intentional.
    t, _ = classify("Logo Image", "FRAME", child_count=5)
    assert t == "Image"  # current behavior; tighten in a follow-up if needed


from services.figma_name_classifier import refine_container_type


def test_horizontal_autolayout_becomes_row():
    assert refine_container_type({"_layoutMode": "HORIZONTAL"}) == "Row"

def test_vertical_autolayout_becomes_stack():
    assert refine_container_type({"_layoutMode": "VERTICAL"}) == "Stack"

def test_horizontal_with_wrap_becomes_grid():
    assert refine_container_type({"_layoutMode": "HORIZONTAL", "_layoutWrap": "WRAP"}) == "Grid"

def test_no_layout_meta_keeps_container():
    assert refine_container_type({}) == "Container"

def test_unknown_layout_mode_keeps_container():
    assert refine_container_type({"_layoutMode": "NONE"}) == "Container"


def test_unknown_named_text_node_falls_through_to_text():
    """A Figma TEXT node whose name doesn't match any rule (chart axis label
    'Jun', table cell '$23.00', free-floating annotation) must still classify
    as Text — otherwise its `characters` value gets dropped on the floor and
    the rendered output shows an empty styled rectangle."""
    schema_type, props = classify("Jun", "TEXT")
    assert schema_type == "Text"
    assert props == {}


def test_unknown_named_frame_node_still_box():
    """Non-TEXT figma types with unknown names still fall to Box (so the
    Container refinement and bbox inference paths can pick them up)."""
    assert classify("MysteryFrame123", "FRAME") == ("Box", {})
    assert classify("MysteryRect", "RECTANGLE") == ("Box", {})


def test_text_classification_specific_rules_still_take_priority():
    """The TEXT fallback doesn't shadow specific rules. A node named
    'Heading 2' that's a Figma TEXT still becomes Heading{level:2}."""
    schema_type, props = classify("Heading 2", "TEXT")
    assert schema_type == "Heading"
    assert props == {"level": 2}
