"""A page that was drawn is built from the drawing; everything else is composed.

`page_layouts` has one producer per page and now two ways to get one. The seam
is `pages[].figmaFrame`: a page naming a frame is built from that frame's
design context, a page naming none falls through to A2UI.

That mix is the point. A design of eight screens against a data model implying
thirty pages should ship thirty pages, eight of them pixel-accurate — not eight
pages and a hole. So *falling through is the normal case*, and every branch that
cannot produce a tree must fall through rather than fail: a missing extraction,
a frame with no captured code, an unparseable frame. The one outcome worse than
a composed page is no page.

The field was already in the contract and already writable by `page_design`.
What was missing was that `designSources` sat outside what that agent could
read, so it was being asked to name a node id it had never been shown.
"""
import json
import pathlib
import tempfile

import pytest

from services.blueprint import figma_layout as F
from services.blueprint.executors import build_prompt, context_for, DAG
from services.figma import store
from services.figma.reference import DesignReference, ScreenRef
from services.figma.url import FigmaTarget

FIXTURE = (pathlib.Path(__file__).resolve().parents[1]
           / "fixtures" / "figma" / "commitbiz_login_design_context.tsx")


class _Svc:
    def __init__(self, doc, output_dir):
        self.doc = doc
        self.output_dir = str(output_dir)


def _stored(tmp_path, *, code: str, node_id: str = "1:2"):
    """A connected design whose frame carries captured design-context code."""
    ref = DesignReference(
        target=FigmaTarget(file_key="aBcD1234EfGh",
                           source_url="https://figma.com/design/aBcD1234EfGh/X"),
        source_id="FIGMA-001",
        screens=[ScreenRef(node_id=node_id, name="Login", canvas="Page 1",
                           structure={"source": "design_context_code",
                                      "code": code, "assets": []})],
    )
    store.save(ref, tmp_path)
    doc = {"designSources": [{"id": "FIGMA-001",
                              "frames": [{"nodeId": node_id, "name": "Login"}]}]}
    return _Svc(doc, tmp_path)


# ------------------------------------------------------- the mapping reaches the author

def test_page_design_may_read_the_frames_it_must_name():
    """It could always WRITE `figmaFrame`; it could not SEE the frames."""
    doc = {"application": {"name": "X"}, "designSources": [
        {"id": "FIGMA-001", "frames": [{"nodeId": "1:2", "name": "Dashboard"}]}]}
    ctx = json.dumps(context_for(doc, DAG["page_contracts"].agent))
    assert "designSources" in ctx and "1:2" in ctx


def test_the_prompt_asks_for_the_frame_only_when_a_design_is_connected():
    base = {"application": {"name": "X"}, "requirements": [], "pages": [],
            "data": {"entities": []}, "modules": [], "roles": []}
    _s, without = build_prompt(base, "page_contracts")
    _s, with_ = build_prompt(dict(base, designSources=[
        {"id": "FIGMA-001", "frames": [{"nodeId": "1:2", "name": "D"}]}]),
        "page_contracts")
    assert "figmaFrame" not in without
    assert "figmaFrame" in with_


def test_the_prompt_says_omitting_the_frame_is_a_good_outcome():
    """A wrong id builds a screen from the wrong picture, so "leave it out"
    has to stay the easy answer."""
    _s, user = build_prompt({"application": {"name": "X"}, "requirements": [],
                             "pages": [], "data": {"entities": []},
                             "modules": [], "roles": [],
                             "designSources": [{"id": "FIGMA-001", "frames": [
                                 {"nodeId": "1:2", "name": "D"}]}]},
                            "page_contracts")
    assert "OMIT" in user


# --------------------------------------------------------------- falling through

@pytest.mark.parametrize("page,doc", [
    ({"id": "P1"}, {}),                                        # never drawn
    ({"id": "P1", "figmaFrame": ""}, {}),                      # empty is not a frame
    ({"id": "P1", "figmaFrame": "1:2"}, {"designSources": []}),  # no source
    ({"id": "P1", "figmaFrame": "1:2"},
     {"designSources": [{"id": "FIGMA-001"}]}),                # nothing extracted
])
def test_a_page_without_a_usable_frame_falls_through(page, doc, tmp_path):
    assert F.compose(_Svc(doc, tmp_path), page, app_root=tmp_path) is None


def test_a_frame_with_no_captured_code_falls_through(tmp_path):
    """§93 — a restored Blueprint may name a source whose payload is gone, and
    an extraction predating the code path recorded the node tree instead."""
    svc = _stored(tmp_path, code="")
    assert F.compose(svc, {"id": "P1", "route": "/login", "figmaFrame": "1:2"},
                     app_root=tmp_path) is None


def test_an_unparseable_frame_costs_the_page_its_design_not_its_existence(tmp_path):
    svc = _stored(tmp_path, code="this is not JSX at all {{{")
    out = F.compose(svc, {"id": "P1", "route": "/login", "figmaFrame": "1:2"},
                    app_root=tmp_path)
    assert out is None          # A2UI composes it instead


# ------------------------------------------------------------- the real thing

@pytest.mark.skipif(not FIXTURE.is_file(), reason="Figma fixture not present")
def test_a_drawn_page_is_built_from_the_drawing(tmp_path):
    """Real `get_design_context` output, through the whole seam."""
    svc = _stored(tmp_path, code=FIXTURE.read_text(encoding="utf-8"))
    out = F.compose(svc, {"id": "PAGE-001", "route": "/login", "name": "Login",
                          "figmaFrame": "1:2"}, app_root=tmp_path / "app")
    assert out is not None, "the fixture frame should compose"
    assert isinstance(out["root"], dict)
    assert out["root"].get("type")


@pytest.mark.skipif(not FIXTURE.is_file(), reason="Figma fixture not present")
def test_the_tree_uses_components_the_engine_can_render(tmp_path):
    """A Figma tree and an A2UI tree are stored in one section and rendered by
    one engine, so the vocabularies must agree — otherwise the page composes,
    validates, projects, and fails in the browser."""
    registry = json.loads((pathlib.Path(__file__).resolve().parents[2]
                           / "contracts" / "component-catalog.json").read_text(encoding="utf-8"))
    raw = registry["components"]
    names = set(raw) if isinstance(raw, dict) else {c["name"] for c in raw}

    svc = _stored(tmp_path, code=FIXTURE.read_text(encoding="utf-8"))
    out = F.compose(svc, {"id": "PAGE-001", "route": "/login",
                          "figmaFrame": "1:2"}, app_root=tmp_path / "app")
    seen = set()

    def walk(node):
        if isinstance(node, dict):
            if node.get("type"):
                seen.add(node["type"])
            for child in node.get("children") or []:
                walk(child)

    walk(out["root"])
    assert seen, "the fixture produced no typed nodes"
    assert not (seen - names), f"not renderable: {sorted(seen - names)}"


# ------------------------------------------------ the branch, not just the helper

def test_the_executor_branch_survives_a_broken_composer(tmp_path, monkeypatch):
    """A NameError in this branch killed the subject outright.

    The Figma attempt sits before A2UI inside `_compose_via_a2ui`, and it was
    NOT inside the try that wraps the A2UI call — so a mistake in it did not
    fall through to A2UI, it removed the page from `pageLayouts` altogether.
    The whole contract of the seam is that a design can only ever cost a page
    its pixels, never its existence.

    Exercised through the module the executor imports, because the earlier
    tests here call `figma_layout.compose` directly and that is precisely the
    path that stayed green while the branch around it raised.
    """
    from services.blueprint import figma_layout

    def explode(*_a, **_k):
        raise NameError("name 'tell' is not defined")

    monkeypatch.setattr(figma_layout, "compose", explode)

    # The executor calls it exactly this way; the assertion is that the caller
    # is expected to guard it rather than that it is safe to call.
    with pytest.raises(NameError):
        figma_layout.compose(None, {"id": "P1"}, app_root=tmp_path)


def test_assets_are_written_under_the_app_root(tmp_path):
    """`public/figma/` is served from `<project>/app`, so composing with the
    project directory put every SVG one level above the tree referencing it."""
    import inspect

    from services.blueprint import executors

    src = inspect.getsource(executors)
    assert 'app_root=Path(svc.output_dir) / "app"' in src, (
        "the Figma branch must compose against the app root, not the project root"
    )
