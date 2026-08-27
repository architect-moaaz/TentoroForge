# backend/tests/services/test_data_engine_aggregations.py
from pathlib import Path


_RUNTIME_ROOT = Path(__file__).resolve().parents[3] / "backend" / "templates" / "runtime"


def test_aggregations_module_exists():
    agg = _RUNTIME_ROOT / "data-engine" / "aggregations.ts"
    assert agg.exists()
    text = agg.read_text()
    assert "executeAggregation" in text
    assert "AggregationFn" in text
    assert "groupBy" in text


def test_saved_views_module_exists():
    sv = _RUNTIME_ROOT / "data-engine" / "saved-views.ts"
    assert sv.exists()
    text = sv.read_text()
    assert "listSavedViews" in text
    assert "createSavedView" in text
    assert "deleteSavedView" in text


def test_aggregation_supports_all_required_fns():
    text = (_RUNTIME_ROOT / "data-engine" / "aggregations.ts").read_text()
    for fn in ["count", "sum", "avg", "min", "max"]:
        assert f'"{fn}"' in text or f"'{fn}'" in text, f"missing fn: {fn}"
