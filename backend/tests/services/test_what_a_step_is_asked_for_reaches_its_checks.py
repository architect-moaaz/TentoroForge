"""What a build step is asked to write reaches the checks that judge it.

Refund And Chargeback (0qtb9jiy, forge-v3 2026-10-20) and three builds before
it were refused for restricted pages that named no roles. The page writer was
asked for `users`, the check demanded `users`, and between the two
`pin_page_set` kept a fixed list of page fields that did not include it — so
the writer's answer never reached the check, and asking again could not help.
Each half was tested; the path between them was not. This is that path.
"""
from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from types import SimpleNamespace

from services.blueprint import agent_contract
from services.blueprint.executors import NODE_TASKS, pin_page_set

SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "blueprint.schema.json").read_text())
PAGE_FIELDS = set(SCHEMA["properties"]["pages"]["items"]["properties"])
#: The checks that judge the page SET — the declaration `page_contracts`
#: writes and `pin_page_set` cleans. A check of a page's content judges the
#: later contract step, whose reply is not cleaned this way.
PAGE_SET_CHECKS = (agent_contract.check_page_access, agent_contract.check_role_doors)


def _named(text: str) -> set[str]:
    """Page fields named in backticks: `users`, `access: "role_restricted"`."""
    return {m for m in re.findall(r"`([A-Za-z]+)", text) if m in PAGE_FIELDS}


def _survivors() -> set[str]:
    """The page fields `pin_page_set` keeps, found by running it on a page
    that has every one of them."""
    body = {f: "x" for f in PAGE_FIELDS}
    body["sections"], body["data"] = [], {}
    result = SimpleNamespace(proposals=[SimpleNamespace(section="pages", body=body)])
    pin_page_set(result)
    return set(result.proposals[0].body)


def test_every_page_field_the_page_set_is_asked_for_survives_to_its_checks():
    asked = _named(NODE_TASKS["page_contracts"])
    assert "users" in asked and "access" in asked  # the brief still asks for them
    lost = asked - _survivors()
    assert not lost, f"page_contracts is asked for {sorted(lost)} and pin_page_set drops them"


def test_every_page_field_a_page_set_check_demands_survives_to_it():
    demanded = set().union(*(_named(inspect.getsource(c)) for c in PAGE_SET_CHECKS))
    assert "users" in demanded
    lost = demanded - _survivors()
    assert not lost, f"a page-set check demands {sorted(lost)} and pin_page_set drops them"


def test_a_page_set_check_never_demands_what_the_writer_is_not_asked_for():
    """A check that refuses for a field the brief never mentions is a build
    that can only fail: the author has no way to know to write it."""
    demanded = set().union(*(_named(inspect.getsource(c)) for c in PAGE_SET_CHECKS))
    unasked = demanded - _named(NODE_TASKS["page_contracts"])
    assert not unasked, f"page-set checks demand {sorted(unasked)}, which the page_contracts brief never asks for"
