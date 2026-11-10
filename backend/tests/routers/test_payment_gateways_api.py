"""Settings → Integrations → Payments: an organisation's gateways, through the API.

Every answer the gateway can give a key (accepted, refused, unreachable) and
every kind of person (admin, member, another organisation, signed out) is
asked here, with the gateway itself replaced by a recorded mock transport —
so what Forge SENDS each gateway is checked too, not only what it does with
the answer. Keys never come back in any response, and are not readable in the
database row.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from main import app
from services.payments import providers as P

pytestmark = pytest.mark.asyncio

# Fixture keys are split in two ("sk_test_" "..."): whole, a secret scanner takes them for real ones.
RZP_TEST = {"key_id": "rzp_test_" "AbCdEf123456", "key_secret": "s3cretTESTvalue0001"}
RZP_LIVE = {"key_id": "rzp_live_" "ZyXwVu987654", "key_secret": "s3cretLIVEvalue0002"}
STRIPE_TEST = {"secret_key": "sk_test_" "51Abcdefghijklmnopqrstuv", "publishable_key": "pk_test_" "51Abcdefghij"}
PAYPAL_SANDBOX = {"client_id": "AbcSandboxClientId123", "client_secret": "EFGsandboxsecret456"}


class Gateway:
    """A stand-in for the gateways' APIs: answers by URL, records each request."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.answer: dict[str, tuple[int, dict]] = {}
        self.down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            raise httpx.ConnectError("no route", request=request)
        for fragment, (status, body) in self.answer.items():
            if fragment in str(request.url):
                return httpx.Response(status, json=body)
        return httpx.Response(200, json={})


@pytest.fixture
def gateway(monkeypatch):
    gw = Gateway()
    monkeypatch.setenv("FORGE_INTEGRATIONS_SECRET", "test-secret-for-payment-gateways-0123")
    monkeypatch.delenv("FORGE_PAYMENTS_EMULATOR", raising=False)
    monkeypatch.setattr(P, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(gw.handler)))
    return gw


async def _signup(email: str) -> tuple[AsyncClient, str]:
    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    r = await c.post("/api/auth/signup", json={"email": email, "name": email.split("@")[0], "password": "Testpass123"})
    assert r.status_code == 201, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c, (await c.get("/api/auth/me")).json()["id"]


async def _join(org_id: str, user_id: str, role: str) -> None:
    from database import async_session
    from models.org import InviteStatus, OrgMember, OrgMemberRole
    async with async_session() as db:
        db.add(OrgMember(org_id=uuid.UUID(org_id), user_id=uuid.UUID(user_id), role=OrgMemberRole(role),
                         invite_status=InviteStatus.accepted))
        await db.commit()


@pytest_asyncio.fixture
async def people(auth_client, org_id):
    member, mid = await _signup("payments-member@example.com")
    await _join(org_id, mid, "member")
    outsider, _ = await _signup("payments-outsider@example.com")
    anon = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    try:
        yield {"admin": auth_client, "member": member, "outsider": outsider, "anon": anon}
    finally:
        for c in (member, outsider, anon):
            await c.aclose()


def _base(org_id: str) -> str:
    return f"/api/orgs/{org_id}/payment-gateways"


def _no_secret_in(text: str, *values: str) -> None:
    for v in values:
        assert v not in text, f"a key value came back: {v[:6]}…"


# --------------------------------------------------------------------------- #

async def test_the_catalog_says_what_each_gateway_needs(auth_client):
    r = await auth_client.get("/api/payment-gateways/providers")
    assert r.status_code == 200
    ids = [p["id"] for p in r.json()]
    assert ids == ["razorpay", "stripe", "paypal"]
    rzp = r.json()[0]
    assert [f["key"] for f in rzp["fields"]] == ["key_id", "key_secret"]
    assert rzp["fields"][0]["prefix"] == {"test": ["rzp_test_"], "live": ["rzp_live_"]}
    assert rzp["webhooks"] == "manual" and rzp["coverage"] == "domestic" and rzp["homeCountry"] == "IN"
    paypal = r.json()[2]
    assert "INR" not in paypal["currencies"] and "AED" not in paypal["currencies"]


async def test_razorpay_test_keys_are_checked_sealed_and_never_returned(people, org_id, gateway):
    r = await people["admin"].post(_base(org_id), json={"provider": "razorpay", "label": "Razorpay India",
                                                        "test": RZP_TEST})
    assert r.status_code == 201, r.text
    body = r.json()
    _no_secret_in(r.text, RZP_TEST["key_secret"], RZP_TEST["key_id"])
    assert body["status"] == "test_only" and body["isDefault"] is True
    assert body["modes"]["test"]["set"] and not body["modes"]["live"]["set"]
    assert body["modes"]["test"]["masked"]["key_secret"].endswith("0001")
    assert body["currencies"] == ["INR"] and body["homeCountry"] == "IN" and body["coverage"] == "domestic"
    # What Forge asked Razorpay: one read of its orders, with Basic auth of the test keys.
    (req,) = gateway.requests
    assert req.method == "GET" and req.url.path == "/v1/orders" and req.url.params["count"] == "1"
    assert req.url.host == "api.razorpay.com"
    import base64
    assert req.headers["authorization"] == "Basic " + base64.b64encode(
        f"{RZP_TEST['key_id']}:{RZP_TEST['key_secret']}".encode()).decode()
    # And the row holds ciphertext only.
    from database import async_session
    from models.payment_gateway import PaymentGateway
    async with async_session() as db:
        row = await db.get(PaymentGateway, uuid.UUID(body["id"]))
        dumped = json.dumps({c: str(getattr(row, c)) for c in ("test_ct", "test_iv", "live_ct", "checks")})
    _no_secret_in(dumped, RZP_TEST["key_secret"], RZP_TEST["key_id"])
    assert row.live_ct is None


async def test_a_live_key_in_the_test_slot_is_refused_without_asking_anyone(people, org_id, gateway):
    r = await people["admin"].post(_base(org_id), json={"provider": "razorpay", "test": RZP_LIVE})
    assert r.status_code == 400
    assert "live key" in r.json()["detail"] and "Live keys go under Live" in r.json()["detail"]
    assert gateway.requests == []
    r = await people["admin"].post(_base(org_id), json={"provider": "stripe", "live": {"secret_key": "pk_live_abc12345678"}})
    assert r.status_code == 400 and "should start with sk_live_ or rk_live_" in r.json()["detail"]


async def test_keys_the_gateway_refuses_are_not_saved(people, org_id, gateway):
    gateway.answer["/v1/orders"] = (401, {"error": {"code": "BAD_REQUEST_ERROR",
                                                    "description": "The api key provided is invalid"}})
    r = await people["admin"].post(_base(org_id), json={"provider": "razorpay", "test": RZP_TEST})
    assert r.status_code == 400
    assert "Razorpay refused these keys: The api key provided is invalid. Copy them" in r.json()["detail"]
    listed = (await people["admin"].get(_base(org_id))).json()
    assert listed["gateways"] == []


async def test_a_gateway_that_cannot_be_reached_is_saved_and_said_unchecked(people, org_id, gateway):
    gateway.down = True
    r = await people["admin"].post(_base(org_id), json={"provider": "razorpay", "test": RZP_TEST})
    assert r.status_code == 201
    assert r.json()["status"] == "unchecked"
    assert "could not reach Razorpay" in r.json()["modes"]["test"]["check"]["error"]
    # Checked again once it is back: ready for test.
    gateway.down = False
    again = await people["admin"].post(f"{_base(org_id)}/{r.json()['id']}/check")
    assert again.status_code == 200 and again.json()["status"] == "test_only"


async def test_stripe_says_whose_account_it_is(people, org_id, gateway):
    gateway.answer["/v1/account"] = (200, {"id": "acct_1Abc", "country": "AE", "default_currency": "aed",
                                           "settings": {"dashboard": {"display_name": "Acme FZ-LLC"}}})
    r = await people["admin"].post(_base(org_id), json={"provider": "stripe", "test": STRIPE_TEST,
                                                        "currencies": ["AED", "USD"]})
    assert r.status_code == 201, r.text
    check = r.json()["modes"]["test"]["check"]
    assert check["account"] == "Acme FZ-LLC" and check["country"] == "AE" and check["currency"] == "AED"
    assert gateway.requests[0].headers["authorization"] == f"Bearer {STRIPE_TEST['secret_key']}"
    _no_secret_in(r.text, STRIPE_TEST["secret_key"])


async def test_a_restricted_stripe_key_is_proved_by_the_balance_and_its_mode(people, org_id, gateway):
    gateway.answer["/v1/account"] = (403, {"error": {"message": "The provided key does not have access"}})
    gateway.answer["/v1/balance"] = (200, {"object": "balance", "livemode": True})
    r = await people["admin"].post(_base(org_id), json={"provider": "stripe",
                                                        "test": {"secret_key": "rk_test_" "51Restricted00000"}})
    assert r.status_code == 400 and "Stripe says these are live keys" in r.json()["detail"]
    gateway.answer["/v1/balance"] = (200, {"object": "balance", "livemode": False})
    r = await people["admin"].post(_base(org_id), json={"provider": "stripe",
                                                        "test": {"secret_key": "rk_test_" "51Restricted00000"}})
    assert r.status_code == 201 and r.json()["status"] == "test_only"


async def test_paypal_sandbox_keys_go_to_the_sandbox(people, org_id, gateway):
    gateway.answer["/v1/oauth2/token"] = (200, {"access_token": "A21AA", "app_id": "APP-80W284485P519543T"})
    r = await people["admin"].post(_base(org_id), json={"provider": "paypal", "test": PAYPAL_SANDBOX})
    assert r.status_code == 201, r.text
    (req,) = gateway.requests
    assert req.url.host == "api-m.sandbox.paypal.com" and req.method == "POST"
    assert req.content == b"grant_type=client_credentials"
    assert r.json()["modes"]["test"]["check"]["accountId"] == "APP-80W284485P519543T"
    # A currency PayPal does not take is refused, by name.
    r = await people["admin"].patch(f"{_base(org_id)}/{r.json()['id']}", json={"currencies": ["USD", "INR"]})
    assert r.status_code == 400 and "PayPal does not take payments in INR" in r.json()["detail"]


async def test_paypal_live_keys_refused_say_where_they_may_belong(people, org_id, gateway):
    gateway.answer["/v1/oauth2/token"] = (401, {"error": "invalid_client", "error_description": "Client Authentication failed"})
    r = await people["admin"].post(_base(org_id), json={"provider": "paypal", "live": PAYPAL_SANDBOX})
    assert r.status_code == 400
    assert gateway.requests[0].url.host == "api-m.paypal.com"
    assert "save them under Sandbox" in r.json()["detail"]


async def test_who_may_see_and_change_the_gateways(people, org_id, gateway):
    made = (await people["admin"].post(_base(org_id), json={"provider": "razorpay", "test": RZP_TEST})).json()
    gid = made["id"]
    # A member sees the gateway, to choose it for an app, but no key, not even masked.
    seen = await people["member"].get(_base(org_id))
    assert seen.status_code == 200 and seen.json()["canManage"] is False
    assert seen.json()["gateways"][0]["id"] == gid and "masked" not in seen.json()["gateways"][0]["modes"]["test"]
    assert (await people["member"].post(_base(org_id), json={"provider": "razorpay", "test": RZP_TEST})).status_code == 403
    assert (await people["member"].patch(f"{_base(org_id)}/{gid}", json={"label": "Mine"})).status_code == 403
    assert (await people["member"].delete(f"{_base(org_id)}/{gid}")).status_code == 403
    assert (await people["member"].post(f"{_base(org_id)}/{gid}/check")).status_code == 403
    for who in ("outsider",):
        assert (await people[who].get(_base(org_id))).status_code == 403
        assert (await people[who].patch(f"{_base(org_id)}/{gid}", json={"label": "x"})).status_code == 403
    assert (await people["anon"].get(_base(org_id))).status_code == 401
    # Another organisation's admin cannot reach this gateway through their own org id.
    other = (await people["outsider"].post("/api/orgs", json={"name": "Elsewhere", "slug": "elsewhere-pay"})).json()["id"]
    assert (await people["outsider"].patch(f"{_base(other)}/{gid}", json={"label": "stolen"})).status_code == 404
    assert (await people["outsider"].delete(f"{_base(other)}/{gid}")).status_code == 404


async def test_editing_keeps_what_is_not_retyped_and_rechecks_what_is(people, org_id, gateway):
    made = (await people["admin"].post(_base(org_id), json={"provider": "razorpay", "test": RZP_TEST})).json()
    gid = made["id"]
    gateway.requests.clear()
    r = await people["admin"].patch(f"{_base(org_id)}/{gid}", json={"test": {"key_secret": "aNewSecretValue9999"}})
    assert r.status_code == 200, r.text
    assert r.json()["modes"]["test"]["masked"]["key_secret"].endswith("9999")
    import base64
    assert gateway.requests[0].headers["authorization"] == "Basic " + base64.b64encode(
        f"{RZP_TEST['key_id']}:aNewSecretValue9999".encode()).decode()
    # Live keys added later; both modes now; status ready.
    r = await people["admin"].patch(f"{_base(org_id)}/{gid}", json={"live": RZP_LIVE, "label": "  Razorpay   (India) "})
    assert r.json()["status"] == "ready" and r.json()["label"] == "Razorpay (India)"
    # Clearing one mode is fine; clearing the last is refused.
    r = await people["admin"].patch(f"{_base(org_id)}/{gid}", json={"clear": ["test"]})
    assert r.status_code == 200 and not r.json()["modes"]["test"]["set"]
    r = await people["admin"].patch(f"{_base(org_id)}/{gid}", json={"clear": ["live"]})
    assert r.status_code == 400 and "at least one set of keys" in r.json()["detail"]
    r = await people["admin"].patch(f"{_base(org_id)}/{gid}", json={"provider": "stripe"})
    assert r.status_code == 400 and "cannot change" in r.json()["detail"]


async def test_one_default_and_removal_hands_it_on(people, org_id, gateway):
    a = (await people["admin"].post(_base(org_id), json={"provider": "razorpay", "test": RZP_TEST})).json()
    b = (await people["admin"].post(_base(org_id), json={"provider": "stripe", "test": STRIPE_TEST})).json()
    assert a["isDefault"] is True and b["isDefault"] is False
    r = await people["admin"].patch(f"{_base(org_id)}/{b['id']}", json={"isDefault": True})
    assert r.json()["isDefault"] is True
    listed = (await people["admin"].get(_base(org_id))).json()["gateways"]
    assert [g["isDefault"] for g in listed] == [True, False] and listed[0]["id"] == b["id"]
    gone = await people["admin"].delete(f"{_base(org_id)}/{b['id']}")
    assert gone.status_code == 200 and gone.json()["apps"] == []
    listed = (await people["admin"].get(_base(org_id))).json()["gateways"]
    assert [g["id"] for g in listed] == [a["id"]] and listed[0]["isDefault"] is True
    assert (await people["admin"].delete(f"{_base(org_id)}/{b['id']}")).status_code == 404


async def test_bad_shapes_are_refused_in_words(people, org_id, gateway):
    admin = people["admin"]
    cases = [
        ({"provider": "venmo", "test": {"x": "y"}}, "not a gateway Forge can build in"),
        ({"provider": "razorpay"}, "test mode keys, its live keys, or both"),
        ({"provider": "razorpay", "test": {"key_id": RZP_TEST["key_id"]}}, "add the key secret"),
        ({"provider": "razorpay", "test": {"key_id": "rzp_test_ ab", "key_secret": "x"}}, "has spaces"),
        ({"provider": "stripe", "test": STRIPE_TEST, "coverage": "galactic"}, "domestic, international or both"),
        ({"provider": "stripe", "test": STRIPE_TEST, "coverage": "domestic"}, "needs its home country"),
        ({"provider": "stripe", "test": STRIPE_TEST, "homeCountry": "India"}, "two-letter code"),
        ({"provider": "stripe", "test": STRIPE_TEST, "currencies": []}, "at least one currency"),
        ({"provider": "stripe", "test": STRIPE_TEST, "label": "x" * 81}, "at most 80"),
    ]
    for body, said in cases:
        r = await admin.post(_base(org_id), json=body)
        assert r.status_code == 400, (body, r.text)
        assert said in r.json()["detail"], (said, r.json()["detail"])
    assert (await admin.get(_base(org_id))).json()["gateways"] == []
    assert (await admin.patch(f"{_base(org_id)}/not-a-uuid", json={"label": "x"})).status_code == 404


def test_each_mode_is_sealed_under_its_own_key(monkeypatch):
    monkeypatch.setenv("FORGE_INTEGRATIONS_SECRET", "test-secret-for-payment-gateways-0123")
    from services.payments import gateways as G
    from services.platform_integrations_crypto import CryptoError, decrypt
    gid = uuid.uuid4()
    ct, iv = G.seal(gid, "test", RZP_TEST)
    assert json.loads(decrypt(f"payment_gateway:{gid}:test", ct, iv)) == RZP_TEST
    with pytest.raises(CryptoError):
        decrypt(f"payment_gateway:{gid}:live", ct, iv)
    with pytest.raises(CryptoError):
        decrypt(f"payment_gateway:{uuid.uuid4()}:test", ct, iv)


def test_masking_shows_the_kind_and_last_four():
    assert P.mask("sk_live_" "51HabcdefghijkWXYZ") == "sk_live_••••WXYZ"
    assert P.mask("rzp_test_" "AbCdEf123456") == "rzp_test_••••3456"
    assert P.mask("short") == "••••"
    assert P.mask("EFGsandboxsecret456") == "••••t456"


# --------------------------------------------------------------------------- #
# One application's payments, through the API
# --------------------------------------------------------------------------- #

async def _app_with_definition(admin, org_id: str, description: str) -> tuple[str, Path]:
    from services.project_service import OUTPUT_BASE
    from services.blueprint.service import BlueprintService
    project = (await admin.post(f"/api/orgs/{org_id}/projects", json={"name": "Fit Club"})).json()
    out = Path(OUTPUT_BASE) / project["short_id"]
    svc = BlueprintService.create(output_dir=out, app_id=project["short_id"], name="Fit Club", domain="fitness", description=description)
    svc.doc.setdefault("product", {})["currency"] = "INR"
    svc.save()
    return project["id"], out


async def test_an_apps_payments_are_chosen_from_its_own_organisations_gateways(people, org_id, gateway, monkeypatch):
    from services.payments import need as N
    monkeypatch.setattr(N, "_default_provider", lambda _p: json.dumps({"needed": True, "models": ["subscription"], "access": "app",
        "reason": "Members pay monthly.", "plans": [{"name": "Monthly", "interval": "month", "price": 999}]}))
    admin = people["admin"]
    pid, out = await _app_with_definition(admin, org_id, "A gym where members pay a monthly membership.")
    rzp = (await admin.post(_base(org_id), json={"provider": "razorpay", "label": "Razorpay India", "test": RZP_TEST, "live": RZP_LIVE})).json()
    # Forge decides; the member who builds sees the gateways (no keys) to choose from.
    v = (await people["member"].post(f"/api/projects/{pid}/payments/decide")).json()
    assert v["payments"]["needed"] is True and v["payments"]["models"] == ["subscription"] and v["payments"]["decided"] is False
    assert v["payments"]["plans"][0]["prices"] == {"INR": 999.0}
    assert [g["id"] for g in v["gateways"]] == [rzp["id"]] and "masked" not in v["gateways"][0]["modes"]["test"]
    assert v["canManageGateways"] is False
    assert (await people["outsider"].get(f"/api/projects/{pid}/payments")).status_code == 403
    # Another organisation's gateway cannot be chosen, even by id.
    other_org = (await people["outsider"].post("/api/orgs", json={"name": "Other", "slug": "other-pay"})).json()["id"]
    theirs = (await people["outsider"].post(_base(other_org), json={"provider": "stripe", "test": STRIPE_TEST})).json()
    bad = await people["member"].put(f"/api/projects/{pid}/payments", json={"needed": True, "gateways": [theirs["id"]], "models": ["subscription"],
                                                                         "plans": [{"name": "Monthly", "interval": "month", "prices": {"INR": 999}}]})
    assert bad.status_code == 400 and "not one of your organisation's" in bad.json()["detail"]
    ok = await people["member"].put(f"/api/projects/{pid}/payments", json={"needed": True, "gateways": [rzp["id"]], "models": ["subscription"],
                                                                        "plans": [{"name": "Monthly", "interval": "month", "prices": {"INR": 999}}],
                                                                        "access": "app"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["payments"]["decided"] is True and ok.json()["payments"]["gateways"][0]["label"] == "Razorpay India"
    # The preview's environment carries the TEST keys, never the live ones.
    env = (out / "app" / ".env.local") if (out / "app").is_dir() else (out / ".env.local")
    text = env.read_text() if env.is_file() else ""
    assert RZP_TEST["key_secret"] in text and RZP_LIVE["key_secret"] not in text
    # A decided app is not decided again over the person.
    again = (await people["member"].post(f"/api/projects/{pid}/payments/decide")).json()
    assert again["payments"]["decidedBy"] == "person" and again["payments"]["gateways"][0]["gateway"] == rzp["id"]


async def test_a_gateway_whose_keys_were_refused_is_not_chosen_until_fixed(people, org_id, gateway):
    admin = people["admin"]
    pid, _out = await _app_with_definition(admin, org_id, "A shop selling candles.")
    made = (await admin.post(_base(org_id), json={"provider": "razorpay", "test": RZP_TEST})).json()
    gateway.answer["/v1/orders"] = (401, {"error": {"description": "Authentication failed"}})
    checked = (await admin.post(f"{_base(org_id)}/{made['id']}/check")).json()
    assert checked["status"] == "attention"
    r = await admin.put(f"/api/projects/{pid}/payments", json={"needed": True, "gateways": [made["id"]], "models": ["one_time"]})
    assert r.status_code == 400 and "Fix them in Settings" in r.json()["detail"]
    r = await admin.put(f"/api/projects/{pid}/payments", json={"needed": False, "gateways": []})
    assert r.status_code == 200 and r.json()["payments"]["needed"] is False


# --------------------------------------------------------------------------- #
# Stripe keys typed under Integrations before gateways
# --------------------------------------------------------------------------- #

async def _put_older(client, org_id: str, **values: str) -> None:
    for key, value in values.items():
        r = await client.put(f"/api/orgs/{org_id}/integrations", json={"provider": "stripe", "key": key, "value": value})
        assert r.status_code == 200, r.text


def test_older_keys_go_to_the_slot_their_prefix_names():
    from services.payments.older_keys import sorted_keys
    test_sk, live_sk = "sk_test_" "51Older", "sk_live_" "51Older"
    # A test key typed into the live name (the old form's commonest slip) is a test key.
    out = sorted_keys({"STRIPE_SECRET_KEY": test_sk, "STRIPE_PUBLISHABLE_KEY": "pk_test_" "51Pub"})
    assert out == {"test": {"secret_key": test_sk, "publishable_key": "pk_test_" "51Pub"}, "live": {}}
    out = sorted_keys({"STRIPE_SECRET_KEY": live_sk, "STRIPE_TEST_SECRET_KEY": test_sk})
    assert out["live"] == {"secret_key": live_sk} and out["test"] == {"secret_key": test_sk}
    # Two keys claiming one slot: the one typed into that slot wins.
    out = sorted_keys({"STRIPE_SECRET_KEY": "sk_test_" "51Stray", "STRIPE_TEST_SECRET_KEY": test_sk})
    assert out["test"]["secret_key"] == test_sk
    assert sorted_keys({}) == {"test": {}, "live": {}}


async def test_older_stripe_keys_are_shown_to_admins_with_the_apps_they_serve(people, org_id, gateway):
    r = await people["admin"].get(_base(org_id))
    assert r.json().get("olderStripe") is None, "nothing set: nothing said"
    await _put_older(people["admin"], org_id, STRIPE_TEST_SECRET_KEY=STRIPE_TEST["secret_key"])
    r = await people["admin"].get(_base(org_id))
    older = r.json()["olderStripe"]
    assert older["keys"] == ["STRIPE_TEST_SECRET_KEY"] and older["apps"] == []
    _no_secret_in(r.text, STRIPE_TEST["secret_key"])
    r = await people["member"].get(_base(org_id))
    assert r.status_code == 200 and "olderStripe" not in r.json(), "a member never hears of keys"


async def test_older_stripe_keys_become_a_checked_gateway_and_stay_for_older_apps(people, org_id, gateway):
    await _put_older(people["admin"], org_id, STRIPE_SECRET_KEY=STRIPE_TEST["secret_key"],
                     STRIPE_PUBLISHABLE_KEY=STRIPE_TEST["publishable_key"])
    gateway.answer["/v1/account"] = (200, {"id": "acct_1Old", "country": "US", "default_currency": "usd",
                                           "settings": {"dashboard": {"display_name": "Older Shop"}}})
    r = await people["member"].post(f"{_base(org_id)}/from-older-keys")
    assert r.status_code == 403, "only an admin moves keys"
    r = await people["admin"].post(f"{_base(org_id)}/from-older-keys")
    assert r.status_code == 201, r.text
    body = r.json()
    _no_secret_in(r.text, STRIPE_TEST["secret_key"])
    assert body["provider"] == "stripe" and body["status"] == "test_only" and body["isDefault"] is True
    assert body["modes"]["test"]["set"] and not body["modes"]["live"]["set"], "a test key typed as live is filed as test"
    assert any("/v1/account" in str(q.url) for q in gateway.requests), "checked with Stripe like any gateway"
    # The older values are not taken away: apps built before gateways read them.
    entries = (await people["admin"].get(f"/api/orgs/{org_id}/integrations")).json()
    assert {e["key"] for e in entries if e["provider"] == "stripe" and e["is_set"]} == {"STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY"}


async def test_older_keys_stripe_refuses_make_no_gateway(people, org_id, gateway):
    await _put_older(people["admin"], org_id, STRIPE_TEST_SECRET_KEY=STRIPE_TEST["secret_key"])
    gateway.answer["/v1/account"] = (401, {"error": {"message": "Invalid API Key provided: sk_test_****"}})
    gateway.answer["/v1/balance"] = (401, {"error": {"message": "Invalid API Key provided: sk_test_****"}})
    r = await people["admin"].post(f"{_base(org_id)}/from-older-keys")
    assert r.status_code == 400 and "Invalid API Key" in r.json()["detail"]
    assert (await people["admin"].get(_base(org_id))).json()["gateways"] == []


async def test_without_an_older_secret_key_there_is_nothing_to_move(people, org_id, gateway):
    await _put_older(people["admin"], org_id, STRIPE_TEST_PUBLISHABLE_KEY=STRIPE_TEST["publishable_key"])
    r = await people["admin"].post(f"{_base(org_id)}/from-older-keys")
    assert r.status_code == 400 and "no older Stripe secret key" in r.json()["detail"]


def test_an_app_from_before_gateways_that_takes_stripe_relies_on_the_older_keys(tmp_path):
    from services.payments.older_keys import apps_relying
    def app(name: str, doc: dict) -> tuple[str, str, str]:
        d = tmp_path / name / ".forge" / "blueprint"
        d.mkdir(parents=True)
        (d / "current.json").write_text(json.dumps(doc))
        return (name, name.title(), str(tmp_path / name))
    stripe = {"id": "INT-1", "provider": "stripe", "serves": "take_payment", "status": "ACTIVE"}
    older = app("older", {"integrations": [stripe]})
    chose = app("chose", {"integrations": [stripe], "payments": {"needed": True, "decidedBy": "person", "gateways": []}})
    retired = app("retired", {"integrations": [{**stripe, "status": "DEPRECATED"}]})
    plain = app("plain", {"integrations": []})
    assert apps_relying([older, chose, retired, plain, ("gone", "Gone", str(tmp_path / "nope"))]) == [{"id": "older", "name": "Older"}]
