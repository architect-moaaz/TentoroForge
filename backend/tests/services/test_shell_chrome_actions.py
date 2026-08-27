"""Shell chrome must not ship controls that do nothing.

Two live defects this pins down, both on the DETERMINISTIC shell path
(the Figma importer has its own toggle heuristic, which is why neither
surfaced there):

  1. The hamburger never carried `togglesSidebar`, so the mobile nav
     drawer could not be opened at all — the runtime seam
     (Button -> data-sidebar-toggle -> ShellStateProvider) was already
     in place; only the flag was missing.
  2. The notifications bell was emitted unconditionally with no action,
     advertising a capability the app may not have.
"""
import pytest

from services.shell_templates import (
    _frame_rail,
    _frame_sidebar,
    _frame_split,
    _frame_topbar,
    extract_tokens,
)

FRAMES = [_frame_sidebar, _frame_topbar, _frame_rail, _frame_split]


def _item(label: str, route: str) -> dict:
    return {"label": label, "route": route, "icon": "box"}


def _buttons(node, icon: str) -> list[dict]:
    out, stack = [], [node]
    while stack:
        x = stack.pop()
        if isinstance(x, list):
            stack.extend(x)
            continue
        if not isinstance(x, dict):
            continue
        if x.get("type") == "Button" and (x.get("props") or {}).get("icon") == icon:
            out.append(x["props"])
        stack.extend(x.get("children") or [])
    return out


@pytest.fixture
def tokens():
    return extract_tokens(None, None)


@pytest.mark.parametrize("frame", FRAMES, ids=lambda f: f.__name__)
def test_no_bell_when_the_app_has_no_notifications_route(frame, tokens):
    groups = [{"label": "Menu", "items": [_item("Products", "/products")]}]
    assert _buttons(frame(groups, tokens), "bell") == []


@pytest.mark.parametrize("frame", FRAMES, ids=lambda f: f.__name__)
def test_bell_navigates_when_a_destination_exists(frame, tokens):
    groups = [{"label": "Menu", "items": [
        _item("Products", "/products"),
        _item("Notifications", "/notifications"),
    ]}]
    bells = _buttons(frame(groups, tokens), "bell")
    assert len(bells) == 1
    assert bells[0]["navigate"] == "/notifications"


@pytest.mark.parametrize("frame", FRAMES, ids=lambda f: f.__name__)
def test_hamburger_toggles_the_sidebar(frame, tokens):
    groups = [{"label": "Menu", "items": [_item("Products", "/products")]}]
    for props in _buttons(frame(groups, tokens), "menu"):
        assert props.get("togglesSidebar") is True, (
            "a hamburger without togglesSidebar renders a button that does "
            "nothing — mobile users can never open the nav"
        )
