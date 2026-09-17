"""Whatever the assemble node writes to `runtime`, the contract declares first.

THIS HAS SHIPPED THREE TIMES. `runtime.build`, then `runtime.placeholders`,
then `runtime.boot`: each time the node that assembles the application wrote a
field the Blueprint contract did not declare, `additionalProperties: false`
refused it, and every application generated from then on was unmodifiable —
the next `save()` raised, so Smith's first change died before it started.

The first two are recorded in comments on the contract itself. The third
reached UAT anyway, because a comment is not a check. This is the check: it
reads which keys the node writes and requires each one in the schema the
Python side validates against.
"""
import inspect
import json
import re
from pathlib import Path

from services.blueprint import orchestrator

CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "blueprint.schema.json"


def _written_runtime_keys() -> set[str]:
    src = inspect.getsource(orchestrator._project_assemble)
    return set(re.findall(r'runtime\[\s*"([A-Za-z_]+)"\s*\]\s*=', src))


def test_the_node_writes_runtime_fields():
    """The check below is only as good as this reading; if it finds nothing,
    the pattern has drifted and the guarantee is gone silently."""
    keys = _written_runtime_keys()
    assert {"build", "pages"} <= keys, keys


def test_every_key_it_writes_is_in_the_contract():
    schema = json.loads(CONTRACT.read_text(encoding="utf-8"))
    runtime = schema["properties"]["runtime"]
    declared = set((runtime.get("properties") or {}))
    assert runtime.get("additionalProperties") is False, (
        "if the contract stops refusing unknown keys this test proves nothing")
    missing = _written_runtime_keys() - declared
    assert not missing, (
        f"the assemble node writes runtime.{sorted(missing)} and the contract "
        f"does not declare it — every generated application becomes "
        f"unmodifiable on its next save. Declare it in packages/schema first, "
        f"then `npm run emit:blueprint-schema`.")
