"""§26 — the build plan as a countable forecast, not just an order.

The PRD's example is a set of numbers::

    18 pages · 12 entities · 7 workflows · 24 business rules
    32 APIs · 6 roles · 3 integrations · 104 expected tests

with agent dependencies as an additional field, not the whole of it. The
distinction matters after the run rather than before it: a node list says what
*will happen*, a forecast says what should *exist afterwards*, and only the
second can be checked against the result.

Everything here is counted or derived from the Blueprint. Nothing is asked of a
model — §116 again, and a forecast an agent guessed at would be checking the
run against its own optimism.
"""
from __future__ import annotations

from typing import Any


def _live(items: Any) -> list[dict]:
    return [i for i in (items or []) if i.get("status") != "DEPRECATED"]


#: What one page is worth in tests, roughly. §77 wants a test per requirement
#: and per workflow branch; this is the coarse version, honest about being an
#: estimate rather than a promise.
TESTS_PER_PAGE = 2
TESTS_PER_WORKFLOW = 3


def forecast(doc: dict) -> dict[str, int]:
    """What the finished application should contain, counted from the Blueprint."""
    data = doc.get("data") or {}
    pages = _live(doc.get("pages"))
    workflows = _live(doc.get("workflows"))
    entities = _live(data.get("entities"))

    counts = {
        "requirements": len(_live(doc.get("requirements"))),
        "pages": len(pages),
        "entities": len(entities),
        "workflows": len(workflows),
        "businessRules": len(_live(doc.get("businessRules"))),
        "apis": len(_live(doc.get("apis"))),
        "roles": len(_live(doc.get("roles"))),
        "integrations": len(_live(doc.get("integrations"))),
    }
    # Tests are the one figure that does not exist yet at planning time, so it
    # is labelled as expected rather than counted.
    counts["expectedTests"] = (
        len(pages) * TESTS_PER_PAGE + len(workflows) * TESTS_PER_WORKFLOW
    )
    return counts


def render(counts: dict[str, int]) -> str:
    """The §26 shape, for a human reading a plan before approving it."""
    label = {
        "requirements": "requirements", "pages": "pages", "entities": "entities",
        "workflows": "workflows", "businessRules": "business rules",
        "apis": "APIs", "roles": "roles", "integrations": "integrations",
        "expectedTests": "expected tests",
    }
    return "\n".join(f"{counts[k]:>4} {label[k]}" for k in label if counts.get(k))


def compare(planned: dict[str, int], doc: dict) -> dict[str, dict]:
    """Forecast against outcome — what a plan is *for*.

    Reported rather than enforced: a run that produces nineteen pages where
    eighteen were forecast has not failed, but the difference is worth seeing.
    A run that produces two has.
    """
    actual = forecast(doc)
    out: dict[str, dict] = {}
    for key, want in planned.items():
        got = actual.get(key, 0)
        if want != got:
            out[key] = {"planned": want, "actual": got, "delta": got - want}
    return out
