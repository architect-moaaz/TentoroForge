import json
from pathlib import Path

import pytest

from services.shell_templates import (
    build_shell_deterministic, build_nav_groups, build_nav_items,
    select_frame, extract_tokens, FRAMES,
)
from services.shell_guardrail import validate_shell, is_renderable_shell


def _nav_flow(routes):
    return {"pages": [{"id": r.strip("/") or "home", "route": r, "title": f"{r.strip('/').title() or 'Dashboard'}Page",
                       "params": [], "shell": True} for r in routes]}


_TOKENS = {"primary": "#2E4A6E", "onPrimary": "#FFFFFF", "accent": "#C47D0E",
           "sidebarBg": "#1A2940", "sidebarText": "#C7D2DE", "sidebarMuted": "#7C8BA0",
           "background": "#F1F0ED", "surface": "#FFFFFF", "border": "#DCDAD5",
           "text": "#1C2536", "textMuted": "#546474", "appName": "TestApp"}


@pytest.mark.parametrize("frame", list(FRAMES))
def test_every_frame_is_renderable(frame):
    groups = [{"label": "Ops", "items": [
        {"label": "Dashboard", "route": "/", "icon": "home"},
        {"label": "Orders", "route": "/orders", "icon": "clipboard-list"},
    ]}]
    root = FRAMES[frame](groups, _TOKENS)
    shell = {"schemaVersion": "2.0", "title": "App Shell", "id": "shell", "children": [root]}
    issues = validate_shell(shell)
    assert issues == [], f"{frame} not renderable: {issues}"


def test_frames_use_design_tokens_not_slate():
    groups = [{"label": "Ops", "items": [{"label": "Dashboard", "route": "/", "icon": "home"}]}]
    for frame in FRAMES:
        blob = json.dumps(FRAMES[frame](groups, _TOKENS))
        assert "slate-900" not in blob and "slate-800" not in blob
        assert _TOKENS["primary"] in blob or _TOKENS["sidebarBg"] in blob or _TOKENS["accent"] in blob


def test_select_frame_varies_by_ia():
    # few items -> topbar
    assert select_frame(None, _nav_flow(["/", "/a", "/b"]), None) == "topbar"
    # canvas-heavy (a dispatch board) -> rail
    plan = {"pages": [{"archetype": "kanban"}]}
    assert select_frame(plan, _nav_flow(["/", "/a", "/b", "/c", "/d", "/e"]), None) == "rail"
    # broad admin, no canvas -> sidebar
    broad = _nav_flow(["/", "/a", "/b", "/c", "/d", "/e", "/f", "/g", "/h", "/i", "/j"])
    assert select_frame({"pages": [{"archetype": "list"}]}, broad, None) == "sidebar"
    # inbox/messaging-centric -> split workspace
    inbox = _nav_flow(["/", "/inbox", "/messages", "/contacts", "/settings", "/labels"])
    assert select_frame({"pages": [{"archetype": "inbox"}]}, inbox, None) == "split"


def test_build_nav_items_skips_detail_and_create_routes():
    nf = {"pages": [
        {"route": "/", "title": "DashboardPage", "params": [], "shell": True},
        {"route": "/orders", "title": "OrderListPage", "params": [], "shell": True},
        {"route": "/orders/new", "title": "OrderCreatePage", "params": [], "shell": True},
        {"route": "/orders/[id]", "title": "OrderDetailPage", "params": ["id"], "shell": True},
    ]}
    routes = {i["route"] for i in build_nav_items(nf)}
    assert routes == {"/", "/orders"}


def test_end_to_end_on_real_e1ndat91_artifacts_if_present():
    base = Path("output/e1ndat91/src/contracts")
    nf_p, ds_p = base / "nav-flow.json", base / "design-spec.json"
    if not (nf_p.exists() and ds_p.exists()):
        pytest.skip("e1ndat91 artifacts not present")
    nav_flow = json.loads(nf_p.read_text(encoding="utf-8"))
    design_spec = json.loads(ds_p.read_text(encoding="utf-8"))
    shell = build_shell_deterministic({"pages": []}, nav_flow, None, design_spec)
    assert is_renderable_shell(shell)
    blob = json.dumps(shell)
    # the real navy token, not stock slate
    assert "#1A2940" in blob or "#2E4A6E" in blob
    assert "slate-900" not in blob


def _walk(n):
    if isinstance(n, dict):
        yield n
        for v in n.values():
            yield from _walk(v)
    elif isinstance(n, list):
        for v in n:
            yield from _walk(v)


def test_nav_buttons_carry_onclick_descriptor_for_preview():
    # Engine navigates in the editor preview via [data-nav-trigger], emitted only
    # from an onClick NavActionDescriptor — props.navigate alone (window.location)
    # is dead in the preview iframe.
    shell = build_shell_deterministic({"pages": []}, _nav_flow(["/", "/tasks", "/projects"]), None)
    nav_btns = [n for n in _walk(shell)
                if n.get("type") == "Button" and (n.get("props") or {}).get("navigate")]
    assert nav_btns, "shell has nav buttons"
    for b in nav_btns:
        oc = b["props"].get("onClick")
        assert isinstance(oc, dict) and oc.get("action") == "navigate" and oc.get("to"), \
            f"nav button missing onClick navigate descriptor: {b['props']}"


def test_header_search_input_has_no_stacked_label():
    # A search Input with `label` renders the label stacked above the field
    # (flex-col), breaking the header's items-center row. Must use placeholder +
    # aria-label only.
    shell = build_shell_deterministic({"pages": []}, _nav_flow(["/", "/tasks"]), None)
    searches = [n for n in _walk(shell)
                if n.get("type") == "Input" and (n.get("props") or {}).get("name") == "search"]
    for s in searches:
        assert s["props"].get("label") is None, "header search must not carry a stacked label"
        assert s["props"].get("placeholder"), "header search keeps its placeholder"


def test_extract_tokens_derives_sidebar_active_from_accent():
    """Spec A Slice 4 — active-nav highlight comes from brief.palette.accent.
    Whether the design-spec sets sidebarActive explicitly or falls back to
    accent, the active-nav color always tracks the brief's accent."""
    from services.shell_templates import extract_tokens
    spec = {"colorPalette": {"primary": "#2D5A8E", "accent": "#E8A020",
                              "sidebarBg": "#1A2940", "sidebarText": "#FFFFFF"}}
    t = extract_tokens(spec)
    assert t["sidebarActive"] == "#E8A020"


def test_extract_tokens_explicit_sidebar_active_wins_over_accent():
    from services.shell_templates import extract_tokens
    spec = {"colorPalette": {"primary": "#2D5A8E", "accent": "#E8A020",
                              "sidebarActive": "#00FF00"}}
    assert extract_tokens(spec)["sidebarActive"] == "#00FF00"


def test_extract_tokens_derives_brand_tile_from_primary():
    """Spec A Slice 4 — sidebar top-left brand tile IS the brand color.
    Cures the reported "green square in the sidebar" symptom."""
    from services.shell_templates import extract_tokens
    spec = {"colorPalette": {"primary": "#2D5A8E", "accent": "#E8A020"}}
    assert extract_tokens(spec)["brandTile"] == "#2D5A8E"


def test_extract_tokens_explicit_brand_tile_wins_over_primary():
    from services.shell_templates import extract_tokens
    spec = {"colorPalette": {"primary": "#2D5A8E", "brandTile": "#FF00FF"}}
    assert extract_tokens(spec)["brandTile"] == "#FF00FF"
