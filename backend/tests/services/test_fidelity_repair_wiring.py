"""The critique must reach a repair, not just a log line.

Covers the seam that makes fidelity scoring more than advisory: findings
collected across every scored page, routed once, and reported honestly —
including what could not be fixed.
"""
import asyncio
import json

import pytest


def _run(agen):
    async def _collect():
        return [e async for e in agen]
    return asyncio.run(_collect())


def _payload(events, kind):
    return [json.loads(e["data"]) for e in events if e.get("event") == kind]


def _logs(events):
    return [json.loads(e["data"])["text"] for e in events if e.get("event") == "log"]


@pytest.fixture
def fake_run(monkeypatch):
    """Replace the Playwright/vision runner with canned score events."""
    def _install(score_events):
        async def _fake(**kwargs):
            for e in score_events:
                yield e
        import services.fidelity_runner as fr
        monkeypatch.setattr(fr, "run_fidelity_scoring", _fake)
    return _install


def _score(route, findings, page_type="list"):
    return {"type": "score", "page": route, "page_type": page_type,
            "domain": "saas", "score_0_to_10": 6.5, "color_match_score": 7,
            "layout_score": 6, "density_score": 6, "polish_score": 7,
            "qualitative_notes": "notes", "findings": findings}


def _f(t, route):
    return {"type": t, "route": route, "detail": "d", "source": "fidelity"}


class TestWiring:
    def test_findings_from_every_page_are_collected_and_routed_once(
            self, monkeypatch, fake_run, tmp_path):
        monkeypatch.setenv("FIDELITY_SCORING_ENABLED", "1")
        fake_run([
            _score("/products", [_f("density_off", "/products")]),
            _score("/orders",   [_f("density_off", "/orders"),
                                 _f("bare_surface", "/orders")]),
        ])
        calls = []
        import services.visual_findings as vf
        monkeypatch.setattr(vf, "_default_fixers", lambda: {
            "density_off":  lambda d: (calls.append("density"), 2)[1],
            "bare_surface": lambda d: (calls.append("surface"), 1)[1],
        })

        from routers.generate import _stream_fidelity_scoring
        events = _run(_stream_fidelity_scoring(str(tmp_path), {"pages": []}))

        # Two pages raised density_off; the app-wide pass runs once.
        assert calls == ["density", "surface"]
        rep = _payload(events, "fidelity_repair")[0]
        assert rep["fixed"] == 3
        assert sorted(rep["ran"]) == ["bare_surface", "density_off"]
        assert rep["unhandled"] == []

    def test_global_findings_are_reported_not_applied(
            self, monkeypatch, fake_run, tmp_path):
        monkeypatch.setenv("FIDELITY_SCORING_ENABLED", "1")
        fake_run([_score("/products", [_f("palette_mismatch", "/products")])])
        import services.visual_findings as vf
        monkeypatch.setattr(vf, "_default_fixers", lambda: {})

        from routers.generate import _stream_fidelity_scoring
        events = _run(_stream_fidelity_scoring(str(tmp_path), {"pages": []}))

        rep = _payload(events, "fidelity_repair")[0]
        assert rep["fixed"] == 0
        assert [f["type"] for f in rep["unhandled"]] == ["palette_mismatch"]
        # And the user is told WHY it wasn't touched.
        assert any("global — needs a design change" in t for t in _logs(events))

    def test_a_clean_run_emits_no_repair_event(
            self, monkeypatch, fake_run, tmp_path):
        # An empty findings array is the common answer on a good page. It must
        # not produce a repair event, or every build looks like it had defects.
        monkeypatch.setenv("FIDELITY_SCORING_ENABLED", "1")
        fake_run([_score("/products", [])])
        from routers.generate import _stream_fidelity_scoring
        events = _run(_stream_fidelity_scoring(str(tmp_path), {"pages": []}))
        assert _payload(events, "fidelity_repair") == []

    def test_disabled_by_default_does_nothing(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FIDELITY_SCORING_ENABLED", raising=False)
        from routers.generate import _stream_fidelity_scoring
        assert _run(_stream_fidelity_scoring(str(tmp_path), {"pages": []})) == []
