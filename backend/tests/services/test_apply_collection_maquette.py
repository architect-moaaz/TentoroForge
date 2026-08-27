"""Tests for services.apply_collection_maquette.

The composer is the "authority not advisory" seam for collections —
maquette is the content contract, composer assembles the schema. Tests
cover:
- multi-maquette dispatch (applies + skips)
- schema lookup (well-known slug + content-match fallback)
- layout branches (table/kanban/calendar/cards/timeline) with fallbacks
- slot honoring (hero, filter_presets, empty_state, footer,
  signature_moves, row_treatment)
- idempotency (re-applying is a no-op)
- fail-closed behavior on unreadable inputs
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.apply_collection_maquette import (
    _build_filter_chip_row,
    _build_footer_node,
    _build_hero_node,
    _humanize,
    _pick_date_column,
    _pick_status_column,
    _route_to_slug,
    apply_maquettes_to_collections,
)


# ─────────────────────────── fixtures ──────────────────────────────────


def _write_registry(root: Path, entities: dict) -> None:
    (root / "src" / "contracts").mkdir(parents=True, exist_ok=True)
    (root / "src" / "contracts" / "registry.json").write_text(
        json.dumps({"entities": entities}), encoding="utf-8",
    )


def _write_maquettes(root: Path, entries: list) -> None:
    (root / "src" / "contracts").mkdir(parents=True, exist_ok=True)
    (root / "src" / "contracts" / "collection-maquettes.json").write_text(
        json.dumps(entries), encoding="utf-8",
    )


def _write_schema(root: Path, slug: str, doc: dict) -> Path:
    (root / "src" / "schemas").mkdir(parents=True, exist_ok=True)
    p = root / "src" / "schemas" / f"{slug}.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _sessions_entity() -> dict:
    # Realistic wellness entity with a status column + a date anchor.
    return {
        "sessions": {
                "fields": [
                    {"name": "id", "type": "uuid"},
                    {"name": "title", "type": "text"},
                    {"name": "startAt", "type": "timestamp"},
                    {"name": "status", "type": "text"},
                    {"name": "capacity", "type": "int"},
                    {"name": "createdAt", "type": "timestamp"},
                ],
        },
    }


def _base_maquette(route: str = "/sessions", layout: str = "table") -> dict:
    return {
        "entity": "sessions",
        "route": route,
        "layout": layout,
        "columns": [
            {"name": "title", "label": "Class", "emphasis": True},
            {"name": "startAt", "label": "When", "kind": "date"},
            {"name": "capacity", "label": "Cap"},
        ],
        "row_treatment": "cozy",
    }


# ─────────────────────────── entry-point ───────────────────────────────


class TestApplyMaquettesToCollections:
    def test_no_maquettes_returns_zero(self, tmp_path: Path):
        result = apply_maquettes_to_collections(str(tmp_path))
        assert result["applied"] == 0
        assert result["skipped"] == 0

    def test_missing_schema_reports_reason_without_authority(
        self, tmp_path: Path, monkeypatch,
    ):
        """Legacy path: with authority off the composer only edits schemas the
        LLM already wrote, so a missing file is a skip with a reason."""
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "0")
        _write_registry(tmp_path, _sessions_entity())
        _write_maquettes(tmp_path, [_base_maquette("/sessions")])
        # No schema file written for /sessions.
        result = apply_maquettes_to_collections(str(tmp_path))
        assert result["applied"] == 0
        assert result["skipped"] == 1
        assert any("no schema" in r for r in result["reasons"])

    def test_missing_schema_is_bootstrapped_under_authority(
        self, tmp_path: Path, monkeypatch,
    ):
        """Authority path: sole writer means the composer AUTHORS the page
        rather than waiting for the LLM to have written one first."""
        monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "1")
        _write_registry(tmp_path, _sessions_entity())
        _write_maquettes(tmp_path, [_base_maquette("/sessions")])
        result = apply_maquettes_to_collections(str(tmp_path))
        assert result["applied"] == 1
        assert (tmp_path / "src" / "schemas" / "sessions.json").is_file()

    def test_bad_json_returns_diagnostic(self, tmp_path: Path):
        _write_registry(tmp_path, _sessions_entity())
        (tmp_path / "src" / "contracts").mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "contracts" / "collection-maquettes.json").write_text(
            "not json", encoding="utf-8",
        )
        result = apply_maquettes_to_collections(str(tmp_path))
        assert result["applied"] == 0
        assert any("unreadable" in r for r in result["reasons"])

    def test_accepts_wrapped_list(self, tmp_path: Path):
        # {maquettes: [...]} shape is also valid — some persistence
        # paths might wrap the list.
        _write_registry(tmp_path, _sessions_entity())
        (tmp_path / "src" / "contracts").mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "contracts" / "collection-maquettes.json").write_text(
            json.dumps({"maquettes": [_base_maquette("/sessions")]}), encoding="utf-8",
        )
        _write_schema(tmp_path, "sessions", {"id": "x", "route": "/sessions", "root": {}})
        result = apply_maquettes_to_collections(str(tmp_path))
        assert result["applied"] == 1

    def test_bad_entries_dont_stop_batch(self, tmp_path: Path):
        _write_registry(tmp_path, _sessions_entity())
        _write_maquettes(tmp_path, [
            "not a dict",
            {"entity": "sessions", "route": "no-slash"},  # bad route
            _base_maquette("/sessions"),
        ])
        _write_schema(tmp_path, "sessions", {"id": "x", "route": "/sessions", "root": {}})
        result = apply_maquettes_to_collections(str(tmp_path))
        # 1 applied, 2 skipped.
        assert result["applied"] == 1
        assert result["skipped"] == 2

    def test_bad_entry_missing_entity_reports_entity_placeholder(self, tmp_path: Path):
        _write_registry(tmp_path, _sessions_entity())
        _write_maquettes(tmp_path, [{"route": "/no-entity"}])
        result = apply_maquettes_to_collections(str(tmp_path))
        assert result["applied"] == 0
        assert any("?:" in r or "?" in r for r in result["reasons"])


# ─────────────────────────── layout branches ───────────────────────────


class TestTableLayout:
    def test_default_layout_is_table_with_columns(self, tmp_path: Path):
        _write_registry(tmp_path, _sessions_entity())
        _write_maquettes(tmp_path, [_base_maquette("/sessions", "table")])
        p = _write_schema(tmp_path, "sessions", {"id": "x", "route": "/sessions", "root": {}})
        apply_maquettes_to_collections(str(tmp_path))
        out = json.loads(p.read_text())
        table = _find(out, "Table")
        assert table is not None
        assert [c["key"] for c in table["props"]["columns"]] == ["title", "startAt", "capacity"]
        assert table["props"]["rowHref"] == "/sessions/{id}"

    def test_table_has_data_row_treatment_attr(self, tmp_path: Path):
        _write_registry(tmp_path, _sessions_entity())
        maq = _base_maquette("/sessions", "table")
        maq["row_treatment"] = "photo-forward"
        _write_maquettes(tmp_path, [maq])
        p = _write_schema(tmp_path, "sessions", {"id": "x", "route": "/sessions", "root": {}})
        apply_maquettes_to_collections(str(tmp_path))
        out = json.loads(p.read_text())
        table = _find(out, "Table")
        assert table["props"]["data-row-treatment"] == "photo-forward"


class TestKanbanLayout:
    def test_kanban_uses_status_column(self, tmp_path: Path):
        _write_registry(tmp_path, _sessions_entity())
        _write_maquettes(tmp_path, [_base_maquette("/sessions", "kanban")])
        p = _write_schema(tmp_path, "sessions", {"id": "x", "route": "/sessions", "root": {}})
        apply_maquettes_to_collections(str(tmp_path))
        out = json.loads(p.read_text())
        kanban = _find(out, "Kanban")
        assert kanban is not None
        assert kanban["props"]["groupBy"] == "status"
        assert kanban["props"]["cardTitle"] == "title"

    def test_kanban_without_status_falls_back_to_table(self, tmp_path: Path):
        _write_registry(tmp_path, {
            "notes": {"fields": [
                {"name": "id", "type": "uuid"},
                {"name": "body", "type": "text"},
            ]},
        })
        maq = _base_maquette("/notes", "kanban")
        maq["entity"] = "notes"
        maq["columns"] = [{"name": "body", "label": "Body"}]
        _write_maquettes(tmp_path, [maq])
        p = _write_schema(tmp_path, "notes", {"id": "x", "route": "/notes", "root": {}})
        apply_maquettes_to_collections(str(tmp_path))
        out = json.loads(p.read_text())
        assert _find(out, "Kanban") is None
        assert _find(out, "Table") is not None
        assert out["root"]["props"]["data-layout"] == "table"


class TestCalendarLayout:
    def test_calendar_uses_first_date_column(self, tmp_path: Path):
        _write_registry(tmp_path, _sessions_entity())
        _write_maquettes(tmp_path, [_base_maquette("/sessions", "calendar")])
        p = _write_schema(tmp_path, "sessions", {"id": "x", "route": "/sessions", "root": {}})
        apply_maquettes_to_collections(str(tmp_path))
        out = json.loads(p.read_text())
        cal = _find(out, "Calendar")
        assert cal is not None
        # Prefer startAt over createdAt.
        assert cal["props"]["dateField"] == "startAt"

    def test_calendar_without_date_falls_back(self, tmp_path: Path):
        _write_registry(tmp_path, {
            "todos": {"fields": [{"name": "id", "type": "uuid"},
                                  {"name": "title", "type": "text"}]},
        })
        maq = _base_maquette("/todos", "calendar")
        maq["entity"] = "todos"
        maq["columns"] = [{"name": "title", "label": "Title"}]
        _write_maquettes(tmp_path, [maq])
        p = _write_schema(tmp_path, "todos", {"id": "x", "route": "/todos", "root": {}})
        apply_maquettes_to_collections(str(tmp_path))
        out = json.loads(p.read_text())
        assert _find(out, "Calendar") is None
        assert _find(out, "Table") is not None


class TestCardsLayout:
    def test_cards_uses_primary_and_secondary(self, tmp_path: Path):
        # ``CardGrid`` was a phantom (not in renderer discriminator; rendered
        # as an error bar). Composer now emits the real primitive combo:
        # Grid > Repeat > Card, with a Heading for the primary field and
        # up to 3 Text children for the secondaries.
        _write_registry(tmp_path, _sessions_entity())
        _write_maquettes(tmp_path, [_base_maquette("/sessions", "cards")])
        p = _write_schema(tmp_path, "sessions", {"id": "x", "route": "/sessions", "root": {}})
        apply_maquettes_to_collections(str(tmp_path))
        out = json.loads(p.read_text())
        # No more CardGrid phantom.
        assert _find(out, "CardGrid") is None
        # Grid wraps the collection.
        grid = _find(out, "Grid")
        assert grid is not None
        # Was `cols: {"base":1,"sm":2,"lg":3}` — a prop Grid never read, so
        # this pinned a grid that rendered as one stacked column. Grid takes a
        # NUMBER and owns that exact responsive ladder itself.
        assert grid["props"]["columns"] == 3
        assert "cols" not in grid["props"]
        # Repeat iterates the data source.
        repeat = _find(grid, "Repeat")
        assert repeat is not None
        # Node-level `bind`, bare name. This used to assert props.bind wrapped
        # in `{{ }}` — pinning the defect: the renderer reads node.bind or
        # props.source and never props.bind, so every card list it emitted
        # iterated nothing.
        assert repeat["bind"] == "sessions" and repeat["props"]["as"] == "item"
        # Card carries the row's primary field as a Heading, and its
        # detail href points at /route/{{item.id}}.
        card = _find(repeat, "Card")
        assert card is not None
        assert card["props"]["href"].endswith("/{{item.id}}")
        heading = _find(card, "Heading")
        assert heading is not None
        assert heading["props"]["content"] == "{{item.title}}"


class TestTimelineLayout:
    def test_timeline_uses_date_field(self, tmp_path: Path):
        _write_registry(tmp_path, _sessions_entity())
        _write_maquettes(tmp_path, [_base_maquette("/sessions", "timeline")])
        p = _write_schema(tmp_path, "sessions", {"id": "x", "route": "/sessions", "root": {}})
        apply_maquettes_to_collections(str(tmp_path))
        out = json.loads(p.read_text())
        tl = _find(out, "TimelineList")
        assert tl is not None
        assert tl["props"]["dateField"] == "startAt"


# ─────────────────────────── slot honoring ─────────────────────────────


class TestHeroSlot:
    def test_hero_becomes_row_header(self, tmp_path: Path):
        _write_registry(tmp_path, _sessions_entity())
        maq = _base_maquette("/sessions", "table")
        maq["hero"] = {"title": "Sessions", "subtitle": "This week", "badge": "12 open"}
        _write_maquettes(tmp_path, [maq])
        p = _write_schema(tmp_path, "sessions", {"id": "x", "route": "/sessions", "root": {}})
        apply_maquettes_to_collections(str(tmp_path))
        out = json.loads(p.read_text())
        # First child is the hero row.
        first = out["root"]["children"][0]
        assert first["type"] == "Row"
        assert first["props"]["data-slot"] == "collection-hero"
        # Contains heading + badge.
        assert _find(first, "Heading")["props"]["content"] == "Sessions"
        assert _find(first, "Badge")["props"]["content"] == "12 open"


class TestFilterPresets:
    def test_filter_chips_row_appears_above_collection(self, tmp_path: Path):
        # Chip strip is now a Cluster (flex-wrap on mobile) instead of a
        # Row (single-axis, no wrap). Chip type=Tag emits `label`
        # (renderer contract) — not `content`. Filter expression is
        # stashed on the NODE not in props (props is strict on Tag).
        # `data-slot` on the container is a node-level attr, not a Row prop.
        _write_registry(tmp_path, _sessions_entity())
        maq = _base_maquette("/sessions", "table")
        maq["filter_presets"] = [
            {"label": "This week", "expr": "startAt < 7d"},
            {"label": "Overdue", "expr": "status=overdue"},
        ]
        _write_maquettes(tmp_path, [maq])
        p = _write_schema(tmp_path, "sessions", {"id": "x", "route": "/sessions", "root": {}})
        apply_maquettes_to_collections(str(tmp_path))
        out = json.loads(p.read_text())
        chip_row = None
        for child in out["root"]["children"]:
            if child.get("type") == "Cluster" and child.get("data-slot") == "collection-filters":
                chip_row = child
                break
        assert chip_row is not None
        chips = chip_row["children"]
        assert [c["props"]["label"] for c in chips] == ["This week", "Overdue"]
        # Filter expr on the node, not inside strict Tag props.
        assert chips[0]["data-filter-expr"] == "startAt < 7d"

    def test_incomplete_presets_dropped(self, tmp_path: Path):
        _write_registry(tmp_path, _sessions_entity())
        maq = _base_maquette("/sessions", "table")
        maq["filter_presets"] = [{"label": "only label"}, {"expr": "only expr"}]
        _write_maquettes(tmp_path, [maq])
        p = _write_schema(tmp_path, "sessions", {"id": "x", "route": "/sessions", "root": {}})
        apply_maquettes_to_collections(str(tmp_path))
        out = json.loads(p.read_text())
        for child in out["root"]["children"]:
            # Chip strip is a Cluster with data-slot at NODE level (not props).
            assert child.get("data-slot") != "collection-filters"


class TestEmptyStateSlot:
    def test_empty_state_applied_to_table_props(self, tmp_path: Path):
        _write_registry(tmp_path, _sessions_entity())
        maq = _base_maquette("/sessions", "table")
        maq["empty_state"] = {
            "illustration": "empty-calendar",
            "headline": "No sessions yet",
            "subhead": "Book your first",
            "cta_label": "Book",
            "cta_action": "/sessions/new",
        }
        _write_maquettes(tmp_path, [maq])
        p = _write_schema(tmp_path, "sessions", {"id": "x", "route": "/sessions", "root": {}})
        apply_maquettes_to_collections(str(tmp_path))
        out = json.loads(p.read_text())
        table = _find(out, "Table")
        assert table["props"]["emptyText"] == "No sessions yet"
        assert table["props"]["emptyDescription"] == "Book your first"
        assert table["props"]["emptyIllustration"] == "empty-calendar"
        assert table["props"]["emptyAction"] == {"label": "Book", "navigate": "/sessions/new"}

    def test_partial_empty_state_applies_what_it_has(self, tmp_path: Path):
        _write_registry(tmp_path, _sessions_entity())
        maq = _base_maquette("/sessions", "table")
        maq["empty_state"] = {"headline": "Nothing yet"}
        _write_maquettes(tmp_path, [maq])
        p = _write_schema(tmp_path, "sessions", {"id": "x", "route": "/sessions", "root": {}})
        apply_maquettes_to_collections(str(tmp_path))
        out = json.loads(p.read_text())
        table = _find(out, "Table")
        assert table["props"]["emptyText"] == "Nothing yet"
        # CTA missing action: should not emit an action button.
        assert "emptyAction" not in table["props"]


class TestFooterSlot:
    def test_insight_footer(self, tmp_path: Path):
        _write_registry(tmp_path, _sessions_entity())
        maq = _base_maquette("/sessions", "table")
        maq["footer"] = {"kind": "insight", "content": "Peak: Tuesday"}
        _write_maquettes(tmp_path, [maq])
        p = _write_schema(tmp_path, "sessions", {"id": "x", "route": "/sessions", "root": {}})
        apply_maquettes_to_collections(str(tmp_path))
        out = json.loads(p.read_text())
        footer = None
        for child in out["root"]["children"]:
            if child.get("props", {}).get("data-slot") == "collection-footer":
                footer = child
                break
        assert footer is not None
        assert footer["props"]["data-footer-kind"] == "insight"

    def test_unknown_footer_kind_dropped(self, tmp_path: Path):
        _write_registry(tmp_path, _sessions_entity())
        maq = _base_maquette("/sessions", "table")
        maq["footer"] = {"kind": "kitchen-sink"}
        _write_maquettes(tmp_path, [maq])
        p = _write_schema(tmp_path, "sessions", {"id": "x", "route": "/sessions", "root": {}})
        apply_maquettes_to_collections(str(tmp_path))
        out = json.loads(p.read_text())
        for child in out["root"]["children"]:
            assert child.get("props", {}).get("data-slot") != "collection-footer"


class TestSignatureMovesAttribute:
    def test_moves_emitted_as_root_data_attr(self, tmp_path: Path):
        _write_registry(tmp_path, _sessions_entity())
        maq = _base_maquette("/sessions", "table")
        maq["signature_moves"] = ["sparkline-preview", "photo-forward-row"]
        _write_maquettes(tmp_path, [maq])
        p = _write_schema(tmp_path, "sessions", {"id": "x", "route": "/sessions", "root": {}})
        apply_maquettes_to_collections(str(tmp_path))
        out = json.loads(p.read_text())
        assert out["root"]["props"]["data-signature-move"] == "sparkline-preview photo-forward-row"

    def test_empty_moves_do_not_emit_attr(self, tmp_path: Path):
        _write_registry(tmp_path, _sessions_entity())
        maq = _base_maquette("/sessions", "table")
        maq["signature_moves"] = []
        _write_maquettes(tmp_path, [maq])
        p = _write_schema(tmp_path, "sessions", {"id": "x", "route": "/sessions", "root": {}})
        apply_maquettes_to_collections(str(tmp_path))
        out = json.loads(p.read_text())
        assert "data-signature-move" not in out["root"]["props"]


# ─────────────────────────── idempotency + fail-closed ─────────────────


class TestIdempotency:
    def test_second_apply_is_a_noop(self, tmp_path: Path):
        _write_registry(tmp_path, _sessions_entity())
        _write_maquettes(tmp_path, [_base_maquette("/sessions", "table")])
        p = _write_schema(tmp_path, "sessions", {"id": "x", "route": "/sessions", "root": {}})
        first = apply_maquettes_to_collections(str(tmp_path))
        assert first["applied"] == 1
        second = apply_maquettes_to_collections(str(tmp_path))
        assert second["applied"] == 0
        assert any("already composed" in r for r in second["reasons"])


class TestScheduleLookup:
    def test_finds_by_route_via_content_when_slug_mismatch(self, tmp_path: Path):
        # Schema file named unlike the route (e.g. "class-list.json" for route
        # /sessions) — content-match fallback should still find it.
        _write_registry(tmp_path, _sessions_entity())
        _write_maquettes(tmp_path, [_base_maquette("/sessions", "table")])
        (tmp_path / "src" / "schemas").mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "schemas" / "class-list.json").write_text(
            json.dumps({"id": "x", "route": "/sessions", "root": {}}), encoding="utf-8",
        )
        result = apply_maquettes_to_collections(str(tmp_path))
        assert result["applied"] == 1


# ─────────────────────────── pure helpers ──────────────────────────────


class TestPickStatusColumn:
    def test_prefers_exact_status(self):
        assert _pick_status_column({"status": "text", "phase": "text"}) == "status"

    def test_falls_back_to_partial_match(self):
        assert _pick_status_column({"orderState": "text"}) == "orderState"

    def test_none_when_absent(self):
        assert _pick_status_column({"title": "text"}) is None


class TestPickDateColumn:
    def test_prefers_event_anchor_over_created_at(self):
        cols = {"createdAt": "timestamp", "startAt": "timestamp"}
        assert _pick_date_column(cols) == "startAt"

    def test_falls_back_to_type(self):
        cols = {"eventDate": "date"}
        assert _pick_date_column(cols) == "eventDate"

    def test_avoids_created_at_when_other_exists(self):
        cols = {"createdAt": "timestamp", "dueDate": "date"}
        # dueDate matches by type before createdAt (last-resort).
        assert _pick_date_column(cols) == "dueDate"

    def test_created_at_is_last_resort(self):
        assert _pick_date_column({"createdAt": "timestamp"}) == "createdAt"


class TestHumanize:
    def test_camel_case(self):
        assert _humanize("createdAt") == "Created At"

    def test_snake_case(self):
        assert _humanize("start_at") == "Start At"

    def test_single_word(self):
        assert _humanize("title") == "Title"


class TestBuildHelpers:
    def test_hero_without_title_returns_none(self):
        assert _build_hero_node({"subtitle": "s"}) is None

    def test_hero_non_dict_returns_none(self):
        assert _build_hero_node("hero") is None

    def test_filter_chip_row_none_for_empty(self):
        assert _build_filter_chip_row([]) is None
        assert _build_filter_chip_row([{"only": "label"}]) is None

    def test_footer_unknown_kind_returns_none(self):
        assert _build_footer_node({"kind": "spicy"}) is None

    def test_footer_non_dict_returns_none(self):
        assert _build_footer_node("footer") is None


class TestRouteToSlug:
    def test_strips_slashes(self):
        assert _route_to_slug("/sessions") == "sessions"
        assert _route_to_slug("/admin/sessions/") == "admin/sessions"

    def test_bare_slash_becomes_index(self):
        assert _route_to_slug("/") == "index"


# ─────────────────────────── shared traversal ──────────────────────────


def _find(node, kind: str):
    """DFS: first node with type=kind."""
    if isinstance(node, dict):
        if node.get("type") == kind:
            return node
        for child in node.get("children", []) or []:
            hit = _find(child, kind)
            if hit is not None:
                return hit
        # Also recurse into root/props children slots.
        for k in ("root", "child"):
            if k in node:
                hit = _find(node[k], kind)
                if hit is not None:
                    return hit
    elif isinstance(node, list):
        for x in node:
            hit = _find(x, kind)
            if hit is not None:
                return hit
    return None
