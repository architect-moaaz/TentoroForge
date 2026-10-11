"""The application is handed over with a card that says what is proven, what
is not yet, and what the checks could not try — and only the second is
ever sent to repair.

Before this, "built" meant the tree compiled; the checks that could say more
held the build turn for an hour and a half and counted their own browser
timeouts as faults of the application (ECom L2, 2026-10-11)."""
from __future__ import annotations

import json
from pathlib import Path

from services.blueprint import scorecard as sc

DOC = {
    "version": 3,
    "pages": [{"id": "PAGE-001", "name": "Catalogue", "route": "/"},
              {"id": "PAGE-002", "name": "Checkout", "route": "/checkout"},
              {"id": "PAGE-003", "name": "Old", "route": "/old", "status": "REMOVED"}],
    "workflows": [{"id": "FLOW-001", "name": "Place order", "trigger": {"type": "manual"}, "steps": []}],
    "runtime": {"pages": {"planned": 2, "served": 1, "missing": ["/checkout"], "status": "short"}},
}


class _Svc:
    def __init__(self, out: Path, doc: dict):
        self.out, self.doc, self.saves = out, json.loads(json.dumps(doc)), 0

    def save(self) -> None:
        self.saves += 1
        (self.out / "current.json").write_text(json.dumps(self.doc))


def test_the_boot_card_knows_what_the_build_could_not_finish(tmp_path):
    svc = _Svc(tmp_path, DOC)
    card = sc.seed_from_boot(svc)
    pages = card["criteria"]["pages"]
    assert (pages["total"], pages["green"]) == (2, 1)
    assert pages["red"][0]["id"] == "PAGE-002" and "not served" in pages["red"][0]["why"]
    assert card["status"] == "checking" and card["version"] == 3
    assert all(card["criteria"][c]["untried"] for c in sc.CRITERIA)      # nothing else tried yet
    assert svc.doc["runtime"]["scorecard"] is card and svc.saves == 1
    assert card["criteria"]["logic"]["total"] == 1                          # one process to run


def test_a_check_writes_its_criterion_and_untried_is_never_a_red(tmp_path):
    svc = _Svc(tmp_path, DOC)
    sc.seed_from_boot(svc)
    sc.write(svc, "routes", green=5,
             red=[sc.item("PAGE-002:Buyer", "Checkout as Buyer", "answers 403", cause="PAGE-002")],
             untried=[sc.item("PAGE-001:Guest", "Catalogue signed out", "the check's browser failed", "PAGE-001")])
    routes = sc.read(svc.doc)["criteria"]["routes"]
    assert (routes["total"], routes["green"], len(routes["red"]), len(routes["untried"])) == (7, 1 + 4, 1, 1)
    reds = sc.reds(svc.doc)
    assert [r["criterion"] for r in reds] == ["pages", "routes"]
    assert all("browser" not in r["why"] for r in reds)
    assert sc.summary(svc.doc)["routes"] == {"total": 7, "green": 5, "red": 1, "untried": 1}


def test_the_card_reads_as_a_table_and_a_fix_as_one_line(tmp_path):
    svc = _Svc(tmp_path, DOC)
    sc.seed_from_boot(svc)
    said = sc.opening(svc.doc)
    assert "| Criterion | Proven | Not yet | Could not try |" in said
    assert "| Pages built and working | 1 of 2 | 1 |" in said
    assert "| Routes answer as declared | — | — | not checked yet |" in said
    line = sc.green_line("pages", {"id": "PAGE-002", "label": "Checkout"}, "Proceed to checkout now opens the checkout")
    assert line == "Checkout: fixed — Proceed to checkout now opens the checkout"
    sc.set_status(svc, "done", fix={"turns": 2, "yield": [1, 0], "stopped": "yield"})
    card = sc.read(svc.doc)
    assert card["status"] == "done" and card["fix"] == {"turns": 2, "yield": [1, 0], "stopped": "yield"}
    closing = sc.closing(svc.doc)
    assert closing.startswith("Checks finished: pages built and working 1 of 2")
    assert "Still not right (1): Checkout" in closing


def test_the_card_is_what_the_contract_declares(tmp_path):
    schema = json.loads((Path(__file__).parents[2] / "contracts" / "blueprint.schema.json").read_text())
    runtime = schema["properties"]["runtime"]
    assert "scorecard" in runtime["properties"]
    card = runtime["properties"]["scorecard"]["properties"]
    assert set(card) >= {"status", "criteria", "fix"}
    assert "untried" in runtime["properties"]["check"]["properties"]
