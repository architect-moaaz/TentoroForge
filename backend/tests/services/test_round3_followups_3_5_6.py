"""Third tester round on tasks 3, 5, 6: a rate-limit block is capped and follows the
key; a shift with anything else attached is not a shift; a currency code beside a
number is not a currency shift; a decision's branch list is named, never dropped."""
import json
import time

import pytest

from services.smith import big_shift, field_change as fc
from tests.services.test_removing_a_field_takes_everything_that_reads_it import svc  # noqa: F401


class Boom(Exception):
    def __init__(self, status, headers):
        super().__init__("boom")
        self.response = type("R", (), {"status_code": status, "headers": headers})()


def _plan(tmp_path):
    (tmp_path / "contracts").mkdir(exist_ok=True)
    rows = [{"id": str(i), "name": f"Dish {chr(97 + i)}", "imageUrl": ""} for i in range(6)]
    p = tmp_path / "contracts/seed-plan.json"
    p.write_text(json.dumps({"tables": [{"name": "MenuItem", "seed_data": rows}]}))
    return p


def test_retry_after_is_capped_and_a_new_key_or_a_retry_lifts_the_block(tmp_path):
    from services.seed_photos import MAX_BLOCK_SECONDS, fill_seed_photos
    p = _plan(tmp_path)
    calls = []

    def get(path, params):
        calls.append(1)
        raise Boom(429, {"Retry-After": "999999"})
    r = fill_seed_photos(tmp_path, get)
    plan = json.loads(p.read_text())
    assert plan["seed_photos_blocked_until"] - time.time() <= MAX_BLOCK_SECONDS + 5
    assert "60 min" in r["why"] and "16666" not in r["why"]
    assert len(calls) == 1
    fill_seed_photos(tmp_path, get)
    assert len(calls) == 1                                                    # still blocked for the same key
    plan["seed_photos_blocked_key"] = "a-different-key"                       # the key was replaced since
    p.write_text(json.dumps(plan))
    fill_seed_photos(tmp_path, get)
    assert len(calls) == 2
    fill_seed_photos(tmp_path, get)                                           # blocked again (same key)
    assert len(calls) == 2
    fill_seed_photos(tmp_path, get, retry=True)                               # an explicit retry ignores the block
    assert len(calls) == 3


@pytest.mark.parametrize("ask", ["make it dubai centric and also add a wishlist", "make it dubai centric and add a refund button",
                                 "go dubai and hide the footer", "make this app india first and rename Orders to Sales",
                                 "change the amount to eur 5", "change the price to usd 20", "set the amount to aed 100",
                                 "show prices in USD on the product page", "change the currency column to be wider",
                                 "use euro symbols in the export file", "make the total eur 5"])
def test_a_shift_with_anything_attached_or_a_code_beside_a_number_is_ordinary(ask):
    assert big_shift.detect(ask) is None, ask


@pytest.mark.parametrize("ask,cur", [("make this app india first", "INR"), ("target the european market", "EUR"), ("target the UAE market", "AED"),
                                     ("make it centric to Dubai", "AED"), ("change everything to dirhams", "AED"),
                                     ("change the currency to AED", "AED"), ("use AED everywhere", "AED"), ("make everything euros", "EUR"),
                                     ("show prices in dirhams", "AED"), ("switch the currency to GBP", "GBP"), ("make it dubai centric please", "AED")])
def test_whole_app_phrasings_are_shifts(ask, cur):
    s = big_shift.detect(ask)
    assert s and s["currency"] == cur, ask


def test_every_branch_row_of_a_decision_is_named_and_kept(svc):
    wf = next(w for w in svc.doc["workflows"] if w["name"] == "Edit Medicine")
    wf["steps"].insert(1, {"key": "pick", "name": "Pick time", "type": "decision", "next": ["upd"],
                           "config": {"branches": [{"when": "preferredTime == 'AM'", "goto": "a"}, {"else": True, "goto": "b"}]}})
    out = fc.remove_field(svc, "Medicine", "preferredTime")
    rows = next(w for w in svc.doc["workflows"] if w["name"] == "Edit Medicine")["steps"][1]["config"]["branches"]
    assert [r.get("when") for r in rows] == ["preferredTime == 'AM'", None]               # the AM row is not deleted
    assert any("decides between" in x and "Pick time" in x for x in out["left"])
    assert "Nothing still refers to it" not in fc.summary_of("remove_field", out)
