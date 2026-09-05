"""Every field the Figma branch puts on a layout row must be declared.

The Blueprint contract is `additionalProperties: false` on `pageLayouts[]`, and
that is right — an undeclared field is a fact the rest of the pipeline cannot
see. It also means a producer that adds a field without declaring it takes
every row down with it: the executor began writing `canvas` (so the renderer
could scale a frame) and fifteen of fifteen pages were refused with "'canvas'
was unexpected", and `preview` failed behind them with nothing to build.

Pinned against the generated JSON, not the TypeScript, because the JSON is
what the validator reads.
"""
import json
from pathlib import Path

import jsonschema

CONTRACT = json.load(open(Path(__file__).resolve().parents[2] / "contracts" / "blueprint.schema.json"))
ROW = CONTRACT["properties"]["pageLayouts"]["items"]

# THE ROW'S SUB-SCHEMA POINTS AT THE DOCUMENT ROOT — `page` is
# `$ref: #/properties/modules/…/pages/items` — so validating the item in
# isolation raises PointerToNowhere. A validator built from the whole contract
# and narrowed to the row keeps the root resolver.
_ROW_VALIDATOR = jsonschema.validators.validator_for(CONTRACT)(CONTRACT).evolve(schema=ROW)


def _check(row):
    errors = sorted(_ROW_VALIDATOR.iter_errors(row), key=lambda e: e.path)
    if errors:
        raise jsonschema.ValidationError("; ".join(e.message for e in errors))


def _row(**extra):
    return {"page": "PAGE-001", "root": {"type": "Container", "props": {}, "children": []},
            "composedBy": "figma", "dataSources": [], "rationale": "built from Figma frame 1:2 (§48)",
            "requirements": [], **extra}


def test_a_figma_row_with_a_canvas_is_legal():
    _check(_row(canvas={"width": 3902.0, "height": 1975.0}))


def test_a_row_without_a_canvas_is_still_legal():
    _check(_row())


def test_a_canvas_must_have_a_size():
    import pytest
    with pytest.raises(jsonschema.ValidationError):
        _check(_row(canvas={"width": 0, "height": 1975.0}))


def test_an_undeclared_field_is_still_refused():
    """The contract stays closed; this test exists because of what closed
    contracts do to producers that forget."""
    import pytest
    with pytest.raises(jsonschema.ValidationError):
        _check(_row(somethingNew=1))
