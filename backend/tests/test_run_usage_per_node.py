"""QA D-06: per-stage tokens + cost must be reachable, not only the aggregate."""
from services.blueprint.executors import RunUsage, Usage


def test_summary_exposes_per_node_cost_and_tokens():
    u = RunUsage()
    u.record(node="data_model", agent="a", usage=Usage(input_tokens=100, output_tokens=50), elapsed_s=2.0)
    u.record(node="design_system", agent="b", usage=Usage(input_tokens=200, output_tokens=80), elapsed_s=3.0)
    s = u.summary()
    # aggregate is still there
    assert s["nodes"] == 2 and s["tokens"] == 430
    # and now the per-stage breakdown a caller can read from the SSE payload
    assert [e["node"] for e in s["perNode"]] == ["data_model", "design_system"]
    first = s["perNode"][0]
    assert first["tokens"] == 150 and first["inputTokens"] == 100 and first["outputTokens"] == 50
    assert "cost_usd" in first and "elapsed_s" in first
