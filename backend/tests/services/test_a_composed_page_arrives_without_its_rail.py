"""End to end through the seams: a stored design's rail never reaches a page,
and what it says is recorded on the source.

`chrome.py` is tested on its own. This pins the two places it is wired in,
because each has already lost a value once (`canvas`, `_figmaDerived`, the
Tailwind glob): `figma_layout.compose` must strip the shared subtree from every
page it composes, and `store.connect` must record what the rail says as
`designSources[].chrome` so the navigation author can read it.

Two screens are the minimum that can share anything. Their JSX is Dev Mode's
real shape — `Stack > Stack(bg) > Row > [rail, page]` — with real actions on
the rail so the recorded groups carry bindings.
"""
import json

import pytest

from services.blueprint import figma_layout
from services.figma import store
from services.figma.reference import DesignReference, ScreenRef
from services.figma.url import FigmaTarget

RAIL = '''
      <div className="bg-[#110f0c] flex flex-col w-[240px] h-full" data-node-id="1:9">
        <p className="text-[14px]">Criterion</p>
        <p className="text-[11px]">OVERVIEW</p>
        <div className="flex gap-[10px] px-[12px] py-[8px]" data-node-id="1:10" data-name="Button"><p className="text-[12px]">⬡Dashboard</p></div>
        <div className="flex gap-[10px] px-[12px] py-[8px]" data-node-id="1:11" data-name="Button"><p className="text-[12px]">⌂Front Desk</p></div>
        <p className="text-[11px]">CASES</p>
        <div className="flex gap-[10px] px-[12px] py-[8px]" data-node-id="1:12" data-name="Button"><p className="text-[12px]">+New Case</p></div>
      </div>'''

# THE FIXTURE IS THE EXPORT'S REAL SHAPE. Dev Mode writes a nav item as a
# `data-name` wrapper around a <p>, never as <button>; the transform has no
# <button> branch and dropped the first version of this rail silently, which
# made two screens share nothing and "proved" the wrong thing.


def _screen(node_id, title, body):
    return f'''
export default function Frame() {{
  return (
    <div className="bg-[#f7f3eb] relative size-full" data-node-id="{node_id}">
      <div className="flex flex-col w-full" data-node-id="{node_id}0">
        <div className="flex" data-node-id="{node_id}1">{RAIL}
          <div className="flex flex-col w-[1147px]" data-node-id="{node_id}2">
            <p className="text-[24px]">{title}</p>
            <p className="text-[14px]">{body}</p>
          </div>
        </div>
      </div>
    </div>
  );
}}
'''


def _ref():
    return DesignReference(
        target=FigmaTarget(file_key="aBcD1234EfGh",
                           source_url="https://figma.com/design/aBcD1234EfGh/X"),
        source_id="FIGMA-001",
        screens=[
            ScreenRef(node_id="1:2", name="Home", canvas="Page 1", width=1440, height=900,
                      structure={"source": "design_context_code",
                                 "code": _screen("1:2", "Operations Dashboard", "Open cases 4"),
                                 "assets": []}),
            ScreenRef(node_id="1:3", name="Cases", canvas="Page 1", width=1440, height=900,
                      structure={"source": "design_context_code",
                                 "code": _screen("1:3", "Cases", "CAS-2024-0441"),
                                 "assets": []}),
        ],
    )


class _Svc:
    def __init__(self, doc, output_dir):
        self.doc, self.output_dir = doc, str(output_dir)

    def save(self):
        pass


def _labels(node, out=None):
    out = [] if out is None else out
    if isinstance(node, dict):
        p = node.get("props") or {}
        t = p.get("label") or p.get("content")
        if isinstance(t, str):
            out.append(t)
        for c in node.get("children") or []:
            _labels(c, out)
    return out


# ------------------------------------------------------------------ compose

def test_a_composed_page_does_not_carry_the_rail(tmp_path, monkeypatch):
    ref = _ref()
    store.save(ref, tmp_path)
    doc = {"designSources": [{"id": "FIGMA-001", "fileKey": "aBcD1234EfGh",
                              "frames": [{"nodeId": "1:2"}, {"nodeId": "1:3"}]}],
           "pages": [], "workflows": [], "data": {"entities": []}}
    # No network: the region/vision pass is an enrichment and is not under test.
    monkeypatch.setattr(figma_layout, "_classify_regions", lambda *a, **k: [])
    svc = _Svc(doc, tmp_path)

    out = figma_layout.compose(svc, {"id": "PAGE-001", "route": "/", "name": "Home",
                                     "figmaFrame": "1:2"}, app_root=tmp_path / "app")
    assert out is not None
    words = " ".join(_labels(out["root"]))
    assert "Operations Dashboard" in words and "Open cases 4" in words
    assert "Front Desk" not in words and "Criterion" not in words


def test_the_content_is_unwrapped_and_keeps_the_frames_background(tmp_path, monkeypatch):
    ref = _ref(); store.save(ref, tmp_path)
    doc = {"designSources": [{"id": "FIGMA-001", "fileKey": "aBcD1234EfGh",
                              "frames": [{"nodeId": "1:2"}, {"nodeId": "1:3"}]}],
           "pages": [], "workflows": [], "data": {"entities": []}}
    monkeypatch.setattr(figma_layout, "_classify_regions", lambda *a, **k: [])
    out = figma_layout.compose(_Svc(doc, tmp_path),
                               {"id": "PAGE-001", "route": "/", "figmaFrame": "1:2"},
                               app_root=tmp_path / "app")
    root = out["root"]
    assert "bg-[#f7f3eb]" in (root.get("props") or {}).get("className", "")
    assert "w-[1147px]" not in (root.get("props") or {}).get("className", "")


def test_a_single_screen_composes_whole(tmp_path, monkeypatch):
    """Nothing to compare with — the page keeps its rail, exactly as before."""
    ref = _ref(); ref.screens = ref.screens[:1]; store.save(ref, tmp_path)
    doc = {"designSources": [{"id": "FIGMA-001", "fileKey": "aBcD1234EfGh",
                              "frames": [{"nodeId": "1:2"}]}],
           "pages": [], "workflows": [], "data": {"entities": []}}
    monkeypatch.setattr(figma_layout, "_classify_regions", lambda *a, **k: [])
    out = figma_layout.compose(_Svc(doc, tmp_path),
                               {"id": "PAGE-001", "route": "/", "figmaFrame": "1:2"},
                               app_root=tmp_path / "app")
    assert "Front Desk" in " ".join(_labels(out["root"]))


# ------------------------------------------------------------------ connect

def test_connect_records_what_the_rail_says(tmp_path):
    doc = {}
    record = store.connect(_Svc(doc, tmp_path), _ref(), treat_as="evidence")
    chrome = record.get("chrome")
    assert chrome and chrome["sharedBy"] == 2
    groups = chrome["sidebar"]["groups"]
    assert [g["label"] for g in groups] == ["OVERVIEW", "CASES"]
    assert groups[0]["items"][0]["label"] == "Dashboard"
    assert doc["designSources"][0]["chrome"] == chrome


def test_connect_records_nothing_for_one_screen(tmp_path):
    ref = _ref(); ref.screens = ref.screens[:1]
    record = store.connect(_Svc({}, tmp_path), ref, treat_as="evidence")
    assert "chrome" not in record


def test_the_record_satisfies_the_contract(tmp_path):
    """The field is declared, so the Blueprint validator accepts it — the
    first run without this failed with 'chrome was unexpected'."""
    import jsonschema
    schema = json.load(open("contracts/blueprint.schema.json"))
    record = store.connect(_Svc({}, tmp_path), _ref(), treat_as="evidence")
    jsonschema.validate(record, schema["properties"]["designSources"]["items"])


# ------------------------------------------- fingerprinting is not a build

def test_fingerprinting_never_calls_the_action_classifier(tmp_path, monkeypatch):
    """A run sat nine minutes in `page_layouts` composing nothing: the chrome
    fingerprint transformed every screen with the routes/workflows vocabulary
    still set, so every button on every screen was a real classifier call,
    per subject, twelve subjects at once. A fingerprint is types and text."""
    from services import figma_action_llm, jsx_to_schema
    from services.figma_llm_ctx import set_figma_llm_context, reset_figma_llm_context

    calls: list[str] = []

    def boom(label, **_k):
        calls.append(label)
        raise RuntimeError("the LLM boundary was reached while fingerprinting")

    # THE INNER CALL, NOT THE GATED WRAPPER. Patching the wrapper replaced the
    # gate itself, so every button raised inside the transform's per-node
    # guard and was dropped — the rail lost its labels and "was not found",
    # which proved nothing about the classifier. The wrapper only reaches
    # `classify_figma_action_llm` when the vocabulary is set; that is exactly
    # the condition fingerprinting must clear.
    monkeypatch.setattr(figma_action_llm, "classify_figma_action_llm", boom)
    monkeypatch.setattr(jsx_to_schema, "_figma_llm_enabled", lambda: True)
    monkeypatch.setattr(figma_layout, "_classify_regions", lambda *a, **k: [])
    figma_layout._CHROME_CACHE.clear()

    store.save(_ref(), tmp_path)
    doc = {"designSources": [{"id": "FIGMA-001", "fileKey": "aBcD1234EfGh",
                              "frames": [{"nodeId": "1:2"}, {"nodeId": "1:3"}]}],
           "pages": [{"id": "PAGE-001", "route": "/"}], "workflows": [{"id": "FLOW-001"}],
           "data": {"entities": []}}
    set_figma_llm_context(routes=["/"], workflows=["FLOW-001"])
    try:
        shared = figma_layout._shared_chrome_for(_Svc(doc, tmp_path))
    finally:
        reset_figma_llm_context()
    assert shared, "the rail was not found"
    assert calls == [], f"classifier reached for: {calls[:3]}"


def test_the_vocabulary_survives_fingerprinting(tmp_path, monkeypatch):
    """Cleared for the transform, restored after — the page's own buttons
    still bind."""
    from services.figma_llm_ctx import (
        get_routes, get_workflows, set_figma_llm_context, reset_figma_llm_context,
    )
    monkeypatch.setattr(figma_layout, "_classify_regions", lambda *a, **k: [])
    figma_layout._CHROME_CACHE.clear()
    store.save(_ref(), tmp_path)
    doc = {"designSources": [{"id": "FIGMA-001", "frames": []}], "pages": [],
           "workflows": [], "data": {"entities": []}}
    set_figma_llm_context(routes=["/x"], workflows=["FLOW-009"])
    try:
        figma_layout._shared_chrome_for(_Svc(doc, tmp_path))
        assert get_routes() == ["/x"] and get_workflows() == ["FLOW-009"]
    finally:
        reset_figma_llm_context()
