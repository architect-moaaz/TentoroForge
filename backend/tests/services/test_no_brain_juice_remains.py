"""Brain Juice became the Drafts Room (2026-10-14): one room for the
conversation, the study of references, the idea board and the hand-off that
creates and builds the app. Nothing is left under the old name."""
from __future__ import annotations

import importlib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
FRONTEND = BACKEND.parent / "frontend" / "src"


def test_no_brain_juice_module_or_route():
    assert not (BACKEND / "services" / "brain_juice").exists()
    assert not (BACKEND / "routers" / "brain_juice.py").exists()
    import routers.drafts_room as room
    assert all(str(r.path).startswith("/api/orgs/{org_id}/drafts-room") for r in room.router.routes), \
        [str(r.path) for r in room.router.routes]
    main = (BACKEND / "main.py").read_text()
    assert "drafts_room_router" in main and "brain_juice" not in main
    assert importlib.import_module("services.drafts_room.agent").pitch_of


def test_the_menu_names_the_drafts_room_and_the_old_address_only_redirects():
    layout = (FRONTEND / "app" / "org" / "[orgId]" / "layout.tsx").read_text()
    assert '"/drafts-room"' in layout and "Brain Juice" not in layout
    old = FRONTEND / "app" / "org" / "[orgId]" / "brain-juice" / "page.tsx"
    assert old.exists() and "drafts-room" in old.read_text() and "router.replace" in old.read_text()
    assert not (FRONTEND / "components" / "brain-juice").exists()
    panel = (FRONTEND / "components" / "smith" / "SmithPanel.tsx").read_text()
    assert "brain_juice_" not in panel and "drafts_room_" not in panel, "nothing is replayed from sessionStorage"
