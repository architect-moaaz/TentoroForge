"""A local emulator of the three payment gateways Forge builds in — for the
end-to-end check of a generated app's payments, with no real account.

It answers the endpoints Forge and the app's runtime call, in the gateways'
documented shapes, at:

    http://127.0.0.1:6599/stripe/...           (Stripe's /v1 API)
    http://127.0.0.1:6599/razorpay/...         (Razorpay's /v1 API)
    http://127.0.0.1:6599/paypal/sandbox/...   (PayPal's sandbox API)

and serves stand-ins for each gateway's own page (Stripe Checkout, PayPal's
approval) where the tester presses "Pay" or "Cancel". Paying signs a webhook
exactly as the gateway does — Stripe-Signature (HMAC over `t.body`),
X-Razorpay-Signature (HMAC of the body), PayPal's transmission headers
(verified by `verify-webhook-signature` here) — and sends it to every
endpoint registered for that gateway. `POST /razorpay/_checkout` plays
Razorpay's Checkout window: it captures a payment and answers with the
`razorpay_signature` the handler would get.

Keys: any key works except one containing "bad" (answered 401).
State is in memory. Run:  .venv/bin/python scripts/payments_emulator.py
Point the platform at it with FORGE_PAYMENTS_EMULATOR and an app with
FORGE_PAY_EMULATOR. Never set either in production.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import itertools
import json
import os
import threading
import time
from typing import Any
from urllib.parse import parse_qs

import httpx
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

app = FastAPI(title="Forge payments emulator")
BASE = os.environ.get("EMULATOR_BASE", "http://127.0.0.1:6599")
# Ids never come round again, across restarts too, as a gateway's never do:
# counted from 1000, an id from before a restart named another subscription,
# and an app holding the old one read the new one into it.
_ids = itertools.count(int(time.time() * 1000))
S: dict[str, dict[str, Any]] = {"sessions": {}, "subs": {}, "prices": {}, "hooks": {}, "rz_orders": {}, "rz_payments": {},
                                 "rz_plans": {}, "rz_subs": {}, "pp_orders": {}, "pp_products": {}, "pp_plans": {}, "pp_subs": {},
                                 "sent": {}}
LOG: list[dict] = []


def nid(prefix: str) -> str:
    return f"{prefix}{next(_ids)}"


def now() -> int:
    return int(time.time())


def refused(request: Request) -> bool:
    auth = request.headers.get("authorization", "")
    try:
        if auth.startswith("Basic "):
            auth = base64.b64decode(auth[6:]).decode()
    except Exception:  # noqa: BLE001
        pass
    return "bad" in auth.lower()


def deny(gateway: str) -> JSONResponse:
    if gateway == "stripe":
        return JSONResponse({"error": {"message": "Invalid API Key provided", "type": "invalid_request_error"}}, 401)
    if gateway == "razorpay":
        return JSONResponse({"error": {"code": "BAD_REQUEST_ERROR", "description": "Authentication failed"}}, 401)
    return JSONResponse({"error": "invalid_client", "error_description": "Client Authentication failed"}, 401)


async def body_of(request: Request) -> dict:
    raw = (await request.body()).decode()
    if not raw:
        return {}
    if request.headers.get("content-type", "").startswith("application/json"):
        return json.loads(raw)
    flat = {k: v[-1] for k, v in parse_qs(raw, keep_blank_values=True).items()}
    return flat


def record(kind: str, **data: Any) -> None:
    LOG.append({"at": time.time(), "kind": kind, **data})


# ---------------------------------------------------------------- webhooks ---

def deliver(gateway: str, event: dict) -> None:
    """Send a signed event to every endpoint registered for `gateway` (after a beat, like a gateway)."""
    raw = json.dumps(event)

    def go() -> None:
        time.sleep(0.4)
        for hook in list(S["hooks"].values()):
            if hook["gateway"] != gateway:
                continue
            headers = {"content-type": "application/json"}
            if gateway == "stripe":
                t = now()
                sig = hmac.new(hook["secret"].encode(), f"{t}.{raw}".encode(), hashlib.sha256).hexdigest()
                headers["stripe-signature"] = f"t={t},v1={sig}"
            elif gateway == "razorpay":
                headers["x-razorpay-signature"] = hmac.new(hook["secret"].encode(), raw.encode(), hashlib.sha256).hexdigest()
                headers["x-razorpay-event-id"] = nid("evt_")
            else:
                tid = nid("tx-")
                S["sent"][tid] = raw
                headers.update({"paypal-auth-algo": "SHA256withRSA", "paypal-cert-url": f"{BASE}/paypal/certs/CERT",
                                "paypal-transmission-id": tid, "paypal-transmission-sig": "emulated",
                                "paypal-transmission-time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            try:
                r = httpx.post(hook["url"], content=raw, headers=headers, timeout=20)
                record("webhook", gateway=gateway, url=hook["url"], type=event.get("type") or event.get("event") or event.get("event_type"),
                       status=r.status_code, answer=r.text[:200])
            except Exception as exc:  # noqa: BLE001
                record("webhook", gateway=gateway, url=hook["url"], error=str(exc))
    threading.Thread(target=go, daemon=True).start()


@app.post("/_hooks")
async def add_hook(request: Request):
    """For a test: register an endpoint by hand (Razorpay's dashboard step)."""
    b = await request.json()
    hid = nid("hook_")
    S["hooks"][hid] = {"gateway": b["gateway"], "url": b["url"], "secret": b["secret"]}
    return {"id": hid}


@app.get("/_log")
async def log():
    return {"log": LOG[-200:], "hooks": list(S["hooks"].values())}


# ------------------------------------------------------------------ Stripe ---

@app.get("/stripe/v1/account")
async def st_account(request: Request):
    if refused(request):
        return deny("stripe")
    return {"id": "acct_emulated", "country": "AE", "default_currency": "aed", "settings": {"dashboard": {"display_name": "Emulated Merchant LLC"}}}


@app.get("/stripe/v1/balance")
async def st_balance(request: Request):
    if refused(request):
        return deny("stripe")
    key = request.headers.get("authorization", "")
    return {"object": "balance", "livemode": "_live_" in key}


@app.post("/stripe/v1/webhook_endpoints")
async def st_hook(request: Request):
    if refused(request):
        return deny("stripe")
    raw = (await request.body()).decode()
    url = parse_qs(raw)["url"][0]
    hid, secret = nid("we_"), "whsec_" + hashlib.sha256(url.encode()).hexdigest()[:24]
    S["hooks"][hid] = {"gateway": "stripe", "url": url, "secret": secret}
    return {"id": hid, "url": url, "secret": secret, "status": "enabled"}


@app.post("/stripe/v1/webhook_endpoints/{hid}")
async def st_hook_move(hid: str, request: Request):
    b = await body_of(request)
    if hid not in S["hooks"]:
        return JSONResponse({"error": {"message": "No such webhook endpoint"}}, 404)
    S["hooks"][hid]["url"] = b.get("url", S["hooks"][hid]["url"])
    return {"id": hid, "url": S["hooks"][hid]["url"]}


@app.get("/stripe/v1/prices")
async def st_prices(request: Request):
    keys = [v for k, v in request.query_params.multi_items() if k.startswith("lookup_keys")]
    found = [p for p in S["prices"].values() if p["lookup_key"] in keys]
    return {"object": "list", "data": found}


@app.post("/stripe/v1/prices")
async def st_price(request: Request):
    b = await body_of(request)
    pid = nid("price_")
    S["prices"][pid] = {"id": pid, "lookup_key": b.get("lookup_key"), "unit_amount": int(b["unit_amount"]), "currency": b["currency"],
                        "interval": b.get("recurring[interval]"), "interval_count": int(b.get("recurring[interval_count]", 1))}
    return S["prices"][pid]


@app.post("/stripe/v1/checkout/sessions")
async def st_session(request: Request):
    if refused(request):
        return deny("stripe")
    b = await body_of(request)
    cs = nid("cs_test_")
    mode = b.get("mode", "payment")
    if mode == "subscription":
        if b.get("line_items[0][price]") not in S["prices"]:
            # As Stripe: an unknown price is the caller's error, named.
            return JSONResponse({"error": {"type": "invalid_request_error", "code": "resource_missing", "param": "line_items[0][price]",
                                           "message": f"No such price: '{b.get('line_items[0][price]')}'"}}, 400)
        price = S["prices"][b["line_items[0][price]"]]
        amount, currency = price["unit_amount"], price["currency"]
    else:
        amount = sum(int(v) * int(b.get(k.replace("[price_data][unit_amount]", "[quantity]"), 1))
                     for k, v in b.items() if k.endswith("[price_data][unit_amount]"))
        currency = next((v for k, v in b.items() if k.endswith("[price_data][currency]")), "usd")
    meta = {k[len("metadata["):-1]: v for k, v in b.items() if k.startswith("metadata[")}
    sub_meta = {k[len("subscription_data[metadata]["):-1]: v for k, v in b.items() if k.startswith("subscription_data[metadata][")}
    S["sessions"][cs] = {"id": cs, "object": "checkout.session", "mode": mode, "status": "open", "payment_status": "unpaid",
                         "amount_total": amount, "currency": currency, "metadata": meta, "client_reference_id": b.get("client_reference_id"),
                         "success_url": b["success_url"], "cancel_url": b["cancel_url"], "subscription": None, "payment_intent": None,
                         "price": b.get("line_items[0][price]"), "sub_meta": sub_meta,
                         "trial": int(b.get("subscription_data[trial_period_days]", 0) or 0), "url": f"{BASE}/stripe/pay/{cs}"}
    record("stripe.session", id=cs, mode=mode, amount=amount, currency=currency)
    return {k: v for k, v in S["sessions"][cs].items() if k not in ("price", "sub_meta", "trial")}


@app.get("/stripe/v1/checkout/sessions/{cs}")
async def st_get_session(cs: str):
    s = S["sessions"].get(cs)
    if not s:
        return JSONResponse({"error": {"message": "No such checkout.session"}}, 404)
    return {k: v for k, v in s.items() if k not in ("price", "sub_meta", "trial")}


def _sub_view(sid: str) -> dict:
    return S["subs"][sid]


# A subscription the gateway does not know (another account's, or from before
# a restart here): each gateway's own answer.
def st_no_sub(sid: str) -> JSONResponse:
    return JSONResponse({"error": {"type": "invalid_request_error", "code": "resource_missing", "param": "id",
                                   "message": f"No such subscription: '{sid}'"}}, 404)


def rz_no_sub() -> JSONResponse:
    return JSONResponse({"error": {"code": "BAD_REQUEST_ERROR", "description": "The id provided does not exist"}}, 400)


def pp_no_sub() -> JSONResponse:
    return JSONResponse({"name": "RESOURCE_NOT_FOUND", "message": "The specified resource does not exist.",
                         "details": [{"issue": "INVALID_RESOURCE_ID", "description": "Requested resource ID was not found."}]}, 404)


@app.get("/stripe/v1/subscriptions/{sid}")
async def st_get_sub(sid: str):
    if sid not in S["subs"]:
        return st_no_sub(sid)
    return _sub_view(sid)


@app.post("/stripe/v1/subscriptions/{sid}")
async def st_update_sub(sid: str, request: Request):
    b = await body_of(request)
    if sid not in S["subs"]:
        return st_no_sub(sid)
    sub = S["subs"][sid]
    if sub["status"] == "canceled":
        # As Stripe: a canceled subscription can no longer be changed.
        return JSONResponse({"error": {"type": "invalid_request_error",
                                       "message": "A canceled subscription can only update its cancellation_details and metadata."}}, 400)
    if b.get("cancel_at_period_end") == "true":
        sub["cancel_at_period_end"] = True
    deliver("stripe", {"id": nid("evt_"), "type": "customer.subscription.updated", "data": {"object": sub}})
    return sub


@app.delete("/stripe/v1/subscriptions/{sid}")
async def st_delete_sub(sid: str):
    if sid not in S["subs"]:
        return st_no_sub(sid)
    sub = S["subs"][sid]
    if sub["status"] == "canceled":
        return JSONResponse({"error": {"type": "invalid_request_error", "message": "This subscription has already been canceled."}}, 400)
    # As Stripe: ended now, and it says when (`ended_at`, `canceled_at`).
    sub["status"], sub["canceled_at"], sub["ended_at"] = "canceled", now(), now()
    deliver("stripe", {"id": nid("evt_"), "type": "customer.subscription.deleted", "data": {"object": sub}})
    return sub


@app.post("/stripe/v1/refunds")
async def st_refund(request: Request):
    b = await body_of(request)
    return {"id": nid("re_"), "status": "succeeded", "payment_intent": b.get("payment_intent")}


@app.post("/stripe/v1/billing_portal/sessions")
async def st_portal(request: Request):
    b = await body_of(request)
    return {"url": f"{BASE}/stripe/portal?return={b.get('return_url', '')}"}


@app.get("/stripe/pay/{cs}", response_class=HTMLResponse)
async def st_page(cs: str):
    s = S["sessions"][cs]
    what = f"{s['amount_total'] / 100:.2f} {s['currency'].upper()}" + (" / subscription" if s["mode"] == "subscription" else "")
    return f"""<html><body style="font-family:sans-serif;max-width:420px;margin:60px auto" data-emulator="stripe">
      <h2>Stripe Checkout (emulated)</h2><p data-amount>{what}</p>
      <form method="post" action="/stripe/pay/{cs}"><button name="outcome" value="paid" id="pay">Pay</button>
      <button name="outcome" value="cancel" id="cancel">Cancel</button></form></body></html>"""


@app.post("/stripe/pay/{cs}")
async def st_pay(cs: str, request: Request):
    form = await body_of(request)
    s = S["sessions"][cs]
    if form.get("outcome") != "paid":
        s["status"] = "expired"
        return RedirectResponse(s["cancel_url"], 303)
    s["status"], s["payment_status"] = "complete", "paid"
    if s["mode"] == "subscription":
        sid = nid("sub_")
        start = now()
        trial = s["trial"]
        price = S["prices"][s["price"]]
        days = {"day": 1, "week": 7, "month": 30, "year": 365}[price["interval"]] * price["interval_count"]
        S["subs"][sid] = {"id": sid, "object": "subscription", "status": "trialing" if trial else "active", "customer": nid("cus_"),
                          "cancel_at_period_end": False, "metadata": s["sub_meta"], "price": price["id"],
                          "items": {"data": [{"current_period_end": start + (trial or days) * 86400}]},
                          "current_period_end": start + (trial or days) * 86400}
        s["subscription"] = sid
        deliver("stripe", {"id": nid("evt_"), "type": "checkout.session.completed",
                           "data": {"object": {k: v for k, v in s.items() if k not in ("price", "sub_meta", "trial")}}})
        deliver("stripe", {"id": nid("evt_"), "type": "invoice.paid", "data": {"object": {"id": nid("in_"), "subscription": sid,
                                                                                            "subscription_details": {"metadata": s["sub_meta"]}}}})
    else:
        s["payment_intent"] = nid("pi_")
        deliver("stripe", {"id": nid("evt_"), "type": "checkout.session.completed",
                           "data": {"object": {k: v for k, v in s.items() if k not in ("price", "sub_meta", "trial")}}})
    record("stripe.paid", id=cs)
    return RedirectResponse(s["success_url"], 303)


@app.post("/_stripe/renew/{sid}")
async def st_renew(sid: str, failed: int = 0):
    """For a test: the next period is charged (or fails)."""
    sub = S["subs"][sid]
    if failed:
        sub["status"] = "past_due"
        deliver("stripe", {"id": nid("evt_"), "type": "invoice.payment_failed", "data": {"object": {"subscription": sid}}})
    else:
        sub["current_period_end"] += 30 * 86400
        sub["items"]["data"][0]["current_period_end"] = sub["current_period_end"]
        sub["status"] = "active"
        deliver("stripe", {"id": nid("evt_"), "type": "invoice.paid", "data": {"object": {"subscription": sid}}})
    return sub


# ---------------------------------------------------------------- Razorpay ---

def _rz_key_secret(request: Request) -> tuple[str, str]:
    raw = base64.b64decode(request.headers.get("authorization", "Basic Og==")[6:]).decode()
    key_id, _, secret = raw.partition(":")
    return key_id, secret


@app.get("/razorpay/v1/orders")
async def rz_orders(request: Request):
    if refused(request):
        return deny("razorpay")
    return {"entity": "collection", "count": 0, "items": []}


@app.post("/razorpay/v1/orders")
async def rz_order(request: Request):
    if refused(request):
        return deny("razorpay")
    b = await request.json()
    extra = set(b) - {"amount", "currency", "receipt", "notes", "partial_payment", "first_payment_min_amount"}
    if extra:
        return JSONResponse({"error": {"code": "BAD_REQUEST_ERROR", "description": f"{', '.join(extra)} is/are not required and should not be sent"}}, 400)
    oid = nid("order_")
    S["rz_orders"][oid] = {"id": oid, "entity": "order", "amount": b["amount"], "amount_paid": 0, "currency": b["currency"],
                           "receipt": b.get("receipt"), "status": "created", "notes": b.get("notes", {})}
    record("razorpay.order", id=oid, amount=b["amount"])
    return S["rz_orders"][oid]


@app.get("/razorpay/v1/orders/{oid}")
async def rz_get_order(oid: str):
    return S["rz_orders"][oid]


@app.get("/razorpay/v1/orders/{oid}/payments")
async def rz_order_payments(oid: str):
    return {"items": [p for p in S["rz_payments"].values() if p.get("order_id") == oid]}


@app.get("/razorpay/v1/payments/{pid}")
async def rz_payment(pid: str):
    return S["rz_payments"][pid]


@app.post("/razorpay/v1/payments/{pid}/capture")
async def rz_capture(pid: str):
    S["rz_payments"][pid]["status"] = "captured"
    return S["rz_payments"][pid]


@app.post("/razorpay/v1/payments/{pid}/refund")
async def rz_refund(pid: str):
    return {"id": nid("rfnd_"), "status": "processed", "payment_id": pid}


@app.post("/razorpay/_checkout")
async def rz_checkout(request: Request):
    """Razorpay's Checkout window: the payer pays an order (or authorises a subscription)."""
    b = await request.json()
    secret = b["key_secret"]
    pid = nid("pay_")
    if b.get("order_id"):
        order = S["rz_orders"][b["order_id"]]
        S["rz_payments"][pid] = {"id": pid, "entity": "payment", "order_id": order["id"], "amount": order["amount"],
                                 "currency": order["currency"], "status": "authorized", "notes": order["notes"]}
        order["status"], order["amount_paid"] = "paid", order["amount"]
        sig = hmac.new(secret.encode(), f"{order['id']}|{pid}".encode(), hashlib.sha256).hexdigest()
        deliver("razorpay", {"event": "payment.captured", "payload": {"payment": {"entity": {**S["rz_payments"][pid], "status": "captured"}}}})
        return {"razorpay_payment_id": pid, "razorpay_order_id": order["id"], "razorpay_signature": sig}
    sub = S["rz_subs"][b["subscription_id"]]
    sub["status"] = "active"
    sub["current_end"] = now() + 30 * 86400
    sig = hmac.new(secret.encode(), f"{pid}|{sub['id']}".encode(), hashlib.sha256).hexdigest()
    deliver("razorpay", {"event": "subscription.activated", "payload": {"subscription": {"entity": sub}}})
    return {"razorpay_payment_id": pid, "razorpay_subscription_id": sub["id"], "razorpay_signature": sig}


@app.post("/razorpay/v1/plans")
async def rz_plan(request: Request):
    b = await request.json()
    if b.get("period") == "daily" and int(b.get("interval", 1)) < 7:
        return JSONResponse({"error": {"description": "interval must be at least 7 for daily plans"}}, 400)
    pid = nid("plan_")
    S["rz_plans"][pid] = {"id": pid, **b}
    return S["rz_plans"][pid]


@app.post("/razorpay/v1/subscriptions")
async def rz_sub(request: Request):
    b = await request.json()
    if b.get("plan_id") not in S.get("rz_plans", {}):
        return JSONResponse({"error": {"code": "BAD_REQUEST_ERROR", "description": "The id provided does not exist", "field": "plan_id"}}, 400)
    sid = nid("sub_")
    S["rz_subs"][sid] = {"id": sid, "entity": "subscription", "plan_id": b["plan_id"], "status": "created", "notes": b.get("notes", {}),
                         "total_count": b["total_count"], "short_url": f"{BASE}/razorpay/hosted/{sid}", "current_end": None}
    return S["rz_subs"][sid]


@app.get("/razorpay/v1/subscriptions/{sid}")
async def rz_get_sub(sid: str):
    if sid not in S["rz_subs"]:
        return rz_no_sub()
    return S["rz_subs"][sid]


@app.post("/razorpay/v1/subscriptions/{sid}/cancel")
async def rz_cancel(sid: str, request: Request):
    b = await request.json()
    if sid not in S["rz_subs"]:
        return rz_no_sub()
    if S["rz_subs"][sid]["status"] in ("cancelled", "completed", "expired"):
        return JSONResponse({"error": {"code": "BAD_REQUEST_ERROR",
                                       "description": "Subscription is not cancellable in cancelled status."}}, 400)
    if not b.get("cancel_at_cycle_end"):
        S["rz_subs"][sid]["status"], S["rz_subs"][sid]["ended_at"] = "cancelled", now()
    deliver("razorpay", {"event": "subscription.cancelled" if not b.get("cancel_at_cycle_end") else "subscription.updated",
                         "payload": {"subscription": {"entity": S["rz_subs"][sid]}}})
    return S["rz_subs"][sid]


# ------------------------------------------------------------------ PayPal ---

@app.post("/paypal/{env}/v1/oauth2/token")
@app.post("/paypal/v1/oauth2/token")
async def pp_token(request: Request, env: str = "live"):
    if refused(request):
        return deny("paypal")
    return {"access_token": "EMULATED", "token_type": "Bearer", "app_id": "APP-EMULATED", "expires_in": 32400}


@app.post("/paypal/{env}/v1/notifications/webhooks")
async def pp_hook(env: str, request: Request):
    b = await request.json()
    hid = nid("WH-")
    S["hooks"][hid] = {"gateway": "paypal", "url": b["url"], "secret": hid}
    return JSONResponse({"id": hid, "url": b["url"]}, 201)


@app.post("/paypal/{env}/v1/notifications/verify-webhook-signature")
async def pp_verify(env: str, request: Request):
    raw = (await request.body()).decode()
    body = json.loads(raw)
    sent = S["sent"].get(body.get("transmission_id"))
    ok = sent is not None and json.loads(sent) == body.get("webhook_event") and body.get("webhook_id") in S["hooks"]
    return {"verification_status": "SUCCESS" if ok else "FAILURE"}


@app.post("/paypal/{env}/v2/checkout/orders")
async def pp_order(env: str, request: Request):
    b = await request.json()
    oid = nid("ORDER")
    ctx = b.get("payment_source", {}).get("paypal", {}).get("experience_context", {})
    S["pp_orders"][oid] = {"id": oid, "status": "PAYER_ACTION_REQUIRED", "purchase_units": b["purchase_units"], "ctx": ctx}
    return JSONResponse({"id": oid, "status": "PAYER_ACTION_REQUIRED",
                         "links": [{"rel": "payer-action", "href": f"{BASE}/paypal/approve/{oid}"}]}, 200)


@app.get("/paypal/approve/{oid}", response_class=HTMLResponse)
async def pp_page(oid: str):
    return f"""<html><body style="font-family:sans-serif;max-width:420px;margin:60px auto" data-emulator="paypal">
      <h2>PayPal (emulated sandbox)</h2><form method="post" action="/paypal/approve/{oid}">
      <button name="outcome" value="approve" id="approve">Approve</button><button name="outcome" value="cancel" id="cancel">Cancel</button></form></body></html>"""


@app.post("/paypal/approve/{oid}")
async def pp_approve(oid: str, request: Request):
    form = await body_of(request)
    if oid in S["pp_orders"]:
        o = S["pp_orders"][oid]
        if form.get("outcome") != "approve":
            return RedirectResponse(o["ctx"]["cancel_url"], 303)
        o["status"] = "APPROVED"
        sep = "&" if "?" in o["ctx"]["return_url"] else "?"
        return RedirectResponse(f"{o['ctx']['return_url']}{sep}token={oid}&PayerID=PAYER1", 303)
    sub = S["pp_subs"][oid]
    if form.get("outcome") != "approve":
        return RedirectResponse(sub["ctx"]["cancel_url"], 303)
    sub["status"] = "ACTIVE"
    sub["billing_info"] = {"next_billing_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now() + 30 * 86400))}
    deliver("paypal", {"id": nid("WH-EVT-"), "event_type": "BILLING.SUBSCRIPTION.ACTIVATED", "resource": {"id": oid, "custom_id": sub["custom_id"]}})
    sep = "&" if "?" in sub["ctx"]["return_url"] else "?"
    return RedirectResponse(f"{sub['ctx']['return_url']}{sep}subscription_id={oid}&ba_token=BA1", 303)


@app.post("/paypal/{env}/v2/checkout/orders/{oid}/capture")
async def pp_capture(env: str, oid: str):
    o = S["pp_orders"][oid]
    if o["status"] == "COMPLETED":
        return JSONResponse({"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "ORDER_ALREADY_CAPTURED"}]}, 422)
    if o["status"] != "APPROVED":
        return JSONResponse({"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "ORDER_NOT_APPROVED"}]}, 422)
    o["status"] = "COMPLETED"
    unit = o["purchase_units"][0]
    cap = {"id": nid("CAP"), "status": "COMPLETED", "amount": unit["amount"], "custom_id": unit.get("custom_id"),
           "supplementary_data": {"related_ids": {"order_id": oid}}}
    unit["payments"] = {"captures": [cap]}
    record("paypal.capture", id=oid, capture=cap["id"], amount=unit["amount"])
    deliver("paypal", {"id": nid("WH-EVT-"), "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": cap})
    return JSONResponse({"id": oid, "status": "COMPLETED", "purchase_units": [unit]}, 201)


def _pp_capture(cid: str) -> dict | None:
    for o in S["pp_orders"].values():
        for cap in (o["purchase_units"][0].get("payments") or {}).get("captures") or []:
            if cap["id"] == cid:
                return cap
    return None


@app.get("/paypal/{env}/v2/payments/captures/{cid}")
async def pp_get_capture(env: str, cid: str):
    cap = _pp_capture(cid)
    return cap if cap else JSONResponse({"name": "RESOURCE_NOT_FOUND"}, 404)


@app.post("/paypal/{env}/v2/payments/captures/{cid}/refund")
async def pp_refund(env: str, cid: str, request: Request):
    """As PayPal: no amount refunds what is left; an amount is in the capture's currency and no more than is left."""
    cap = _pp_capture(cid)
    if not cap:
        return JSONResponse({"name": "RESOURCE_NOT_FOUND"}, 404)
    b = await body_of(request)
    paid = round(float(cap["amount"]["value"]) * 100)
    done = cap.setdefault("refunded_minor", 0)
    want = round(float(b["amount"]["value"]) * 100) if b.get("amount") else paid - done
    if b.get("amount") and b["amount"].get("currency_code") != cap["amount"]["currency_code"]:
        return JSONResponse({"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "CURRENCY_MISMATCH"}]}, 422)
    if want <= 0 or done + want > paid:
        return JSONResponse({"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "REFUND_AMOUNT_EXCEEDED"}]}, 422)
    cap["refunded_minor"] = done + want
    record("paypal.refund", id=cid, amount=want, of=paid)
    return JSONResponse({"id": nid("RF"), "status": "COMPLETED", "amount": {"value": f"{want / 100:.2f}", "currency_code": cap["amount"]["currency_code"]}}, 201)


@app.get("/paypal/{env}/v2/checkout/orders/{oid}")
async def pp_get_order(env: str, oid: str):
    o = S["pp_orders"][oid]
    return {"id": oid, "status": o["status"], "purchase_units": o["purchase_units"]}


@app.post("/paypal/{env}/v1/catalogs/products")
async def pp_product(env: str, request: Request):
    b = await request.json()
    pid = nid("PROD-")
    S["pp_products"][pid] = {"id": pid, **b}
    return JSONResponse(S["pp_products"][pid], 201)


@app.post("/paypal/{env}/v1/billing/plans")
async def pp_plan(env: str, request: Request):
    b = await request.json()
    pid = nid("P-")
    S["pp_plans"][pid] = {"id": pid, **b}
    return JSONResponse(S["pp_plans"][pid], 201)


@app.post("/paypal/{env}/v1/billing/subscriptions")
async def pp_sub(env: str, request: Request):
    b = await request.json()
    if b.get("plan_id") not in S["pp_plans"]:
        return JSONResponse({"name": "RESOURCE_NOT_FOUND", "message": "The specified resource does not exist.",
                             "details": [{"field": "/plan_id", "issue": "INVALID_RESOURCE_ID", "description": "Requested resource ID was not found."}]}, 404)
    sid = nid("I-")
    S["pp_subs"][sid] = {"id": sid, "status": "APPROVAL_PENDING", "plan_id": b["plan_id"], "custom_id": b.get("custom_id"),
                         "ctx": b.get("application_context", {})}
    return JSONResponse({"id": sid, "status": "APPROVAL_PENDING", "links": [{"rel": "approve", "href": f"{BASE}/paypal/approve/{sid}"}]}, 201)


@app.get("/paypal/{env}/v1/billing/subscriptions/{sid}")
async def pp_get_sub(env: str, sid: str):
    if sid not in S["pp_subs"]:
        return pp_no_sub()
    s = S["pp_subs"][sid]
    return {k: v for k, v in s.items() if k != "ctx"}


@app.post("/paypal/{env}/v1/billing/subscriptions/{sid}/cancel")
async def pp_cancel(env: str, sid: str):
    if sid not in S["pp_subs"]:
        return pp_no_sub()
    if S["pp_subs"][sid]["status"] in ("CANCELLED", "EXPIRED"):
        return JSONResponse({"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "SUBSCRIPTION_STATUS_INVALID",
                             "description": "Invalid subscription status for cancel action."}]}, 422)
    S["pp_subs"][sid]["status"] = "CANCELLED"
    # As PayPal: a cancelled subscription has no next billing time.
    S["pp_subs"][sid].get("billing_info", {}).pop("next_billing_time", None)
    deliver("paypal", {"id": nid("WH-EVT-"), "event_type": "BILLING.SUBSCRIPTION.CANCELLED",
                       "resource": {"id": sid, "custom_id": S["pp_subs"][sid]["custom_id"]}})
    return Response(status_code=204)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("EMULATOR_PORT", "6599")), log_level="warning")
