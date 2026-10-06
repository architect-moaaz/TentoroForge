"""TCommerce (ihf6pjga, forge-v3, 2026-10-05/06): the owner's cart and admin
reports went unfixed through a dozen Smith turns. Three causes, held here:

1. Four turns ended on "I could not turn that into a change I am sure of":
   the model, deep in its reads, thought until the call's budget ran out and
   replied with nothing, and an empty reply was not asked for again.
2. Every look at the product page (`/shop/[slug]`) opened it on a product's
   id and saw "not found", so the Add to Bag button was never reached.
3. A run refused "not available to your role" never showed Smith the app's
   own launch-rights file, which said [] for every admin process.
"""
import json
import re
import subprocess
from pathlib import Path

from services.smith import loop, trials

ROOT = Path(__file__).resolve().parents[2]


def test_an_empty_reply_is_asked_for_again_not_answered_with_a_canned_question():
    replies = iter(["", json.dumps({"tool": "open_page", "args": {"route": "/cart"}, "why": "look"})])
    prompts = []

    def provider(prompt):
        prompts.append(prompt)
        return next(replies)
    chosen = loop.next_step("the cart is empty after Add to Bag", "ctx", [], [], provider=provider)
    assert chosen["tool"] == "open_page" and chosen["args"] == {"route": "/cart"}
    assert len(prompts) == 2 and "Your last reply was empty" in prompts[1]


def test_the_chooser_has_room_to_think_and_still_answer():
    src = (ROOT / "services/smith/understand_ask.py").read_text()
    assert "max_tokens=12000" in src


def test_a_route_param_is_filled_with_the_records_field_of_that_name():
    src = (ROOT / "scripts/page_shots.mjs").read_text()
    body = re.search(r"function fillRoute\(url, row\) \{.*?\n\}", src, re.S).group(0)
    js = body + """
const row = { id: "82d26b26", slug: "ivory-linen-slip-dress", orderNumber: "TC-1001" };
console.log(JSON.stringify([fillRoute("/shop/[slug]", row), fillRoute("/admin/products/[id]", row),
                            fillRoute("/orders/[order-number]", row), fillRoute("/x/[other]", row)]));"""
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == ["/shop/ivory-linen-slip-dress", "/admin/products/82d26b26",
                               "/orders/TC-1001", "/x/82d26b26"]


def test_a_role_refusal_shows_the_apps_launch_rights_and_where_they_come_from(tmp_path):
    f = tmp_path / "app/src/lib/workflows"
    f.mkdir(parents=True)
    (f / "launch-roles.ts").write_text('export const LAUNCH_ROLES = {\n  "FLOW-006": [],\n  "create-product": [],\n};\n')
    doc = {"pages": [{"id": "PAGE-012", "route": "/admin/products/new", "access": "role_restricted"}]}
    said = "\n".join(trials.launch_rights(str(tmp_path), doc, {"id": "FLOW-006", "name": "Create Product",
                                                                "launchedFrom": ["PAGE-012"]}))
    assert "launch-roles.ts says FLOW-006: [] — [] admits nobody" in said
    assert "PAGE-012 /admin/products/new (access role_restricted, users none named)" in said
    assert "`edit_access`" in said and "never by editing the file" in said


def test_a_missing_launch_rights_file_is_said(tmp_path):
    said = trials.launch_rights(str(tmp_path), {}, {"id": "FLOW-001", "name": "X"})
    assert "launch-roles.ts is missing" in said[0]


def test_every_signed_out_trial_in_a_turn_is_the_same_visitor(monkeypatch, tmp_path):
    """TCommerce, 2026-10-06: Smith added to the bag signed out, opened the bag
    signed out, and saw it empty — two strangers, because no trial carried the
    guest cookie a browser keeps. It then blamed a cart page that worked."""
    from services.smith import trials

    class _App:
        base = "http://127.0.0.1:1"

    sent = []
    monkeypatch.setattr(trials, "_http", lambda app, m, path, body, jar: sent.append(jar) or (200, "", "{}"))
    monkeypatch.setattr(trials, "_tables", lambda app: [])
    monkeypatch.setattr(trials, "_snapshot", lambda app, tables: {})
    bench = trials.Bench(str(tmp_path))
    monkeypatch.setattr(bench, "app", lambda: _App())
    doc = {"roles": [{"id": "ROLE-001", "name": "Admin"}]}
    trials.try_request(bench, doc, "POST", "/api/workflows/FLOW-001/execute", {}, "signed out")
    trials.try_request(bench, doc, "GET", "/cart", None, "signed out")
    assert sent[0] == sent[1] == [{"name": "forge-guest", "value": bench.guest, "url": _App.base}]
    assert trials.Bench(str(tmp_path)).guest != bench.guest, "a new turn is a new visitor"
