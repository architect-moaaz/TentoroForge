"""What the engine writes must satisfy the contract it validates against.

`runtime.build` is in a generated Blueprint right now and the contract forbids
it — `runtime` permits framework, language, nodeVersion, packageManager and
sets additionalProperties: false. The document was written by the engine and is
rejected by the engine, so that project can never be updated again: the next
`svc.save()` raises BlueprintInvalid and Smith's move dies before it starts.

Both sides had tests. `blueprint.schema.json` is emitted from Zod and checked
for staleness; the projections have tests for what they produce. Nothing
checked that a document the projections actually wrote still validates — the
same gap that let the A2UI catalog drift from the Zod components, one layer up.

Every Blueprint under `output/` is a real artifact of a real run, so this reads
them rather than a fixture. A fixture would be a third statement of the same
shape and would agree with the schema by construction, which is exactly the
agreement that needs testing.
"""

import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_OUTPUT = _ROOT / "output"


def _generated() -> list[Path]:
    if not _OUTPUT.is_dir():
        return []
    return sorted(_OUTPUT.glob("*/.forge/blueprint/current.json"))


@pytest.mark.parametrize(
    "path", _generated(), ids=lambda p: p.parents[2].name,
)
def test_a_generated_blueprint_still_satisfies_the_contract(path):
    """A document the engine wrote and the engine rejects is unwritable: the
    next save raises, so the application can never be changed again."""
    from services.blueprint.service import CONTRACT_PATH

    import jsonschema

    schema = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    doc = json.loads(path.read_text(encoding="utf-8"))

    errors = sorted(
        jsonschema.Draft202012Validator(schema).iter_errors(doc),
        key=lambda e: list(e.path),
    )
    assert not errors, "\n".join(
        f"{'.'.join(map(str, e.path)) or '<root>'}: {e.message}"
        for e in errors[:6]
    )


def test_there_is_something_to_check():
    """A guard on the guard: no generated Blueprints would pass silently."""
    if not _generated():
        pytest.skip("no generated applications in output/")
