"""What stopped the Figma design being usable as a specification.

kkb5mzo3, 2026-11-02: with the design held as `specification`, `page_layouts`
ran for 4m43s and refused every page. Dozens of refusals each, nearly all of
one kind — `Image 'src' is a required property` — so the design produced no
layouts at all. Separately the screen classifier that could have described
those regions never answered: its budget was 8,000 tokens and it spent them
all reasoning.

The fix belongs on the path that VALIDATES a tree, not in the shared
converter: the asset pipeline discovers Image nodes in a pass with no
`asset_paths` and fills them in a second, so erasing the type in
`figma_to_schema` erased the hook (it broke
`test_asset_paths_threaded_into_icon_image_props` and a login page's logo).
"""

from services.blueprint.figma_layout import _drop_sourceless_images
from services.figma_to_schema import _build_node


def _node(name, ftype="RECTANGLE", nid="1:5"):
    return {"node": {"id": nid, "name": name, "type": ftype}}


# -- the converter keeps its behaviour -------------------------------------

def test_the_shared_converter_still_emits_an_image_without_a_source():
    """The asset pipeline's discovery pass depends on it."""
    built = _build_node(_node("Hero Image"), asset_paths=None)
    assert built["type"] == "Image"
    assert built["props"].get("alt")


def test_an_image_with_a_source_is_an_image_with_a_source():
    built = _build_node(_node("Hero Image", nid="1:9"),
                        asset_paths={"1:9": "/api/asset/p/figma/1-9.png"})
    assert built["type"] == "Image" and built["props"]["src"] == "/api/asset/p/figma/1-9.png"


# -- the layout path resolves them before validating ------------------------

def test_a_sourceless_image_becomes_a_box():
    page = {"type": "Stack", "props": {}, "children": [
        {"type": "Image", "props": {"alt": "Logo", "_figmaNodeId": "1:5"}, "children": []},
    ]}
    assert _drop_sourceless_images(page) == 1
    box = page["children"][0]
    assert box["type"] == "Container"
    assert "alt" not in box["props"]
    assert box["props"]["_figmaNodeId"] == "1:5", "an export can make it an Image again"


def test_an_image_that_has_a_source_is_left_alone():
    page = {"type": "Stack", "props": {}, "children": [
        {"type": "Image", "props": {"src": "/a.png", "alt": "Logo"}, "children": []},
    ]}
    assert _drop_sourceless_images(page) == 0
    assert page["children"][0]["type"] == "Image"


def test_it_reaches_the_deeply_nested_ones():
    """The refusals named paths like root.children[0]...children[1].children[0]."""
    deep = {"type": "Image", "props": {}, "children": []}
    page = {"type": "Stack", "props": {}, "children": [
        {"type": "Box", "props": {}, "children": [
            {"type": "Box", "props": {}, "children": [deep]}]}]}
    assert _drop_sourceless_images(page) == 1
    assert deep["type"] == "Container"


def test_an_icon_is_left_alone():
    page = {"type": "Icon", "props": {}, "children": []}
    assert _drop_sourceless_images(page) == 0


# -- the classifier has room to answer --------------------------------------

def test_the_screen_classifier_is_not_capped_at_eight_thousand():
    """It reasons over every rendered region of a screen before writing, and
    the cap covers the thinking as well as the answer. Vision returns [] on
    failure, so too small a budget is silent."""
    import inspect

    from services.blueprint import figma_layout

    src = inspect.getsource(figma_layout)
    assert "max_tokens=8000" not in src, "8,000 was spent entirely on reasoning"
    assert "DEFAULT_MAX_TOKENS" in src


# -- the other half: a drawn button that does nothing ----------------------

def test_the_rest_converter_asks_what_a_button_does():
    """The JSX path has always asked `figma_action_classifier`; the REST path
    never did, and production Figma reads go over REST."""
    built = _build_node({"node": {"id": "1:7", "name": "Sign in", "type": "FRAME"},
                         "text": "Sign in"}, asset_paths=None)
    if built["type"] == "Button":
        assert set(built["props"]) & {"navigate", "workflow", "submit", "onClick"}, (
            "a button the classifier can place must carry its action")


def test_a_button_nobody_can_place_becomes_a_label():
    """Refusing the page is worse, and inventing a target is worse still —
    which is what the action vocabulary exists to prevent."""
    from services.blueprint.figma_layout import _unarm_actionless_controls

    page = {"type": "Stack", "props": {}, "children": [
        {"type": "Button", "props": {"label": "Last 30 days", "_figmaNodeId": "1:9"},
         "children": []},
    ]}
    assert _unarm_actionless_controls(page, {"navigate", "workflow", "submit", "onClick"}) == 1
    node = page["children"][0]
    assert node["type"] == "Text"
    assert node["props"]["text"] == "Last 30 days", "the screen still reads"
    assert node["props"]["_figmaNodeId"] == "1:9", "Smith can wire it later"


def test_a_button_that_does_something_is_untouched():
    from services.blueprint.figma_layout import _unarm_actionless_controls

    page = {"type": "Button", "props": {"label": "Create refund", "navigate": "/cases/new"},
            "children": []}
    assert _unarm_actionless_controls(page, {"navigate", "workflow"}) == 0
    assert page["type"] == "Button" and page["props"]["navigate"] == "/cases/new"


def test_a_templated_control_keeps_its_affordance():
    """A repeated control takes its action from the item it repeats over, so
    the template carries none — the completeness check exempts it and so must
    this."""
    from services.blueprint.figma_layout import _unarm_actionless_controls

    page = {"type": "Stack", "props": {}, "children": [
        {"type": "Button", "props": {"label": "$item.label"}, "children": []},
        {"type": "Button", "props": {"label": "Open"}, "repeat": "rows", "children": []},
    ]}
    assert _unarm_actionless_controls(page, {"navigate", "workflow"}) == 0
    assert [c["type"] for c in page["children"]] == ["Button", "Button"]


def test_a_form_with_no_action_is_unarmed_too():
    """`_ACTIONABLE` is (Button, Form) — workflow_slots records a Form refused
    the same way."""
    from services.blueprint.figma_layout import _unarm_actionless_controls

    page = {"type": "Form", "props": {"submitLabel": "Save"}, "children": []}
    assert _unarm_actionless_controls(page, {"navigate", "workflow", "submit"}) == 1
    assert page["type"] == "Text"


# -- one classifier, both paths --------------------------------------------

def test_both_figma_paths_ask_the_same_function():
    """The logic used to live inside the JSX transformer, which is why the
    REST path never had it. Two copies would drift."""
    import inspect

    from services import figma_to_schema, jsx_to_schema

    assert "classify_action" in inspect.getsource(figma_to_schema._build_node)
    assert "classify_action" in inspect.getsource(jsx_to_schema._classify_button_action_uncached)


def test_it_prefers_the_model_when_there_is_a_vocabulary(monkeypatch):
    from services import figma_action_llm as mod

    mod._ACTION_MEMO.clear()
    monkeypatch.setattr("services.figma_llm_ctx.figma_llm_enabled", lambda: True)
    monkeypatch.setattr("services.figma_llm_ctx.get_routes", lambda: ["/cases/new"])
    monkeypatch.setattr("services.figma_llm_ctx.get_workflows", lambda: [])
    monkeypatch.setattr("services.figma_llm_ctx.get_action_query_fn", lambda: None)

    class _B:
        kind, target = "navigate", "/cases/new"

    monkeypatch.setattr(mod, "classify_figma_action_llm", lambda *a, **k: _B())
    assert mod.classify_action("Create refund") == {"navigate": "/cases/new"}


def test_it_falls_back_to_keywords_when_the_model_cannot_help(monkeypatch):
    from services import figma_action_llm as mod

    mod._ACTION_MEMO.clear()
    monkeypatch.setattr("services.figma_llm_ctx.figma_llm_enabled", lambda: True)
    monkeypatch.setattr("services.figma_llm_ctx.get_routes", lambda: ["/x"])
    monkeypatch.setattr("services.figma_llm_ctx.get_workflows", lambda: [])
    monkeypatch.setattr("services.figma_llm_ctx.get_action_query_fn", lambda: None)

    def boom(*a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(mod, "classify_figma_action_llm", boom)
    from services.figma_action_classifier import classify_button_action
    assert mod.classify_action("Sign in") == classify_button_action("Sign in")


def test_the_same_label_is_asked_once(monkeypatch):
    """A rail is the same twenty buttons on every screen."""
    from services import figma_action_llm as mod

    mod._ACTION_MEMO.clear()
    calls = []
    monkeypatch.setattr("services.figma_llm_ctx.figma_llm_enabled", lambda: True)
    monkeypatch.setattr("services.figma_llm_ctx.get_routes", lambda: ["/cases"])
    monkeypatch.setattr("services.figma_llm_ctx.get_workflows", lambda: [])
    monkeypatch.setattr("services.figma_llm_ctx.get_action_query_fn", lambda: None)

    class _B:
        kind, target = "navigate", "/cases"

    def once(*a, **k):
        calls.append(1)
        return _B()

    monkeypatch.setattr(mod, "classify_figma_action_llm", once)
    for _ in range(5):
        mod.classify_action("All refunds")
    assert len(calls) == 1
