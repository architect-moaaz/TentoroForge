# backend/tests/services/test_schema_prompt_aggregate.py
import inspect
import services.schema_prompt as sp


def test_prompt_documents_aggregate_metrics():
    """Assert the aggregate-metrics guidance constants are present in the module source."""
    src = inspect.getsource(sp)
    assert '"op": "aggregate"' in src
    assert '"metrics"' in src
    assert "monthlyRevenue" in src  # the worked example
