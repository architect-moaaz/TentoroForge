"""Tests for the Phase 2 wiring layer in plan_finalize.py.

Covers ``author_collection_maquettes_if_enabled`` and
``author_record_maquettes_if_enabled``:
- profile gate (off → returns None + no file written)
- per-page fanout (one entry per matching page)
- LLM-call cap (large plans trim to _MAX_*_MAQUETTES)
- entity/route validation (bad rows skipped, batch continues)
- mode inference for record pages
- file persistence at the expected paths
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from services import plan_finalize
from services.plan_finalize import (
    _MAX_COLLECTION_MAQUETTES,
    _MAX_RECORD_MAQUETTES,
    _infer_record_mode,
    _maquette_profile_on,
    _pages_of_type,
    _resolve_entity,
    author_collection_maquettes_if_enabled,
    author_record_maquettes_if_enabled,
)


# ─────────────────────────── fixtures ──────────────────────────────────


def _write_profile(root: Path, on: bool) -> None:
    """Persist a generation profile with the maquette gate flipped.

    Both registered profiles ("fast" + "complete") ship with
    ``require_kpi_row`` and ``require_primary_chart`` set to True, so
    the maquette gate opens when EITHER is present. "Off" is modelled
    as an absent profile file — :func:`load_profile` returns None and
    the gate stays closed. Path is ``<output>/contracts/generation-profile.json``
    (see :data:`services.generation_profile._REL_PATH`), NOT under ``src/``.
    """
    if not on:
        # No file → load_profile returns None → gate off.
        return
    (root / "contracts").mkdir(parents=True, exist_ok=True)
    # load_profile only reads the ``id`` field and looks up the
    # registered Profile by that id — writing "complete" gives us a
    # profile with the maquette flags on.
    (root / "contracts" / "generation-profile.json").write_text(
        json.dumps({"id": "complete"}), encoding="utf-8",
    )


def _basic_plan() -> dict:
    return {
        "description": "yoga studio for booking classes",
        "module_name": "Rania",
        "entities": {
            "sessions": {"fields": [{"name": "title", "type": "text"},
                                     {"name": "startAt", "type": "timestamp"}]},
            "bookings": {"fields": [{"name": "email", "type": "text"},
                                     {"name": "sessionId", "type": "uuid"}]},
        },
        "pages": [
            {"route": "/sessions", "type": "list", "entity": "sessions",
             "name": "Sessions"},
            {"route": "/bookings", "type": "kanban", "entity": "bookings",
             "name": "Bookings board"},
            {"route": "/sessions/new", "type": "form", "entity": "sessions",
             "name": "New session"},
            {"route": "/bookings/[id]", "type": "detail", "entity": "bookings",
             "name": "Booking detail"},
            {"route": "/sessions/[id]/edit", "type": "edit", "entity": "sessions",
             "name": "Edit session"},
            {"route": "/dashboard", "type": "dashboard", "entity": "sessions",
             "name": "Dashboard"},
        ],
    }


def _stub_author(text: str):
    """Return a monkeypatched author_* factory that ignores the LLM and
    returns a shape from-dict can parse."""
    async def _fake_col(plan, entity, route, *, brief_text=None,
                        query_fn=None, timeout_seconds=45.0):  # noqa: ARG001
        from services.collection_maquette import CollectionMaquette
        return CollectionMaquette.from_dict({
            "entity": entity, "route": route, "layout": "table",
            "columns": [{"name": "title", "label": "Title"}],
        })

    async def _fake_rec(plan, entity, route, *, mode="edit", brief_text=None,
                        query_fn=None, timeout_seconds=45.0):  # noqa: ARG001
        from services.record_maquette import RecordMaquette
        return RecordMaquette.from_dict({
            "entity": entity, "route": route, "mode": mode,
            "section_grouping": [{"label": "Info", "fields": ["title"]}],
        })

    if text == "collection":
        return _fake_col
    return _fake_rec


# ─────────────────────────── pure helpers ──────────────────────────────


class TestPagesOfType:
    def test_matches_type_field(self):
        pages = _pages_of_type(_basic_plan(),
                                 {"list", "kanban", "calendar", "cards", "timeline"})
        assert {p["route"] for p in pages} == {"/sessions", "/bookings"}

    def test_matches_archetype_fallback(self):
        plan = {"pages": [{"route": "/x", "archetype": "list", "entity": "x"}]}
        assert len(_pages_of_type(plan, {"list"})) == 1

    def test_ignores_non_dict_entries(self):
        plan = {"pages": ["not a dict", None, {"route": "/x", "type": "list"}]}
        assert len(_pages_of_type(plan, {"list"})) == 1

    def test_empty_when_no_matches(self):
        assert _pages_of_type({"pages": []}, {"list"}) == []


class TestResolveEntity:
    def test_returns_entity_field(self):
        plan = _basic_plan()
        page = plan["pages"][0]
        assert _resolve_entity(page, plan) == "sessions"

    def test_returns_none_when_entity_missing_from_plan_entities(self):
        plan = _basic_plan()
        page = {"route": "/x", "type": "list", "entity": "unknown-entity"}
        assert _resolve_entity(page, plan) is None

    def test_none_when_no_entity_field(self):
        plan = _basic_plan()
        page = {"route": "/x", "type": "list"}
        assert _resolve_entity(page, plan) is None


class TestInferRecordMode:
    def test_type_form_becomes_create(self):
        assert _infer_record_mode({"type": "form"}, "/x") == "create"

    def test_type_new_becomes_create(self):
        assert _infer_record_mode({"type": "new"}, "/x") == "create"

    def test_type_edit_becomes_edit(self):
        assert _infer_record_mode({"type": "edit"}, "/x") == "edit"

    def test_type_detail_becomes_view(self):
        assert _infer_record_mode({"type": "detail"}, "/x") == "view"

    def test_route_new_suffix_falls_back_to_create(self):
        assert _infer_record_mode({}, "/bookings/new") == "create"

    def test_route_edit_suffix_falls_back_to_edit(self):
        assert _infer_record_mode({}, "/bookings/[id]/edit") == "edit"

    def test_view_is_the_default(self):
        assert _infer_record_mode({}, "/bookings/[id]") == "view"


class TestProfileGate:
    def test_off_when_no_profile(self, tmp_path: Path):
        assert _maquette_profile_on(str(tmp_path)) is False

    def test_off_when_flags_off(self, tmp_path: Path):
        _write_profile(tmp_path, on=False)
        assert _maquette_profile_on(str(tmp_path)) is False

    def test_on_when_flags_on(self, tmp_path: Path):
        _write_profile(tmp_path, on=True)
        assert _maquette_profile_on(str(tmp_path)) is True


# ─────────────────────────── collection authoring ──────────────────────


class TestAuthorCollectionMaquettes:
    def _run(self, coro):
        return asyncio.run(coro)

    def test_returns_none_when_profile_off(self, tmp_path: Path):
        _write_profile(tmp_path, on=False)
        result = self._run(author_collection_maquettes_if_enabled(_basic_plan(), str(tmp_path)))
        assert result is None
        # No file written.
        assert not (tmp_path / "src" / "contracts" / "collection-maquettes.json").is_file()

    def test_returns_empty_list_when_no_collection_pages(self, tmp_path: Path):
        _write_profile(tmp_path, on=True)
        plan = {"pages": [{"route": "/foo", "type": "dashboard", "entity": "x"}],
                "entities": {"x": {"fields": []}}}
        result = self._run(author_collection_maquettes_if_enabled(plan, str(tmp_path)))
        assert result == []

    def test_authors_one_per_collection_page(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        _write_profile(tmp_path, on=True)
        # Monkeypatch the author entry-point so we don't call the LLM.
        import services.collection_maquette as cm
        monkeypatch.setattr(cm, "author_collection_maquette", _stub_author("collection"))
        result = self._run(author_collection_maquettes_if_enabled(_basic_plan(), str(tmp_path)))
        assert result is not None
        # Plan has 2 collection pages: /sessions (list) + /bookings (kanban).
        assert len(result) == 2
        assert {r["route"] for r in result} == {"/sessions", "/bookings"}

    def test_writes_file_at_expected_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        _write_profile(tmp_path, on=True)
        import services.collection_maquette as cm
        monkeypatch.setattr(cm, "author_collection_maquette", _stub_author("collection"))
        self._run(author_collection_maquettes_if_enabled(_basic_plan(), str(tmp_path)))
        p = tmp_path / "src" / "contracts" / "collection-maquettes.json"
        assert p.is_file()
        loaded = json.loads(p.read_text())
        assert isinstance(loaded, list)
        assert len(loaded) == 2

    def test_llm_exception_does_not_stop_batch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        _write_profile(tmp_path, on=True)
        calls = {"n": 0}

        async def _flaky(plan, entity, route, *, brief_text=None,
                         query_fn=None, timeout_seconds=45.0):  # noqa: ARG001
            calls["n"] += 1
            if entity == "sessions":
                raise RuntimeError("boom")
            from services.collection_maquette import CollectionMaquette
            return CollectionMaquette.from_dict({
                "entity": entity, "route": route,
                "columns": [{"name": "title", "label": "Title"}],
            })

        import services.collection_maquette as cm
        monkeypatch.setattr(cm, "author_collection_maquette", _flaky)
        result = self._run(author_collection_maquettes_if_enabled(_basic_plan(), str(tmp_path)))
        # One raised (sessions), one succeeded (bookings).
        assert calls["n"] == 2
        assert result is not None
        assert len(result) == 1
        assert result[0]["entity"] == "bookings"

    def test_pages_without_entity_are_skipped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        _write_profile(tmp_path, on=True)
        plan = {
            "entities": {"sessions": {"fields": []}},
            "pages": [
                {"route": "/sessions", "type": "list", "entity": "sessions"},
                {"route": "/orphan", "type": "list"},  # no entity → skipped
                {"route": "/typo", "type": "list", "entity": "notreal"},  # unknown → skipped
            ],
        }
        import services.collection_maquette as cm
        monkeypatch.setattr(cm, "author_collection_maquette", _stub_author("collection"))
        result = self._run(author_collection_maquettes_if_enabled(plan, str(tmp_path)))
        assert result is not None
        assert len(result) == 1
        assert result[0]["entity"] == "sessions"

    def test_caps_at_max_collection_maquettes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        _write_profile(tmp_path, on=True)
        # Generate more pages than the cap allows.
        n = _MAX_COLLECTION_MAQUETTES + 3
        pages = [{"route": f"/x{i}", "type": "list", "entity": "x"} for i in range(n)]
        plan = {"pages": pages, "entities": {"x": {"fields": []}}}
        import services.collection_maquette as cm
        monkeypatch.setattr(cm, "author_collection_maquette", _stub_author("collection"))
        result = self._run(author_collection_maquettes_if_enabled(plan, str(tmp_path)))
        assert result is not None
        # Cap enforced: at most _MAX_COLLECTION_MAQUETTES entries.
        assert len(result) == _MAX_COLLECTION_MAQUETTES


# ─────────────────────────── record authoring ──────────────────────────


class TestAuthorRecordMaquettes:
    def _run(self, coro):
        return asyncio.run(coro)

    def test_returns_none_when_profile_off(self, tmp_path: Path):
        _write_profile(tmp_path, on=False)
        result = self._run(author_record_maquettes_if_enabled(_basic_plan(), str(tmp_path)))
        assert result is None

    def test_returns_empty_when_no_record_pages(self, tmp_path: Path):
        _write_profile(tmp_path, on=True)
        plan = {"pages": [{"route": "/x", "type": "list", "entity": "x"}],
                "entities": {"x": {"fields": []}}}
        result = self._run(author_record_maquettes_if_enabled(plan, str(tmp_path)))
        assert result == []

    def test_authors_one_per_record_page_with_correct_mode(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        _write_profile(tmp_path, on=True)
        import services.record_maquette as rm
        monkeypatch.setattr(rm, "author_record_maquette", _stub_author("record"))
        result = self._run(author_record_maquettes_if_enabled(_basic_plan(), str(tmp_path)))
        assert result is not None
        # Plan has 3 record pages: /sessions/new (form→create), /bookings/[id]
        # (detail→view), /sessions/[id]/edit (edit→edit).
        assert len(result) == 3
        by_route = {r["route"]: r for r in result}
        assert by_route["/sessions/new"]["mode"] == "create"
        assert by_route["/bookings/[id]"]["mode"] == "view"
        assert by_route["/sessions/[id]/edit"]["mode"] == "edit"

    def test_writes_file_at_expected_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        _write_profile(tmp_path, on=True)
        import services.record_maquette as rm
        monkeypatch.setattr(rm, "author_record_maquette", _stub_author("record"))
        self._run(author_record_maquettes_if_enabled(_basic_plan(), str(tmp_path)))
        p = tmp_path / "src" / "contracts" / "record-maquettes.json"
        assert p.is_file()

    def test_llm_exception_does_not_stop_batch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        _write_profile(tmp_path, on=True)

        async def _flaky(plan, entity, route, *, mode="edit", brief_text=None,
                         query_fn=None, timeout_seconds=45.0):  # noqa: ARG001
            if "edit" in route:
                raise RuntimeError("boom")
            from services.record_maquette import RecordMaquette
            return RecordMaquette.from_dict({
                "entity": entity, "route": route, "mode": mode,
                "section_grouping": [{"label": "Info", "fields": ["title"]}],
            })

        import services.record_maquette as rm
        monkeypatch.setattr(rm, "author_record_maquette", _flaky)
        result = self._run(author_record_maquettes_if_enabled(_basic_plan(), str(tmp_path)))
        # One raised, two succeeded.
        assert result is not None
        assert len(result) == 2

    def test_caps_at_max_record_maquettes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        _write_profile(tmp_path, on=True)
        n = _MAX_RECORD_MAQUETTES + 3
        pages = [{"route": f"/x{i}/new", "type": "form", "entity": "x"} for i in range(n)]
        plan = {"pages": pages, "entities": {"x": {"fields": []}}}
        import services.record_maquette as rm
        monkeypatch.setattr(rm, "author_record_maquette", _stub_author("record"))
        result = self._run(author_record_maquettes_if_enabled(plan, str(tmp_path)))
        assert result is not None
        assert len(result) == _MAX_RECORD_MAQUETTES


# ─────────────────────────── existing dashboard still works ────────────


class TestDashboardMaquetteAuthoringUnchanged:
    """Sanity — the dashboard author still gates on the same flag and
    the two new authors don't disturb it."""

    def _run(self, coro):
        return asyncio.run(coro)

    def test_dashboard_author_still_gated_off(self, tmp_path: Path):
        _write_profile(tmp_path, on=False)
        from services.plan_finalize import author_dashboard_maquette_if_enabled
        result = self._run(author_dashboard_maquette_if_enabled(_basic_plan(), str(tmp_path)))
        assert result is None

    def test_dashboard_author_still_gated_on(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        _write_profile(tmp_path, on=True)

        # Stub the dashboard author entry-point.
        async def _fake_dash(plan, brief_text=None,
                              query_fn=None, timeout_seconds=60.0):  # noqa: ARG001
            from services.dashboard_maquette import DashboardMaquette
            return DashboardMaquette.from_dict({
                "kpis": [{"label": "K", "entity": "sessions", "op": "count"}],
            })

        import services.dashboard_maquette as dm
        monkeypatch.setattr(dm, "author_dashboard_maquette", _fake_dash)
        from services.plan_finalize import author_dashboard_maquette_if_enabled
        result = self._run(author_dashboard_maquette_if_enabled(_basic_plan(), str(tmp_path)))
        assert result is not None
        # And the dashboard maquette file was written.
        p = tmp_path / "src" / "contracts" / "dashboard-maquette.json"
        assert p.is_file()
