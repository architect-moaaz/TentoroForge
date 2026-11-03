"""Build-usage ledger + admin summary aggregates."""
import json

import pytest

from services import build_usage


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "usage.jsonl"
    monkeypatch.setenv("FORGE_USAGE_LOG", str(path))
    return path


def test_record_and_read(ledger):
    build_usage.record_usage(
        project="app1", agent="Planner", model="claude-sonnet-4-5",
        usage={"input_tokens": 1000, "output_tokens": 500,
               "cache_read_input_tokens": 200},
        sdk_cost_usd=0.0, duration_ms=1200, num_turns=3,
    )
    rows = build_usage.read_ledger()
    assert len(rows) == 1
    r = rows[0]
    assert r["project"] == "app1" and r["agent"] == "Planner"
    assert r["input_tokens"] == 1000 and r["cache_read_tokens"] == 200
    assert r["est_cost_usd"] > 0  # estimated because sdk cost was 0


def test_estimate_pricing_by_model_family():
    usage = {"input_tokens": 1_000_000, "output_tokens": 0}
    # $5/Mtok, not $15. The $15/$75 row belongs to Claude 3 Opus; pricing the
    # modern family by it overstated every Opus call threefold, which is the
    # bug the substring table's own comment records. This test asserted the
    # overstatement, so the number every cost report is read against was
    # guarded at three times its real value.
    assert build_usage.estimate_cost_usd("claude-opus-4", usage) == 5.0
    assert build_usage.estimate_cost_usd("claude-opus-5", usage) == 5.0
    # …and the old row is still exact for the model it actually applies to.
    assert build_usage.estimate_cost_usd("claude-3-opus-20240229", usage) == 15.0
    assert build_usage.estimate_cost_usd("claude-sonnet-4-5", usage) == 3.0
    assert build_usage.estimate_cost_usd("claude-haiku-4-5", usage) == 1.0
    # unknown model → sonnet-class default
    assert build_usage.estimate_cost_usd("mystery", usage) == 3.0


def test_zero_token_synthetic_results_skipped(ledger):
    build_usage.record_usage(project="app1", agent="x", usage={}, sdk_cost_usd=0)
    assert build_usage.read_ledger() == []


def test_sdk_cost_wins_over_estimate(ledger):
    build_usage.record_usage(
        project="a", agent="x", model="claude-sonnet-4-5",
        usage={"input_tokens": 10, "output_tokens": 10}, sdk_cost_usd=1.25,
    )
    s = build_usage.usage_summary()
    assert s["totals"]["cost_usd"] == 1.25
    assert s["totals"]["estimated_events"] == 0


def test_summary_aggregates(ledger):
    for proj, agent, out in [("a", "Planner", 100), ("a", "Pages", 300),
                             ("b", "Planner", 200)]:
        build_usage.record_usage(
            project=proj, agent=agent, model="claude-sonnet-4-5",
            usage={"input_tokens": 1000, "output_tokens": out},
        )
    s = build_usage.usage_summary()
    assert s["totals"]["events"] == 3
    assert s["totals"]["projects"] == 2
    assert s["totals"]["input_tokens"] == 3000
    # rows sorted by cost desc; project 'a' has 2 events → costs more
    assert s["by_project"][0]["project"] == "a"
    agents = {r["agent"] for r in s["by_agent"]}
    assert agents == {"Planner", "Pages"}
    assert len(s["daily"]) == 1  # all today


def test_record_never_raises_on_bad_path(monkeypatch):
    monkeypatch.setenv("FORGE_USAGE_LOG", "/dev/null/impossible/x.jsonl")
    build_usage.record_usage(project="a", agent="x",
                             usage={"input_tokens": 1})  # must not raise


def test_malformed_ledger_lines_skipped(ledger):
    ledger.write_text('{"project": "a", "agent": "x", "input_tokens": 5, '
                      '"output_tokens": 1, "sdk_cost_usd": 0, '
                      '"est_cost_usd": 0.1, "ts": 1700000000}\nNOT JSON\n')
    assert len(build_usage.read_ledger()) == 1
    assert build_usage.usage_summary()["totals"]["events"] == 1


def test_the_blueprint_tracker_writes_to_the_ledger_the_environment_names(ledger):
    """`RunUsage.record` mirrors every call into the platform ledger. Under test
    that ledger must be the session's own file, never `data/build-usage.jsonl`:
    the executor fakes report round token counts, and 1,250 of those rows had
    accumulated in the real file as $108 of spend that never happened."""
    from services.blueprint.executors import RunUsage, Usage

    before = build_usage._DEFAULT_LEDGER.stat().st_size if build_usage._DEFAULT_LEDGER.exists() else 0
    RunUsage().record(node="data_model", agent="data_model",
                      usage=Usage("claude-opus-5", 20000, 4000), elapsed_s=1.0)

    rows = [json.loads(l) for l in ledger.read_text().splitlines()]
    assert [r["project"] for r in rows] == ["blueprint"]
    after = build_usage._DEFAULT_LEDGER.stat().st_size if build_usage._DEFAULT_LEDGER.exists() else 0
    assert after == before, "a test wrote into the real ledger"


def test_the_suite_never_points_at_the_real_ledger():
    """Set once for the session in conftest, before any import. A test that
    forgets the `ledger` fixture must still land in the temp file."""
    import os

    assert os.environ.get("FORGE_USAGE_LOG"), "conftest no longer redirects the ledger"
    assert build_usage._ledger_path() != build_usage._DEFAULT_LEDGER
