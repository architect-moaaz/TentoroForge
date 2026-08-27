"""Regression test for the universal plan-normalization choke point
(Pipeline Reliability Atlas L1).

`_normalize_oneshot_plan` (+`_annotate_page_types`) convert an `entities`-DICT
plan into the `data_models`-LIST shape the pipeline consumes. They were wired
ONLY into `run_planner_oneshot` — plans entering via the interactive planner,
figma analysis, or `_extract_plan_json` were used RAW, so a raw plan expressing
entities as the `entities` DICT registered 0 entities → no schema → broken app.

`_ensure_normalized_plan` is the single choke point (called at the top of both
relay pipelines) that guarantees normalization for every ingestion path.
"""

from routers.generate import _ensure_normalized_plan


def _raw_entities_dict_plan():
    """A RAW plan (as an interactive/figma/re-extracted plan may arrive):
    entities expressed as a DICT, NO `data_models`."""
    return {
        "domain": "inventory",
        "entities": {
            "Equipment": {
                "table": "equipment",
                "fields": [
                    {"name": "id", "type": "serial"},
                    {"name": "name", "type": "varchar", "nullable": False},
                ],
            },
            "Vendor": {
                "fields": [
                    {"name": "id", "type": "serial"},
                    {"name": "name", "type": "varchar", "nullable": False},
                ],
            },
        },
        "pages": [
            {"route": "/equipment", "name": "Equipment", "entity": "Equipment"},
        ],
    }


def test_raw_entities_dict_gets_data_models_populated():
    plan = _ensure_normalized_plan(_raw_entities_dict_plan())
    models = plan.get("data_models")
    assert isinstance(models, list)
    names = {m["name"] for m in models}
    assert names == {"Equipment", "Vendor"}
    assert len(models) > 0
    # `id` field promoted to primaryKey by the oneshot normalizer.
    equip = next(m for m in models if m["name"] == "Equipment")
    id_field = next(f for f in equip["fields"] if f["name"] == "id")
    assert id_field.get("primaryKey") is True
    # Table hint preserved.
    assert equip.get("table") == "equipment"


def test_already_normalized_plan_is_idempotent():
    """A plan already carrying `data_models` (no `entities` dict) passes through
    with its entity list unchanged — re-application is a no-op."""
    normalized = {
        "domain": "inventory",
        "data_models": [
            {
                "name": "Equipment",
                "table": "equipment",
                "fields": [
                    {"name": "id", "type": "serial", "primaryKey": True},
                    {"name": "name", "type": "varchar", "nullable": False},
                ],
            },
        ],
        "pages": [
            {"route": "/equipment", "name": "Equipment", "type": "list",
             "entity": "Equipment"},
        ],
    }
    before = [dict(m) for m in normalized["data_models"]]
    out = _ensure_normalized_plan(normalized)
    assert out["data_models"] == before

    # Fully idempotent: running twice yields the same data_models.
    twice = _ensure_normalized_plan(_ensure_normalized_plan(dict(normalized)))
    assert twice["data_models"] == before


def test_non_dict_input_returned_unchanged():
    assert _ensure_normalized_plan(None) is None
    assert _ensure_normalized_plan([1, 2]) == [1, 2]
