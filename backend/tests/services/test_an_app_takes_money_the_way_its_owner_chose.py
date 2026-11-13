"""An application takes money only when it should, through the gateways its
owner chose, with the right keys on the right side — and every agent, the
app's own files and Smith follow that one record (`payments`).

Deciding: the person's "no payments" wins with no model call; a model's
answer is checked against what the definition holds (a checkout step is
one-time payments whatever was said); with no model, the signals decide
conservatively. Choosing: gateways are the organisation's, one per
provider, priced currencies must be ones they take; integrations follow.
Keys: a preview and the test version get TEST keys, production LIVE ones,
and a side never keeps a payment key it should not have.
"""
from __future__ import annotations

import json
import types
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from services.blueprint.service import BlueprintService
from services.payments import app_payments as AP
from services.payments import need as N

FIXTURE = Path(__file__).resolve().parents[2] / "fleet" / "blueprints" / "ats-live.json"


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("FORGE_INTEGRATIONS_SECRET", "test-secret-for-payment-gateways-0123")


def _svc(tmp_path, description: str, *, requirements=(), currency=None, workflows=None, entities=None) -> BlueprintService:
    svc = BlueprintService.create(output_dir=tmp_path, app_id="a", name="App", domain="d", description=description)
    svc.doc["requirements"] = [{"id": f"REQ-{i + 1:03d}", "description": r, "status": "PROPOSED"} for i, r in enumerate(requirements)]
    if currency:
        svc.doc.setdefault("product", {})["currency"] = currency
    if workflows is not None:
        svc.doc["workflows"] = workflows
    if entities is not None:
        svc.doc.setdefault("data", {})["entities"] = entities
    svc.validate()
    svc.save()
    return BlueprintService.load(output_dir=tmp_path)


def _model(answer: dict | str):
    calls: list[str] = []

    def provider(prompt: str) -> str:
        calls.append(prompt)
        return answer if isinstance(answer, str) else json.dumps(answer)
    provider.calls = calls  # type: ignore[attr-defined]
    return provider


def _row(provider: str, *, label: str | None = None, coverage="both", home=None, currencies=("USD",), test=None, live=None):
    """A gateway row as the store holds it (sealed keys), without a database."""
    from services.payments.gateways import seal
    gid = uuid.uuid4()
    r = types.SimpleNamespace(id=gid, provider=provider, label=label or provider.title(), coverage=coverage, home_country=home,
                              currencies=list(currencies), deleted_at=None, checks={}, is_default=False)
    r.test_ct = r.test_iv = r.live_ct = r.live_iv = None
    if test:
        r.test_ct, r.test_iv = seal(gid, "test", test)
    if live:
        r.live_ct, r.live_iv = seal(gid, "live", live)
    return r


# --------------------------------------------------------------------------- #
# Deciding
# --------------------------------------------------------------------------- #

def test_a_person_who_said_no_payments_is_never_asked_a_model(tmp_path):
    svc = _svc(tmp_path, "A gym members portal to book classes. No payments — members pay at the front desk.")
    provider = _model({"needed": True, "models": ["subscription"]})
    out = N.decide(svc.doc, provider=provider)
    assert out["needed"] is False and out["by"] == "words" and provider.calls == []
    assert "No payments" in out["reason"]


@pytest.mark.parametrize("description, said, needed, models", [
    ("A yoga studio where members pay a monthly membership to book classes.",
     {"needed": True, "models": ["subscription"], "access": "app", "reason": "Members pay monthly.",
      "plans": [{"name": "Monthly", "interval": "month", "price": 999, "features": ["Unlimited classes"]}]},
     True, ["subscription"]),
    ("An online store selling handmade candles with a cart and checkout.",
     {"needed": True, "models": ["one_time"], "reason": "Shoppers buy candles."}, True, ["one_time"]),
    ("An expense tracker where staff log what they spent and managers approve it.",
     {"needed": False, "models": [], "reason": "It records spending made elsewhere."}, False, []),
])
def test_the_model_decides_what_the_words_alone_cannot(tmp_path, description, said, needed, models):
    svc = _svc(tmp_path, description, currency="INR")
    out = N.decide(svc.doc, provider=_model(said))
    assert out["needed"] is needed and out["models"] == models and out["by"] == "model"
    if "subscription" in models:
        assert out["plans"][0]["prices"] == {"INR": 999.0} and out["plans"][0]["highlighted"] is True
        assert out["access"] == "app"


def test_a_checkout_step_is_one_time_payments_whatever_the_model_said(tmp_path):
    flows = [{"id": "FLOW-001", "name": "Place order", "status": "PROPOSED", "trigger": {"kind": "manual"},
              "steps": [{"key": "pay", "type": "action", "config": {"actionType": "create_checkout"}}, {"key": "end", "type": "end"}]}]
    svc = _svc(tmp_path, "A bakery's order desk.")
    svc.doc["workflows"] = flows
    out = N.decide(svc.doc, provider=_model({"needed": False, "models": []}))
    assert out["needed"] is True and out["models"] == ["one_time"]


def test_with_no_model_the_signals_decide_and_a_broken_answer_is_no_answer(tmp_path):
    svc = _svc(tmp_path, "Members subscribe to a monthly membership to use the climbing gym's booking app.")

    def down(_prompt):
        raise RuntimeError("model unreachable")
    out = N.decide(svc.doc, provider=down)
    assert out["by"] == "signals" and out["needed"] is True and "subscription" in out["models"]
    svc2 = _svc(tmp_path / "b", "A team wiki for our engineers.")
    assert N.decide(svc2.doc, provider=_model("I think maybe?"))["needed"] is False


def test_forge_decides_once_per_definition_and_never_over_a_person(tmp_path):
    svc = _svc(tmp_path, "A tutoring marketplace where parents book and pay for lessons.")
    provider = _model({"needed": True, "models": ["one_time"], "reason": "Parents pay per lesson."})
    first = AP.decide_and_record(svc, provider=provider)
    assert first["needed"] is True and first["decidedBy"] == "forge" and len(provider.calls) == 1
    svc = BlueprintService.load(output_dir=tmp_path)
    AP.decide_and_record(svc, provider=provider)
    assert len(provider.calls) == 1, "the same definition is not decided twice"
    assert svc.doc["changeHistory"], "the decision is recorded with history"
    svc.doc["payments"]["decidedBy"] = "person"
    svc.doc["payments"]["needed"] = False
    svc.save()
    svc.doc["application"]["description"] += " Also sells study packs."
    svc.save()
    again = AP.decide_and_record(BlueprintService.load(output_dir=tmp_path), provider=provider)
    assert again["needed"] is False and len(provider.calls) == 1, "a person's decision is never overruled"


# --------------------------------------------------------------------------- #
# Choosing
# --------------------------------------------------------------------------- #

def test_choosing_records_gateways_plans_and_one_integration_per_gateway(tmp_path):
    svc = _svc(tmp_path, "A fitness studio app.", currency="INR")
    rzp = _row("razorpay", label="Razorpay India", coverage="domestic", home="IN", currencies=["INR"])
    stripe = _row("stripe", label="Stripe Global", coverage="international", currencies=["USD", "EUR", "INR"])
    out = AP.choose(svc, gateways=[rzp, stripe], needed=True, models=["subscription", "one_time"],
                    plans=[{"name": "Pro", "interval": "month", "prices": {"INR": 499, "USD": 9}, "features": ["All classes"]}],
                    access="app", output_dir=str(tmp_path))
    doc = BlueprintService.load(output_dir=tmp_path).doc
    p = doc["payments"]
    assert p["needed"] is True and p["decidedBy"] == "person" and p["access"] == "app"
    assert [g["provider"] for g in p["gateways"]] == ["razorpay", "stripe"] and p["gateways"][0]["gateway"] == str(rzp.id)
    assert p["plans"][0]["prices"] == {"INR": 499.0, "USD": 9.0}
    rows = [r for r in doc["integrations"] if r.get("serves") == "take_payment"]
    assert sorted(r["provider"] for r in rows) == ["razorpay", "stripe"]
    assert all(r["inbound"]["verify"] == "provider" for r in rows)
    assert json.dumps(doc).count("s3cret") == 0
    # Stripe dropped later: its row retires; Razorpay's keeps its id.
    rzp_id = next(r["id"] for r in rows if r["provider"] == "razorpay")
    AP.choose(BlueprintService.load(output_dir=tmp_path), gateways=[rzp], needed=True, models=["subscription"],
              plans=[{"name": "Pro", "interval": "month", "prices": {"INR": 499}}], access="none")
    doc = BlueprintService.load(output_dir=tmp_path).doc
    live = {r["provider"]: r for r in doc["integrations"] if r.get("serves") == "take_payment" and r.get("status") != "DEPRECATED"}
    assert list(live) == ["razorpay"] and live["razorpay"]["id"] == rzp_id
    assert out["decided"] is True


@pytest.mark.parametrize("gateways, kw, said", [
    (lambda: [_row("stripe", currencies=["USD"]), _row("stripe", currencies=["EUR"])], {"models": ["one_time"]}, "one Stripe account"),
    (lambda: [_row("paypal", currencies=["USD"])], {"models": ["subscription"], "plans": [{"name": "Pro", "interval": "month", "prices": {"INR": 499}}]},
     "priced in INR, which none of the chosen gateways takes"),
    (lambda: [_row("paypal", currencies=["USD"])], {"models": ["one_time"]}, "prices are in INR, and none of the chosen gateways takes INR"),
    (lambda: [_row("razorpay", currencies=["INR"])], {"models": ["subscription"], "plans": []}, "at least one plan"),
])
def test_a_choice_that_cannot_work_is_refused_in_words(tmp_path, gateways, kw, said):
    svc = _svc(tmp_path, "A shop.", currency="INR")
    with pytest.raises(AP.ChoiceError) as exc:
        AP.choose(svc, gateways=gateways(), needed=True, **kw)
    assert said in str(exc.value)


def test_turning_payments_off_keeps_the_reason_and_writes_no_gateways(tmp_path):
    svc = _svc(tmp_path, "A shop.", currency="INR")
    AP.choose(svc, gateways=[_row("razorpay", currencies=["INR"])], needed=True, models=["one_time"])
    AP.choose(BlueprintService.load(output_dir=tmp_path), gateways=[], needed=False)
    p = BlueprintService.load(output_dir=tmp_path).doc["payments"]
    assert p["needed"] is False and p["gateways"] == [] and p["decidedBy"] == "person"


# --------------------------------------------------------------------------- #
# Every agent is told
# --------------------------------------------------------------------------- #

def test_each_build_agent_is_told_what_was_decided(tmp_path):
    svc = _svc(tmp_path, "A gym.", currency="INR")
    assert AP.agent_note(svc.doc, "integrations") == "", "nothing decided, nothing said"
    AP.choose(svc, gateways=[_row("razorpay", label="Razorpay India", currencies=["INR"])], needed=True, models=["subscription"],
              plans=[{"name": "Monthly", "interval": "month", "prices": {"INR": 999}}])
    doc = BlueprintService.load(output_dir=tmp_path).doc
    assert "do not declare any other payment service" in AP.agent_note(doc, "integrations")
    assert "Razorpay India" in AP.agent_note(doc, "integrations")
    wf = AP.agent_note(doc, "workflows")
    assert "SUBSCRIPTIONS ARE BUILT IN" in wf and "Write no `create_checkout`" in wf
    assert "`/billing`" in AP.agent_note(doc, "page_contracts")
    assert "Do not declare Plan, Subscription" in AP.agent_note(doc, "data_model")
    assert AP.agent_note(doc, "design_system") == ""
    from services.blueprint.executors import build_prompt
    system, _user = build_prompt(doc, "integrations")[:2] if isinstance(build_prompt(doc, "integrations"), tuple) else (build_prompt(doc, "integrations"), "")
    assert "PAYMENTS ARE ALREADY DECIDED BY THE OWNER" in json.dumps(system)
    AP.choose(BlueprintService.load(output_dir=tmp_path), gateways=[], needed=False)
    doc = BlueprintService.load(output_dir=tmp_path).doc
    assert "takes no money" in AP.agent_note(doc, "workflows") and "NO payments" in AP.agent_note(doc, "integrations")


# --------------------------------------------------------------------------- #
# Keys, by side
# --------------------------------------------------------------------------- #

def test_test_keys_for_previews_live_keys_for_production_and_nothing_left_over(tmp_path):
    svc = _svc(tmp_path, "A shop.", currency="INR")
    rzp = _row("razorpay", currencies=["INR"], test={"key_id": "rzp_test_A", "key_secret": "TESTSECRET"},
               live={"key_id": "rzp_live_B", "key_secret": "LIVESECRET"})
    paypal = _row("paypal", currencies=["USD"], test={"client_id": "PPTEST", "client_secret": "PPTESTSECRET"})
    svc.doc.setdefault("product", {})["currency"] = "INR"
    AP.choose(svc, gateways=[rzp, paypal], needed=True, models=["one_time"])
    doc = BlueprintService.load(output_dir=tmp_path).doc
    local = AP.env_for_side(doc, [rzp, paypal], "local")
    assert local["RAZORPAY_KEY_ID"] == "rzp_test_A" and local["RAZORPAY_KEY_SECRET"] == "TESTSECRET"
    assert local["PAYPAL_CLIENT_ID"] == "PPTEST" and local["PAYPAL_ENV"] == "sandbox"
    assert local["STRIPE_SECRET_KEY"] is None, "a gateway not chosen is removed from the environment"
    assert "LIVESECRET" not in json.dumps(local), "a live key never reaches a preview"
    test = AP.env_for_side(doc, [rzp, paypal], "test", webhooks={"razorpay": "whsec_rzp"})
    assert test["RAZORPAY_KEY_SECRET"] == "TESTSECRET" and test["RAZORPAY_WEBHOOK_SECRET"] == "whsec_rzp"
    prod = AP.env_for_side(doc, [rzp, paypal], "production")
    assert prod["RAZORPAY_KEY_ID"] == "rzp_live_B" and prod["RAZORPAY_KEY_SECRET"] == "LIVESECRET"
    assert prod["PAYPAL_CLIENT_SECRET"] is None, "no live PayPal keys: production carries none (the stand-in says so)"
    assert "TESTSECRET" not in json.dumps(prod), "a test key never reaches production"
    paypal.deleted_at = datetime.now(timezone.utc)
    assert AP.env_for_side(doc, [rzp, paypal], "local")["PAYPAL_CLIENT_ID"] is None, "a removed gateway is gone everywhere"


# --------------------------------------------------------------------------- #
# Into the app
# --------------------------------------------------------------------------- #

def _app(tmp_path) -> Path:
    app = tmp_path / "app"
    (app / "src" / "db" / "schema").mkdir(parents=True)
    (app / "src" / "db" / "schema" / "index.ts").write_text('export { users } from "./users";\n')
    (app / "package.json").write_text("{}")
    return app


def test_the_app_gets_its_payment_files_its_config_and_a_gate_when_plans_open_it(tmp_path):
    svc = _svc(tmp_path, "A members' club.", currency="AED")
    app = _app(tmp_path)
    AP.choose(svc, gateways=[_row("stripe", label="Stripe UAE", currencies=["AED", "USD"])], needed=True, models=["subscription"],
              plans=[{"name": "Gold", "interval": "year", "prices": {"AED": 1200, "USD": 330}, "features": ["Lounge"]}],
              access="app", output_dir=str(tmp_path))
    files = {p.relative_to(app).as_posix() for p in app.rglob("*") if p.is_file()}
    for rel in ("src/app/api/billing/subscribe/route.ts", "src/app/api/pay/return/route.ts", "src/app/api/pay/confirm/route.ts",
                "src/app/(dashboard)/billing/page.tsx", "src/app/pay/razorpay/page.tsx", "src/db/schema/_forge_billing.ts",
                # the ledger, and the stand-in that takes a payment before any key
                "src/db/schema/_forge_payments.ts", "src/app/pay/stand-in/page.tsx", "src/app/api/pay/stand-in/route.ts",
                "src/lib/payments-config.ts", "src/middleware.ts",
                # The library those routes import, for an app built before it existed.
                "src/lib/payments/billing.ts", "src/lib/payments/routing.ts", "src/lib/payments/razorpay.ts",
                # and the currency it falls back to, which a bundler must be able to resolve.
                "src/lib/money.ts",
                # where its gateways' signed events land
                "src/app/api/webhooks/[integration]/route.ts", "src/lib/integrations/providers.ts",
                # and the current workflow engine, whose checkout returns through /api/pay/return
                "src/lib/workflows/index.ts"):
        assert rel in files, rel
    assert not any("__tests__" in f for f in files)
    assert "/api/pay/return?payment=" in (app / "src/lib/workflows/index.ts").read_text()
    barrel = (app / "src/db/schema/index.ts").read_text()
    assert "forgeSubscriptions, forgePlanRefs" in barrel and "forgePayments" in barrel
    cfg = (app / "src/lib/payments-config.ts").read_text()
    assert '"access": "app"' in cfg and '"integration": "stripe"' in cfg and '"AED": 1200' in cfg and "sk_" not in cfg
    mw = (app / "src/middleware.ts").read_text()
    assert "async function middleware(req)" in mw and "holdsAccess" in mw and "SUBSCRIPTION_REQUIRED" in mw
    assert '"^/billing(?:/.*)?$"' in mw and "OPERATORS" in mw
    # Installing again changes nothing.
    assert AP.install_runtime(app, BlueprintService.load(output_dir=tmp_path).doc) == []
    # Plans that do not lock the app: no gate in the middleware.
    AP.choose(BlueprintService.load(output_dir=tmp_path), gateways=[_row("stripe", currencies=["AED"])], needed=True,
              models=["subscription"], plans=[{"name": "Gold", "interval": "year", "prices": {"AED": 1200}}], access="none",
              output_dir=str(tmp_path))
    mw = (app / "src/middleware.ts").read_text()
    assert "holdsAccess" not in mw and "  function middleware(req)" in mw


@pytest.mark.parametrize("first", ["stripe", "razorpay"])
def test_two_gateways_are_one_connected_service_and_the_default_answers_for_it(tmp_path, first):
    """Both gateways serve `take_payment`; the app's map holds the action once (an object
    literal with the key twice keeps only the last), and it is the default — the first the
    owner chose, as in the payments config."""
    svc = _svc(tmp_path, "A members' club.", currency="INR")
    app = _app(tmp_path)
    rows = {"stripe": _row("stripe", label="Stripe Global", coverage="international", currencies=["USD", "INR"]),
            "razorpay": _row("razorpay", label="Razorpay India", coverage="domestic", home="IN", currencies=["INR"])}
    other = "razorpay" if first == "stripe" else "stripe"
    AP.choose(svc, gateways=[rows[first], rows[other]], needed=True, models=["one_time"], output_dir=str(tmp_path))
    text = (app / "src/lib/integrations/connected.ts").read_text()
    services = text[text.index("CONNECTED_SERVICES"):text.index("};", text.index("CONNECTED_SERVICES"))]
    assert services.count('"take_payment"') == 1, services
    assert f'"provider": "{first}"' in services and f'"provider": "{other}"' not in services
    cfg = (app / "src/lib/payments-config.ts").read_text()
    assert cfg.index(f'"integration": "{first}"') < cfg.index(f'"integration": "{other}"')
    # Both still receive their own signed events.
    inbound = text[text.index("INBOUND"):]
    assert '"stripe":' in inbound and '"razorpay":' in inbound


@pytest.mark.parametrize("words, currency, plans", [
    ("Members buy a monthly membership: Basic at Rs 999 a month (8 classes) or Unlimited at Rs 1999 a month, "
     "and anyone can also pay Rs 400 for a single drop-in class.", "INR",
     [("Basic", "month", {"INR": 999.0}), ("Unlimited", "month", {"INR": 1999.0})]),
    ("Members pay a monthly membership of Rs 999 or a yearly one of Rs 9999. A drop-in pass is Rs 300.", "INR",
     [("Monthly", "month", {"INR": 999.0}), ("Yearly", "year", {"INR": 9999.0})]),
    ("Pro plan at ₹1,999 per month and Team plan ₹4,999/month", "INR",
     [("Pro", "month", {"INR": 1999.0}), ("Team", "month", {"INR": 4999.0})]),
    ("Rs 1,49,999 a year for the enterprise tier", "INR", [("Yearly", "year", {"INR": 149999.0})]),
    ("$9/mo or $90 per year", "USD", [("Monthly", "month", {"USD": 9.0}), ("Yearly", "year", {"USD": 90.0})]),
    ("an annual plan at $99, billed once", "USD", [("Yearly", "year", {"USD": 99.0})]),
    ("Gold membership costs AED 1200 a year", "AED", [("Gold", "year", {"AED": 1200.0})]),
    ("€9,99 per month", "EUR", [("Monthly", "month", {"EUR": 9.99})]),
    ("Book a class for Rs 400. No subscriptions.", "INR", []),
    # One plan said twice is one plan, by its own name.
    ("Members pay a monthly membership of Rs 999 or a yearly one of Rs 9999. Later: Basic at Rs 999 a month or "
     "Unlimited at Rs 1999 a month.", "INR",
     [("Basic", "month", {"INR": 999.0}), ("Yearly", "year", {"INR": 9999.0}), ("Unlimited", "month", {"INR": 1999.0})]),
])
def test_plans_are_read_as_the_person_priced_them(words, currency, plans):
    """Thousands separators (Indian grouping too), the interval before or after the
    price, a plan's own name; a one-off price is not a plan."""
    from services.payments.need import plans_in_words
    assert [(p["name"], p["interval"], p["prices"]) for p in plans_in_words(words, currency)] == plans


@pytest.mark.parametrize("words, found", [
    ("Visitors can buy a single drop-in class pass for Rs 300.", ["Rs 300"]),
    ("anyone can also pay Rs 400 for a single drop-in class.", ["Rs 400"]),
    ("a ₹50 late fee on returns", ["₹50"]),
    ("Tickets cost $25 each", ["$25"]),
    ("Basic at Rs 999 a month or Unlimited at Rs 1999 a month", []),
    ("Employees see their salary of Rs 50,000 and the department budget of $2M.", []),
    ("The event has 300 seats.", []),
])
def test_a_price_charged_once_is_read_from_the_words_around_it(words, found):
    from services.payments.need import one_off_prices
    assert one_off_prices(words) == found


def test_without_a_model_the_plans_still_come_from_the_persons_words(tmp_path):
    """The model is unreachable (no credit, an outage): the decision falls back to the
    signals, and the plans the request priced are still the ones offered."""
    svc = _svc(tmp_path, "A yoga studio. Members buy Basic at Rs 999 a month or Unlimited at Rs 1,999 a month; "
                         "a drop-in class is Rs 400.", currency="INR")
    def down(_prompt):
        raise RuntimeError("429 insufficient balance")
    from services.payments.need import decide
    out = decide(svc.doc, provider=down)
    assert out["needed"] and out["models"] == ["one_time", "subscription"] and out["by"] == "signals"
    assert "Basic" in out["reason"] and "one-time payments and subscriptions" in out["reason"]
    assert [(p["name"], p["prices"]) for p in out["plans"]] == [("Basic", {"INR": 999.0}), ("Unlimited", {"INR": 1999.0})]
    assert all(p.get("id") and p["interval"] == "month" for p in out["plans"])


def test_a_new_decision_brings_its_own_plans_but_a_persons_are_kept(tmp_path):
    svc = _svc(tmp_path, "A gym. Members pay Rs 999 a month.", currency="INR")
    down = lambda _p: (_ for _ in ()).throw(RuntimeError("no model"))  # noqa: E731
    AP.decide_and_record(svc, provider=down)
    assert [p["prices"] for p in AP.section(svc.doc)["plans"]] == [{"INR": 999.0}]
    svc.doc["requirements"] = [{"id": "REQ-001", "description": "Gold at Rs 1,499 a month.", "status": "PROPOSED"}]
    svc.doc["application"]["description"] = "A gym."
    AP.decide_and_record(svc, provider=down)
    assert [(p["name"], p["prices"]) for p in AP.section(svc.doc)["plans"]] == [("Gold", {"INR": 1499.0})], "Forge's old guess replaced"
    AP.choose(svc, gateways=[_row("razorpay", currencies=["INR"])], needed=True, models=["subscription"],
              plans=[{"name": "Mine", "interval": "month", "prices": {"INR": 10}}])
    svc.doc["requirements"][0]["description"] = "Platinum at Rs 4,999 a month."
    AP.decide_and_record(svc, provider=down)
    assert [p["name"] for p in AP.section(svc.doc)["plans"]] == ["Mine"], "a person's plans are theirs"


def test_the_middleware_gate_is_valid_typescript_shape():
    doc = {"payments": {"needed": True, "models": ["subscription"], "access": "app",
                        "plans": [{"id": "p", "name": "P", "interval": "month", "prices": {"USD": 9}}]}}
    head, body = AP.middleware_gate(doc)
    text = "\n".join(head + body)
    assert text.count("{") == text.count("}") and text.count("(") == text.count(")")
    assert "token && !GATE_FREE.some" in text and "/api/billing/access" in text
    assert AP.middleware_gate({"payments": {"needed": True, "models": ["one_time"], "access": "app"}}) == ([], [])


# --------------------------------------------------------------------------- #
# Before a build, and after a Smith change
# --------------------------------------------------------------------------- #

def test_a_build_of_an_app_that_takes_money_waits_for_the_owner(tmp_path, monkeypatch):
    svc = _svc(tmp_path, "A ticketing app where fans buy tickets to gigs.")
    monkeypatch.setattr(N, "_default_provider", _model({"needed": True, "models": ["one_time"], "reason": "Fans buy tickets."}))
    asked = AP.build_question(svc)
    assert asked and asked["paymentChoice"] is True and asked["status"] == "asked" and "Fans buy tickets." in asked["text"]
    AP.choose(BlueprintService.load(output_dir=tmp_path), gateways=[], needed=False)
    assert AP.build_question(BlueprintService.load(output_dir=tmp_path)) is None, "once the person chose, the build goes on"
    svc2 = _svc(tmp_path / "b", "A rota planner for nurses.")
    monkeypatch.setattr(N, "_default_provider", _model({"needed": False, "models": []}))
    assert AP.build_question(svc2) is None, "an app that takes no money builds straight away"


def test_a_smith_change_that_makes_the_app_take_money_asks_how(tmp_path, monkeypatch):
    svc = _svc(tmp_path, "A club's events calendar.")
    monkeypatch.setattr(N, "_default_provider", _model({"needed": True, "models": ["subscription"], "reason": "Members pay yearly.",
                                                        "plans": [{"name": "Yearly", "interval": "year", "price": 50}]}))
    assert AP.sense_after_change(tmp_path, "rename the events page") is None, "a change with no money in it asks nothing"
    sensed = AP.sense_after_change(tmp_path, "add a yearly membership people subscribe to")
    assert sensed and sensed["options"] == [AP.PAYMENT_CHIP] and "sells subscriptions" in sensed["said"]
    AP.choose(BlueprintService.load(output_dir=tmp_path), gateways=[_row("stripe", currencies=["USD"])], needed=True,
              models=["subscription"], plans=[{"name": "Yearly", "interval": "year", "prices": {"USD": 50}}])
    assert AP.sense_after_change(tmp_path, "add a monthly plan too") is None, "already set up: nothing to ask"


def test_smith_sets_payments_up_from_words_through_the_orgs_gateways(tmp_path, monkeypatch):
    from services.smith import payments_setup as S
    svc = _svc(tmp_path, "A coaching app.", currency="INR")
    # Connected as an admin connects them: test keys, checked.
    rzp = _row("razorpay", label="Razorpay India", coverage="domestic", home="IN", currencies=["INR"],
               test={"key_id": "rzp_test_" "AbCdEf123456", "key_secret": "s3cret"})
    stripe = _row("stripe", label="Stripe Global", currencies=["USD", "INR"], test={"secret_key": "sk_test_" "51Abc"})
    rzp.checks = stripe.checks = {"test": {"ok": True}}
    monkeypatch.setattr(S, "_org_gateways", lambda _o: [rzp, stripe])
    asked = S.run(str(tmp_path), change="let people subscribe")
    assert not asked["applied"] and asked["options"] == [AP.PAYMENT_CHIP] and "Razorpay India" in asked["reason"]
    out = S.run(str(tmp_path), change="take payments through razorpay with a Pro plan at ₹499 a month; members must subscribe")
    assert out["applied"], out
    p = BlueprintService.load(output_dir=tmp_path).doc["payments"]
    assert [g["provider"] for g in p["gateways"]] == ["razorpay"] and p["decidedBy"] == "smith" and p["access"] == "app"
    assert p["plans"][0]["name"] == "Pro" and p["plans"][0]["prices"] == {"INR": 499.0} and p["plans"][0]["interval"] == "month"
    off = S.run(str(tmp_path), change="stop taking payments")
    assert off["applied"] and BlueprintService.load(output_dir=tmp_path).doc["payments"]["needed"] is False
    monkeypatch.setattr(S, "_org_gateways", lambda _o: [])
    none = S.run(str(tmp_path), change="take payments")
    assert not none["applied"] and "Settings → Integrations → Payments" in none["reason"] and "sk_" not in json.dumps(none)


# --------------------------------------------------------------------------- #
# Webhooks: registered once, reused, moved
# --------------------------------------------------------------------------- #

class _Gateway:
    def __init__(self):
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url.endswith("/v1/webhook_endpoints"):
            return httpx.Response(200, json={"id": "we_1", "secret": "whsec_from_stripe"})
        if "/v1/webhook_endpoints/we_1" in url:
            return httpx.Response(200, json={"id": "we_1"})
        if url.endswith("/v1/oauth2/token"):
            return httpx.Response(200, json={"access_token": "TOK"})
        if url.endswith("/v1/notifications/webhooks") and request.method == "POST":
            return httpx.Response(201, json={"id": "WH-PAYPAL-1"})
        return httpx.Response(404, json={})


@pytest.mark.asyncio
async def test_webhooks_are_registered_once_and_moved_with_the_address(tmp_path, monkeypatch, org_id, auth_client):
    from database import async_session
    from models.payment_gateway import PaymentGateway, PaymentGatewayWebhook
    from models.project import Project
    from services.payments import webhooks as W
    from services.payments.gateways import seal
    from sqlalchemy import select
    gw = _Gateway()
    monkeypatch.setattr(W, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(gw)))
    monkeypatch.delenv("FORGE_PAYMENTS_EMULATOR", raising=False)
    res = await auth_client.post(f"/api/orgs/{org_id}/projects", json={"name": "Shop"})
    project_id = uuid.UUID(res.json()["id"])
    out_dir = tmp_path / "out"
    svc = _svc(out_dir, "A shop.", currency="USD")
    async with async_session() as db:
        rows = []
        for prov, keys in (("stripe", {"secret_key": "sk_test_x"}), ("paypal", {"client_id": "c", "client_secret": "s"}),
                           ("razorpay", {"key_id": "rzp_test_x", "key_secret": "y"})):
            row = PaymentGateway(id=uuid.uuid4(), org_id=uuid.UUID(org_id), provider=prov, label=prov.title(), coverage="both",
                                 currencies=["USD"] if prov != "razorpay" else ["INR"], checks={}, is_default=False)
            row.test_ct, row.test_iv = seal(row.id, "test", keys)
            db.add(row)
            rows.append(row)
        await db.commit()
    svc.doc.setdefault("product", {})["currency"] = "USD"
    AP.choose(svc, gateways=rows, needed=True, models=["one_time"])
    async with async_session() as db:
        first = await W.ensure_webhooks(db, project_id=project_id, output_dir=out_dir, org_id=uuid.UUID(org_id), side="test",
                                        address="https://shop-test.vercel.app")
    assert first["secrets"] == {"stripe": "whsec_from_stripe", "paypal": "WH-PAYPAL-1", "razorpay": first["secrets"]["razorpay"]}
    assert len(first["secrets"]["razorpay"]) >= 24
    statuses = {r["provider"]: r["status"] for r in first["report"]}
    assert statuses == {"stripe": "registered", "paypal": "registered", "razorpay": "manual"}
    stripe_req = next(r for r in gw.requests if str(r.url).endswith("/v1/webhook_endpoints"))
    body = stripe_req.content.decode()
    assert "url=https%3A%2F%2Fshop-test.vercel.app%2Fapi%2Fwebhooks%2Fstripe" in body and "enabled_events%5B%5D=invoice.paid" in body
    n = len(gw.requests)
    async with async_session() as db:
        again = await W.ensure_webhooks(db, project_id=project_id, output_dir=out_dir, org_id=uuid.UUID(org_id), side="test",
                                        address="https://shop-test.vercel.app")
    assert again["secrets"] == first["secrets"]
    assert not any(str(r.url).endswith("/v1/webhook_endpoints") for r in gw.requests[n:]), "Stripe's endpoint is not made twice"
    async with async_session() as db:
        moved = await W.ensure_webhooks(db, project_id=project_id, output_dir=out_dir, org_id=uuid.UUID(org_id), side="test",
                                        address="https://shop.example.com")
    assert any("/v1/webhook_endpoints/we_1" in str(r.url) for r in gw.requests), "a new address moves the endpoint"
    assert moved["secrets"]["stripe"] == "whsec_from_stripe"
    async with async_session() as db:
        stored = (await db.execute(select(PaymentGatewayWebhook))).scalars().all()
        assert all("whsec_from_stripe" not in (h.secret_ct or "") for h in stored), "secrets are sealed"
        setup = await W.setup_for(db, project_id)
        member = await W.setup_for(db, project_id, admin=False)
    manual = next(s for s in setup if s["provider"] == "razorpay")
    assert manual["secret"] == first["secrets"]["razorpay"] and "subscription.charged" in manual["events"]
    assert "secret" not in next(s for s in setup if s["provider"] == "stripe"), "a registered secret is never shown"
    told = next(s for s in member if s["provider"] == "razorpay")
    assert "secret" not in told and told["secretHidden"] is True and told["events"], \
        "a member is told the webhook must be pasted, never the secret that signs payments"


# --------------------------------------------------------------------------- #
# Brutal round 1: what an owner, a payer and the live app must never get wrong
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("prices,said", [
    ({"USD": -5}, "more than zero"), ({"USD": 0}, "more than zero"), ({"USD": "abc"}, "not a number"),
    ({"USD": 5.999}, "Use 6.00"), ({"JPY": 500.5}, "Use 500"), ({"KWD": 1.2555}, "Use 1.256"),
])
def test_a_price_that_cannot_be_charged_is_said_never_dropped(tmp_path, prices, said):
    svc = _svc(tmp_path, "A members' club.", currency="USD")
    cur = next(iter(prices))
    with pytest.raises(AP.ChoiceError, match=said):
        AP.choose(svc, gateways=[_row("stripe", currencies=[cur, "USD"])], needed=True, models=["subscription"],
                  plans=[{"name": "Gold", "interval": "month", "prices": prices}])


def test_three_decimal_currencies_keep_their_fils():
    assert N.clean_plans([{"name": "Gold", "prices": {"KWD": 1.255, "JPY": 500}}], "KWD")[0]["prices"] == {"KWD": 1.255, "JPY": 500}


def test_razorpay_is_not_asked_to_bill_daily(tmp_path):
    svc = _svc(tmp_path, "A gym.", currency="INR")
    with pytest.raises(AP.ChoiceError, match="at most once a week"):
        AP.choose(svc, gateways=[_row("razorpay", currencies=["INR"])], needed=True, models=["subscription"],
                  plans=[{"name": "Day pass", "interval": "day", "prices": {"INR": 99}}])


@pytest.mark.parametrize("brief,needed", [
    ("Free to use for browsing classes; members pay ₹999 a month", True),
    ("free for everyone during the trial, then $49 per month", True),
    ("A gym members portal to book classes. No payments — members pay at the front desk.", False),
    ("A team task board, completely free, no payments.", False),
])
def test_a_free_part_does_not_decide_the_whole_app(tmp_path, brief, needed):
    svc = _svc(tmp_path, brief, currency="INR")
    out = N.decide(svc.doc, provider=lambda _p: (_ for _ in ()).throw(RuntimeError("no model")))
    assert out["needed"] is needed, out


def test_the_live_side_is_told_it_is_live_and_live_readiness_is_checked_keys(tmp_path):
    svc = _svc(tmp_path, "A shop.", currency="USD")
    test_only = _row("stripe", currencies=["USD"], test={"secret_key": "sk_test_" "51Abc"})
    test_only.checks = {"test": {"ok": True}}
    AP.choose(svc, gateways=[test_only], needed=True, models=["one_time"])
    doc = BlueprintService.load(output_dir=tmp_path).doc
    prod = AP.env_for_side(doc, [test_only], "production")
    assert prod[AP.SIDE_ENV] == "production" and prod["STRIPE_SECRET_KEY"] is None, "no live keys: none shipped, and the app knows it is live"
    assert AP.env_for_side(doc, [test_only], "test")[AP.SIDE_ENV] == "test"
    ready = AP.readiness(doc, [test_only])
    assert ready["needed"] and not ready["liveReady"] and ready["missing"][0]["state"] == "test_only"
    unchecked = _row("stripe", currencies=["USD"], live={"secret_key": "sk_live_" "51Abc"})
    unchecked.id = test_only.id
    unchecked.checks = {"live": {"ok": False, "reachable": False}}
    assert not AP.readiness(doc, [unchecked])["liveReady"], "live keys never checked may be sandbox keys: not ready"
    unchecked.checks = {"live": {"ok": True}}
    assert AP.readiness(doc, [unchecked])["liveReady"]


def test_a_role_people_choose_at_sign_up_is_never_an_operator_who_skips_the_plan(tmp_path):
    svc = _svc(tmp_path, "A property app.", currency="USD")
    svc.doc["roles"] = [{"id": "ROLE-001", "name": "Admin"}, {"id": "ROLE-002", "name": "Owner"}]
    svc.doc.setdefault("security", {})["signupRoles"] = ["ROLE-002"]
    ops = AP._operators(svc.doc)
    assert "owner" not in ops and "admin" in ops


def test_payments_turned_off_retire_the_old_payment_service(tmp_path):
    svc = _svc(tmp_path, "A shop.", currency="USD")
    AP.choose(svc, gateways=[_row("stripe", currencies=["USD"])], needed=True, models=["one_time"])
    svc = BlueprintService.load(output_dir=tmp_path)
    AP.choose(svc, gateways=[], needed=False)
    rows = [r for r in BlueprintService.load(output_dir=tmp_path).doc.get("integrations") or [] if r.get("serves") == AP.SERVES]
    assert rows and all(r["status"] == "DEPRECATED" for r in rows)


def test_another_organisations_copy_of_a_template_chooses_its_own_gateways():
    from services.project_templates import for_another_organisation
    doc = {"payments": {"needed": True, "models": ["subscription"], "decidedBy": "person", "basis": "x",
                        "gateways": [{"gateway": "g-of-org-a", "provider": "razorpay", "label": "Acme India"}],
                        "plans": [{"name": "Pro"}], "access": "app", "reason": "You chose."}}
    out = for_another_organisation(doc)["payments"]
    assert "gateways" not in out and "decidedBy" not in out and out["plans"] == [{"name": "Pro"}]


@pytest.mark.parametrize("asked,off", [
    ("Don't forget to add a Pro plan with payments", False), ("remove the old billing page and charge through Razorpay", False),
    ("do not charge for the trial, add a monthly plan at 499 rupees", False), ("stop taking payments", True), ("make it free", True),
])
def test_smith_turns_payments_off_only_when_asked_to(asked, off):
    from services.smith import payments_setup as S
    assert bool(S._OFF.search(asked) and not S._ADDS.search(asked) and not N.plans_in_words(asked, "USD")) is off


def test_smith_never_chooses_a_gateway_whose_keys_were_refused(tmp_path, monkeypatch):
    from services.smith import payments_setup as S
    _svc(tmp_path, "A coaching app.", currency="INR")
    broken = _row("razorpay", label="Razorpay India", currencies=["INR"], test={"key_id": "rzp_test_" "AbC", "key_secret": "x"})
    broken.checks = {"test": {"ok": False, "error": "refused"}}
    monkeypatch.setattr(S, "_org_gateways", lambda _o: [broken])
    out = S.run(str(tmp_path), change="take payments through razorpay")
    assert not out["applied"] and "refused" in out["reason"]


def test_an_agent_never_declares_a_payment_service_in_an_app_whose_owner_chooses_them(tmp_path):
    from services.blueprint.agent_contract import AgentResult, ArtifactProposal, apply_agent_result
    svc = _svc(tmp_path, "A yoga studio; members pay ₹999 a month.", currency="INR")
    N_doc = svc.doc
    N_doc["payments"] = {"needed": True, "models": ["subscription"], "decidedBy": "forge", "gateways": [], "plans": [], "access": "none",
                         "reason": ""}
    svc.save()
    svc = BlueprintService.load(output_dir=tmp_path)
    result = AgentResult(task_id="t", agent="integration", confidence=0.9, proposals=[
        ArtifactProposal("integrations", "razorpay", {"name": "Razorpay", "kind": "payment", "provider": "razorpay",
                                                      "serves": "take_payment", "status": "PROPOSED", "secretRefs": ["RAZORPAY_KEY_ID"]})])
    apply_agent_result(svc, result, commit=False)
    assert not [r for r in svc.doc.get("integrations") or [] if r.get("serves") == "take_payment"], \
        "the agent's own payment service is set aside: the owner chooses the gateways"


def test_test_payments_retire_a_payment_service_nobody_chose(tmp_path):
    svc = _svc(tmp_path, "A shop.", currency="USD")
    svc.doc.setdefault("integrations", []).append({"id": "INT-001", "name": "Razorpay", "kind": "payment", "provider": "razorpay",
                                                   "serves": "take_payment", "status": "PROPOSED"})
    svc.save()
    AP.choose(BlueprintService.load(output_dir=tmp_path), gateways=[], needed=True, models=["one_time"])
    rows = [r for r in BlueprintService.load(output_dir=tmp_path).doc.get("integrations") or [] if r.get("serves") == AP.SERVES]
    assert rows and all(r["status"] == "DEPRECATED" for r in rows)


def test_a_change_that_says_take_payments_asks_which_gateway(tmp_path):
    svc = _svc(tmp_path, "A yoga studio.", currency="INR")
    svc.doc["payments"] = {"needed": True, "models": ["subscription"], "decidedBy": "forge", "gateways": [], "plans": [], "access": "none",
                           "reason": ""}
    svc.save()
    sensed = AP.sense_after_change(tmp_path, "Take payments for the memberships through our payment gateways")
    assert sensed and sensed["options"] == [AP.PAYMENT_CHIP]


def test_a_member_without_a_plan_is_shown_the_way_to_one():
    """An app that stays open showed its plans only inside the account menu: a
    new member never learned one existed (Task Board, 2026-11-06)."""
    from services.smith.sync_app import FRAME_FILES
    shell = Path(__file__).resolve().parents[2] / "templates" / "app-foundation" / "src" / "app" / "(dashboard)"
    layout, prompt = (shell / "layout.tsx").read_text(), (shell / "PlanPrompt.tsx").read_text()
    assert "@/lib/payments-config" in layout and "plansOnSale &&" in layout and "<PlanPrompt />" in layout
    assert "/api/billing/status" in prompt and "status.held" in prompt, "shown once the app says the person holds no plan"
    assert "(billing|pay)" in prompt, "never on the plan page or a payment page"
    # A holder is marked as a member in the account menu (and the persona frame), with the plan in words.
    menu, persona = (shell / "AccountMenu.tsx").read_text(), (shell / "PersonaChrome.tsx").read_text()
    assert "usePlanStatus(sellsPlans)" in menu and "<MemberCrown" in menu and "planLine(plan)" in menu
    assert "usePlanStatus(plans)" in persona and "<MemberCrown" in persona
    assert "plans={plansOnSale}" in layout and layout.index("const plansOnSale") < layout.index("const cluster = ")
    assert "let asked: Promise<PlanStatus>" in prompt, "the frame asks once per page load, however many parts show the plan"
    assert "src/app/(dashboard)/PlanPrompt.tsx" in FRAME_FILES, "an app's refreshed layout brings the file it imports"


def test_a_new_app_has_its_gateways_keys_before_its_checks_run():
    """Zenith Yoga, 2026-11-11: a freshly built app's preview had no gateway
    keys (the settings were written only at the next Smith turn), so it took
    payments through the stand-in. The build now writes them first."""
    src = (Path(__file__).resolve().parents[2] / "routers" / "blueprint_generate.py").read_text()
    hook = src[src.index("def _after_turn(result: Any) -> None:"):src.index("async def turn() -> None:")]
    assert "write_env_local_from_platform" in hook
    assert hook.index("write_env_local_from_platform") < hook.index("_start_checks(")


def test_the_root_sends_a_signed_in_person_to_their_roles_page():
    """A new visitor's first sight of Zenith Yoga was the "not allowed" page:
    "/" sent everyone to the navigation's first page, which their role could
    not open. It sends a signed-in person to their role's landing page."""
    page = (Path(__file__).resolve().parents[2] / "templates" / "standalone-app" / "src" / "app" / "[[...slug]]" / "page.tsx").read_text()
    assert 'import { landingFor } from "@/lib/landing";' in page and "await auth()" in page
    assert "redirect(own && own !== \"/\" ? own : entryRoute)" in page
