"""design-context.json is the provider-neutral file; figma-context.json is
read as a fallback and the Figma module keeps its public names."""
from __future__ import annotations

import json

from services import design_context as dc
from services.figma_context import (
    extract_figma_context,
    get_figma_context_for_prompt,
    should_refetch_figma,
    tokens_from_styles,
)


_TOKENS = {"colors": ["#123456", "#FFFFFF"], "fonts": ["Inter"], "font_sizes": [14],
           "border_radii": [8], "spacings": [16]}


def test_write_then_read_names_the_provider(tmp_path):
    ctx = dc.write_design_context(tmp_path, provider="uxpilot", design_ref="pg_9", tokens=_TOKENS)
    assert ctx["provider"] == "uxpilot" and ctx["design_ref"] == "pg_9"
    assert "figma_url" not in ctx
    on_disk = json.loads((tmp_path / dc.CONTEXT_PATH).read_text())
    assert on_disk["design_tokens"]["colors"] == ["#123456", "#FFFFFF"]
    assert dc.read_design_context(tmp_path)["provider"] == "uxpilot"


def test_figma_write_keeps_the_url_key_legacy_readers_expect(tmp_path):
    ctx = dc.write_design_context(tmp_path, provider="figma", design_ref="https://figma.com/design/abc", tokens=_TOKENS)
    assert ctx["figma_url"] == "https://figma.com/design/abc"


def test_legacy_figma_context_file_is_read_as_figma(tmp_path):
    p = tmp_path / dc.LEGACY_CONTEXT_PATH
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"figma_url": "https://figma.com/design/old", "design_tokens": _TOKENS}))
    ctx = dc.read_design_context(tmp_path)
    assert ctx["provider"] == "figma"
    assert ctx["design_ref"] == "https://figma.com/design/old"
    assert dc.context_ref_changed(tmp_path, "https://figma.com/design/new")
    assert not dc.context_ref_changed(tmp_path, "https://figma.com/design/old")


def test_prompt_section_names_the_provider(tmp_path):
    assert dc.get_design_context_for_prompt(tmp_path) == ""
    dc.write_design_context(tmp_path, provider="uxpilot", design_ref="pg", tokens=_TOKENS)
    text = dc.get_design_context_for_prompt(tmp_path)
    assert "## Design Context" in text
    assert "UX Pilot design" in text
    assert "#123456" in text and "Inter" in text
    assert "reference.png" not in text
    dc.write_design_context(tmp_path, provider="figma", design_ref="u", tokens=_TOKENS)
    assert "reference.png" in dc.get_design_context_for_prompt(tmp_path)
    assert get_figma_context_for_prompt(str(tmp_path)) == dc.get_design_context_for_prompt(tmp_path)


def test_tokens_from_styles_walks_fills_text_and_layout():
    styles = {
        "fills": [{"color": "#AABBCC"}],
        "textStyle": {"fontFamily": "Inter", "fontSize": 14},
        "borderRadius": 8,
        "layout": {"gap": 12, "padding": {"top": 16, "left": 0}},
        "children": [{"textColor": "#112233", "border": {"color": "#445566"},
                      "textStyle": {"fontFamily": "Inter", "fontSize": 20}, "borderRadius": [4, 0]}],
    }
    t = tokens_from_styles(styles)
    assert t["colors"] == ["#112233", "#445566", "#AABBCC"]
    assert t["fonts"] == ["Inter"]
    assert t["font_sizes"] == [14, 20]
    assert t["border_radii"] == [4, 8]
    assert t["spacings"] == [12, 16]


def test_extract_figma_context_writes_the_shared_file(tmp_path):
    (tmp_path / "styles.json").write_text(json.dumps({"fills": [{"color": "#ABCDEF"}]}))
    ctx = extract_figma_context(str(tmp_path), "https://figma.com/design/k")
    assert ctx["provider"] == "figma"
    assert ctx["figma_url"] == "https://figma.com/design/k"
    assert ctx["styles_json_hash"].startswith("sha256:")
    assert (tmp_path / dc.CONTEXT_PATH).exists()
    # Same URL, artifacts present → no refetch; new URL → refetch.
    (tmp_path / "reference.png").write_bytes(b"png")
    assert not should_refetch_figma(str(tmp_path), "https://figma.com/design/k")
    assert should_refetch_figma(str(tmp_path), "https://figma.com/design/other")


def test_extract_figma_context_without_styles_returns_empty(tmp_path):
    assert extract_figma_context(str(tmp_path), "u") == {}
