from services.figma_typography_extractor import extract_typography


def _text(name, style):
    return {"node": {"name": name, "type": "TEXT", "style": style}, "parent": None, "path": []}


def test_heading_family_picked_from_heading_named_text():
    walked = [
        _text("IntentAI Title", {"fontFamily": "Inter Display", "fontWeight": 700, "fontSize": 32, "lineHeightPx": 40, "letterSpacing": -0.5}),
        _text("Welcome Title", {"fontFamily": "Inter Display", "fontWeight": 600, "fontSize": 24, "lineHeightPx": 32, "letterSpacing": -0.3}),
    ]
    t = extract_typography(walked)
    assert t["font"]["heading"] == "Inter Display"
    assert t["weight"]["heading"] in ("600", "700")


def test_body_family_picked_from_plain_text():
    walked = [
        _text("Sign in Subtitle", {"fontFamily": "Inter", "fontWeight": 400, "fontSize": 16, "lineHeightPx": 24}),
        _text("Platform Description", {"fontFamily": "Inter", "fontWeight": 400, "fontSize": 14, "lineHeightPx": 20}),
    ]
    t = extract_typography(walked)
    assert t["font"]["body"] == "Inter"
    assert t["weight"]["body"] == "400"


def test_heading_and_body_can_be_different_families():
    walked = [
        _text("Heading 1", {"fontFamily": "Cal Sans", "fontWeight": 700, "fontSize": 32, "lineHeightPx": 40}),
        _text("Sign in Subtitle", {"fontFamily": "Inter", "fontWeight": 400, "fontSize": 16, "lineHeightPx": 24}),
    ]
    t = extract_typography(walked)
    assert t["font"]["heading"] == "Cal Sans"
    assert t["font"]["body"] == "Inter"


def test_only_heading_seen_propagates_to_body():
    """If only heading-named TEXT exists, use its family for body too."""
    walked = [_text("Heading 1", {"fontFamily": "Cal Sans", "fontWeight": 700, "fontSize": 32, "lineHeightPx": 40})]
    t = extract_typography(walked)
    assert t["font"]["body"] == "Cal Sans"
    assert t["font"]["heading"] == "Cal Sans"


def test_scale_collects_unique_sizes():
    walked = [
        _text("Heading 1", {"fontFamily": "Inter", "fontWeight": 700, "fontSize": 32, "lineHeightPx": 40}),
        _text("Heading 4", {"fontFamily": "Inter", "fontWeight": 600, "fontSize": 18, "lineHeightPx": 24}),
        _text("Paragraph", {"fontFamily": "Inter", "fontWeight": 400, "fontSize": 16, "lineHeightPx": 24}),
        _text("Email Label", {"fontFamily": "Inter", "fontWeight": 500, "fontSize": 12, "lineHeightPx": 16}),
    ]
    t = extract_typography(walked)
    values = set(t["scale"].values())
    # 12 → 0.75rem, 16 → 1rem, 18 → 1.125rem, 32 → 2rem
    assert "0.75rem" in values
    assert "1rem" in values
    assert "2rem" in values


def test_line_height_normal_from_body_ratio():
    walked = [_text("Paragraph", {"fontFamily": "Inter", "fontWeight": 400, "fontSize": 16, "lineHeightPx": 24})]
    t = extract_typography(walked)
    # 24/16 = 1.5
    assert t["lineHeight"]["normal"] == "1.5"


def test_letter_spacing_heading_em():
    walked = [_text("Heading 1", {"fontFamily": "Inter", "fontWeight": 700, "fontSize": 32, "lineHeightPx": 40, "letterSpacing": -0.5})]
    t = extract_typography(walked)
    val = t["letterSpacing"]["heading"]
    assert val.endswith("em")
    assert val.startswith("-")


def test_empty_walked_returns_safe_defaults():
    t = extract_typography([])
    assert t["font"]["body"]
    assert t["font"]["heading"]
    assert t["weight"]["body"]
    assert t["weight"]["heading"]
    # scale may be empty when no nodes


def test_ignores_non_text_nodes():
    walked = [
        {"node": {"name": "Container", "type": "FRAME"}, "parent": None, "path": []},
        _text("Body", {"fontFamily": "Inter", "fontWeight": 400, "fontSize": 16, "lineHeightPx": 24}),
    ]
    t = extract_typography(walked)
    assert t["font"]["body"] == "Inter"


def test_text_nodes_with_no_style_are_skipped():
    """TEXT nodes without a `style` dict shouldn't crash; just ignored."""
    walked = [
        {"node": {"name": "Stray", "type": "TEXT"}, "parent": None, "path": []},
        _text("Body", {"fontFamily": "Inter", "fontWeight": 400, "fontSize": 16, "lineHeightPx": 24}),
    ]
    t = extract_typography(walked)
    assert t["font"]["body"] == "Inter"
