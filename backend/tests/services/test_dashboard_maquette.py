"""Tests for the dashboard maquette LLM step + parsing."""
from __future__ import annotations

import json

import pytest

from services.dashboard_maquette import (
    ActivitySpec,
    ChartSpec,
    DashboardMaquette,
    HeroSpec,
    KPISpec,
    author_dashboard_maquette,
    meets_richness_contract,
)


_MINIMAL_PLAN = {
    "module_name": "Wellness Studio",
    "domain": "wellness",
    "entities": {
        "session": {"fields": [{"name": "date", "type": "date"}, {"name": "instructor_id", "type": "uuid"}]},
        "member": {"fields": [{"name": "status", "type": "text"}, {"name": "joined_at", "type": "timestamp"}]},
        "booking": {"fields": [{"name": "createdAt", "type": "timestamp"}, {"name": "session_id", "type": "uuid"}]},
        "payment": {"fields": [{"name": "amount", "type": "numeric"}, {"name": "createdAt", "type": "timestamp"}]},
    },
}


class TestFromDict:
    def test_parses_full_maquette(self):
        raw = {
            "kpis": [
                {"label": "Classes Today", "entity": "session", "op": "count",
                 "filter": "date=today"},
                {"label": "Active Members", "entity": "member", "op": "count",
                 "filter": "status=active"},
                {"label": "Week Revenue", "entity": "payment", "op": "sum",
                 "field": "amount", "trend_window": "week"},
            ],
            "primary_chart": {
                "kind": "bar", "title": "Bookings this week",
                "entity": "booking", "group_by": "createdAt",
                "aggregate": "count", "window": "week",
            },
            "activity": {"entity": "booking", "title": "Latest bookings",
                         "limit": 5, "order_by": "createdAt"},
            "hero": {"photo_subject": "yoga studio at golden hour",
                     "greeting": "Welcome back — {n} classes today"},
        }
        m = DashboardMaquette.from_dict(raw)
        assert len(m.kpis) == 3
        assert m.kpis[0].label == "Classes Today"
        assert m.kpis[0].entity == "session"
        assert m.kpis[0].op == "count"
        assert m.kpis[2].field == "amount"
        assert m.primary_chart is not None
        assert m.primary_chart.kind == "bar"
        assert m.activity is not None
        assert m.activity.entity == "booking"
        assert m.hero is not None
        assert "golden hour" in m.hero.photo_subject

    def test_drops_kpi_without_required_fields(self):
        raw = {"kpis": [
            {"label": "Good", "entity": "session", "op": "count"},
            {"label": "Bad — no op", "entity": "session"},
            {"label": "Bad — invalid op", "entity": "session", "op": "xyz"},
        ]}
        m = DashboardMaquette.from_dict(raw)
        assert len(m.kpis) == 1
        assert m.kpis[0].label == "Good"

    def test_drops_chart_missing_required_keys(self):
        raw = {"primary_chart": {"kind": "bar", "title": "..."}}
        m = DashboardMaquette.from_dict(raw)
        assert m.primary_chart is None

    def test_handles_non_dict_input(self):
        assert DashboardMaquette.from_dict(None).kpis == []  # type: ignore
        assert DashboardMaquette.from_dict("string").kpis == []  # type: ignore


class TestRichnessContract:
    def test_full_maquette_meets_contract(self):
        m = DashboardMaquette(
            kpis=[
                KPISpec("A", "e", "count"),
                KPISpec("B", "e", "count"),
                KPISpec("C", "e", "count"),
            ],
            primary_chart=ChartSpec("bar", "t", "e", "g"),
            activity=ActivitySpec("e", "recent"),
            hero=HeroSpec("subj", "hi"),
        )
        assert meets_richness_contract(m) == []

    def test_missing_hero_reported(self):
        m = DashboardMaquette(
            kpis=[KPISpec("A", "e", "count"), KPISpec("B", "e", "count"),
                  KPISpec("C", "e", "count")],
            primary_chart=ChartSpec("bar", "t", "e", "g"),
            activity=ActivitySpec("e", "recent"),
        )
        missing = meets_richness_contract(m)
        assert "hero" in missing

    def test_too_few_kpis_reported(self):
        m = DashboardMaquette(
            kpis=[KPISpec("A", "e", "count")],
            primary_chart=ChartSpec("bar", "t", "e", "g"),
            activity=ActivitySpec("e", "recent"),
            hero=HeroSpec("s", "h"),
        )
        missing = meets_richness_contract(m)
        assert any("kpi_row" in m for m in missing)

    def test_relax_min_kpis(self):
        m = DashboardMaquette(
            kpis=[KPISpec("A", "e", "count")],
            primary_chart=ChartSpec("bar", "t", "e", "g"),
            activity=ActivitySpec("e", "recent"),
            hero=HeroSpec("s", "h"),
        )
        assert meets_richness_contract(m, min_kpis=1) == []


class TestAuthorDashboardMaquette:
    @pytest.mark.asyncio
    async def test_uses_injected_query_fn(self):
        captured: dict = {}

        async def fake(system: str, user: str) -> str:
            captured["system"] = system
            captured["user"] = user
            return json.dumps({
                "kpis": [
                    {"label": "Sessions Today", "entity": "session", "op": "count"},
                    {"label": "Members", "entity": "member", "op": "count"},
                    {"label": "Revenue", "entity": "payment", "op": "sum", "field": "amount"},
                ],
                "primary_chart": {
                    "kind": "bar", "title": "Weekly bookings",
                    "entity": "booking", "group_by": "createdAt", "aggregate": "count",
                },
                "activity": {"entity": "booking", "title": "Latest", "limit": 5},
                "hero": {"photo_subject": "yoga studio at sunrise",
                         "greeting": "Good morning"},
            })

        m = await author_dashboard_maquette(_MINIMAL_PLAN, brief_text="wellness studio", query_fn=fake)
        assert m is not None
        assert len(m.kpis) == 3
        assert m.primary_chart is not None
        assert "wellness studio" in captured["user"]
        # Entities from the plan appear in the prompt.
        assert "session" in captured["user"]
        assert "payment" in captured["user"]

    @pytest.mark.asyncio
    async def test_drops_kpi_referencing_unknown_entity(self):
        async def fake(system: str, user: str) -> str:
            return json.dumps({
                "kpis": [
                    {"label": "OK", "entity": "session", "op": "count"},
                    {"label": "Hallucinated", "entity": "made_up", "op": "count"},
                ],
            })

        m = await author_dashboard_maquette(_MINIMAL_PLAN, query_fn=fake)
        assert m is not None
        assert len(m.kpis) == 1
        assert m.kpis[0].entity == "session"

    @pytest.mark.asyncio
    async def test_returns_none_on_llm_exception(self):
        async def boom(system: str, user: str) -> str:
            raise RuntimeError("provider down")

        assert await author_dashboard_maquette(_MINIMAL_PLAN, query_fn=boom) is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_entities(self):
        plan = {"module_name": "X", "domain": "x", "entities": {}}
        assert await author_dashboard_maquette(plan) is None

    @pytest.mark.asyncio
    async def test_returns_none_on_unparseable_response(self):
        async def prose(system: str, user: str) -> str:
            return "Sorry, I can't help with that."

        assert await author_dashboard_maquette(_MINIMAL_PLAN, query_fn=prose) is None

    @pytest.mark.asyncio
    async def test_strips_markdown_fence_from_response(self):
        async def fenced(system: str, user: str) -> str:
            payload = {"kpis": [{"label": "OK", "entity": "session", "op": "count"}]}
            return f"```json\n{json.dumps(payload)}\n```"

        m = await author_dashboard_maquette(_MINIMAL_PLAN, query_fn=fenced)
        assert m is not None
        assert len(m.kpis) == 1


class TestSystemPromptGuardrails:
    def test_prompt_forbids_prose_output(self):
        from services.dashboard_maquette import _build_system_prompt
        p = _build_system_prompt()
        assert "JSON only" in p or "Return JSON only" in p
        assert "No markdown" in p or "no markdown" in p or "No prose" in p or "no prose" in p

    def test_prompt_bans_auth_entities(self):
        from services.dashboard_maquette import _build_system_prompt
        p = _build_system_prompt()
        assert "audit" in p.lower()
        assert "notification" in p.lower()

    def test_prompt_lists_the_shape(self):
        from services.dashboard_maquette import _build_system_prompt
        p = _build_system_prompt()
        assert "kpis" in p
        assert "primary_chart" in p
        assert "activity" in p
        assert "hero" in p
