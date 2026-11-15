"""The payment gateways Forge can build into an application, what each one
needs, and how a set of keys is checked against it.

Three providers, chosen for who our owners take money from: **Razorpay**
(India: UPI, cards, netbanking, wallets, e-mandates for subscriptions),
**Stripe** (cards and wallets in most of the world, including the Gulf), and
**PayPal** (buyers who pay with a PayPal balance, worldwide). A fourth is one
entry here and one adapter in the app's runtime (`templates/runtime/payments`).

A KEY IS CHECKED THE MOMENT IT IS SAVED, with one read-only call that costs
nothing and changes nothing at the gateway: Stripe's account, Razorpay's
order list (one row), PayPal's OAuth token. The answer says who the keys
belong to when the gateway tells us, whether they are test or live, and in
words exactly what is wrong when they are not right. A key in the wrong slot
(live keys saved as test) is refused before any call: its prefix says so.

`FORGE_PAYMENTS_EMULATOR` points every call at a local emulator (tests and the
end-to-end check); unset, the gateways' own addresses are used.
"""
from __future__ import annotations

import base64
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TEST = "test"
LIVE = "live"
MODES = (TEST, LIVE)
COVERAGES = ("domestic", "international", "both")
TIMEOUT_S = 12.0


@dataclass(frozen=True)
class KeyField:
    key: str
    label: str
    secret: bool
    required: bool = True
    #: What a value for each mode starts with; None: anything.
    prefix: dict[str, tuple[str, ...]] | None = None
    help: str = ""


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    tagline: str
    coverage: str
    home_country: str | None
    #: The currencies the gateway settles in that a Forge app may price in.
    currencies: tuple[str, ...]
    default_currencies: tuple[str, ...]
    fields: tuple[KeyField, ...]
    #: What the gateway calls its test mode.
    test_name: str
    keys_url: dict[str, str] = field(default_factory=dict)
    #: "auto": Forge registers the app's webhook at publish; "manual": the
    #: owner pastes the address once (Forge shows it, with the secret).
    webhooks: str = "auto"
    payment_methods: str = ""


# Currencies each gateway can charge in, for an app's own currency. Stripe's
# list is long; these are the ones Forge apps are priced in (product.currency).
_COMMON = ("USD", "EUR", "GBP", "INR", "AED", "SAR", "QAR", "KWD", "BHD", "OMR", "SGD", "AUD", "CAD", "JPY",
           "CHF", "NZD", "HKD", "MYR", "ZAR", "SEK", "NOK", "DKK", "PLN", "MXN", "BRL", "THB", "PHP", "IDR")

PROVIDERS: dict[str, Provider] = {
    "razorpay": Provider(
        id="razorpay", name="Razorpay",
        tagline="India: UPI, cards, netbanking and wallets, with automatic recurring payments for subscriptions.",
        coverage="domestic", home_country="IN",
        currencies=("INR", "USD", "EUR", "GBP", "AED", "SAR", "SGD", "AUD", "CAD"),
        default_currencies=("INR",),
        fields=(
            KeyField("key_id", "Key ID", secret=False, prefix={TEST: ("rzp_test_",), LIVE: ("rzp_live_",)},
                     help="Dashboard → Account & Settings → API Keys. Starts rzp_test_ or rzp_live_."),
            KeyField("key_secret", "Key secret", secret=True,
                     help="Shown once, when the key is generated."),
        ),
        test_name="Test mode",
        keys_url={TEST: "https://dashboard.razorpay.com/app/website-app-settings/api-keys",
                  LIVE: "https://dashboard.razorpay.com/app/website-app-settings/api-keys"},
        webhooks="manual",
        payment_methods="UPI, cards, netbanking, wallets, EMI",
    ),
    "stripe": Provider(
        id="stripe", name="Stripe",
        tagline="Cards, Apple Pay and Google Pay in most countries, in your customers' currencies.",
        coverage="international", home_country=None,
        currencies=_COMMON,
        default_currencies=("USD", "EUR", "GBP", "AED"),
        fields=(
            KeyField("secret_key", "Secret key", secret=True,
                     prefix={TEST: ("sk_test_", "rk_test_"), LIVE: ("sk_live_", "rk_live_")},
                     help="Developers → API keys. Starts sk_test_ or sk_live_ (a restricted rk_ key works too)."),
            KeyField("publishable_key", "Publishable key", secret=False, required=False,
                     prefix={TEST: ("pk_test_",), LIVE: ("pk_live_",)},
                     help="Optional. Starts pk_test_ or pk_live_."),
        ),
        test_name="Test mode",
        keys_url={TEST: "https://dashboard.stripe.com/test/apikeys", LIVE: "https://dashboard.stripe.com/apikeys"},
        webhooks="auto",
        payment_methods="Cards, Apple Pay, Google Pay, Link",
    ),
    "paypal": Provider(
        id="paypal", name="PayPal",
        tagline="Buyers who pay with their PayPal balance or a card through PayPal, worldwide.",
        coverage="international", home_country=None,
        currencies=("USD", "EUR", "GBP", "AUD", "CAD", "JPY", "CHF", "SGD", "HKD", "NZD", "SEK", "NOK", "DKK",
                    "PLN", "MXN", "BRL", "THB", "PHP", "MYR", "ILS", "CZK", "HUF", "TWD"),
        default_currencies=("USD", "EUR", "GBP"),
        fields=(
            KeyField("client_id", "Client ID", secret=False,
                     help="developer.paypal.com → Apps & Credentials, under Sandbox or Live."),
            KeyField("client_secret", "Secret", secret=True),
        ),
        test_name="Sandbox",
        keys_url={TEST: "https://developer.paypal.com/dashboard/applications/sandbox",
                  LIVE: "https://developer.paypal.com/dashboard/applications/live"},
        webhooks="auto",
        payment_methods="PayPal balance, cards via PayPal, Pay Later",
    ),
}

#: The order they are offered in.
ORDER = ("razorpay", "stripe", "paypal")


class KeyProblem(ValueError):
    """Keys that cannot be right whatever the gateway says (missing, a live
    key in the test slot). The message is the person's to read."""


def provider(pid: str) -> Provider:
    p = PROVIDERS.get(str(pid or "").lower())
    if p is None:
        raise KeyProblem(f"“{pid}” is not a gateway Forge can build in. Choose Razorpay, Stripe or PayPal.")
    return p


def catalog() -> list[dict[str, Any]]:
    """What the settings page draws: each gateway, its fields, its links."""
    out = []
    for pid in ORDER:
        p = PROVIDERS[pid]
        out.append({
            "id": p.id, "name": p.name, "tagline": p.tagline, "coverage": p.coverage, "homeCountry": p.home_country,
            "currencies": list(p.currencies), "defaultCurrencies": list(p.default_currencies),
            "testName": p.test_name, "keysUrl": dict(p.keys_url), "webhooks": p.webhooks,
            "paymentMethods": p.payment_methods,
            "fields": [{"key": f.key, "label": f.label, "secret": f.secret, "required": f.required,
                        "prefix": {m: list(v) for m, v in (f.prefix or {}).items()}, "help": f.help} for f in p.fields],
        })
    return out


def clean_keys(pid: str, mode: str, keys: dict[str, Any] | None) -> dict[str, str]:
    """The keys for one mode, trimmed, checked for shape. Raises KeyProblem
    with the sentence to show. An empty dict means the mode is not set."""
    p = provider(pid)
    if mode not in MODES:
        raise KeyProblem("Keys are test keys or live keys.")
    raw = {str(k): str(v or "").strip() for k, v in (keys or {}).items() if k in {f.key for f in p.fields}}
    if not any(raw.values()):
        return {}
    out: dict[str, str] = {}
    mode_word = p.test_name.lower() if mode == TEST else "live"
    for f in p.fields:
        v = raw.get(f.key, "")
        if not v:
            if f.required:
                raise KeyProblem(f"{p.name} {mode_word}: add the {f.label.lower()}.")
            continue
        if re.search(r"\s", v) or len(v) > 300:
            raise KeyProblem(f"{p.name} {mode_word}: the {f.label.lower()} has spaces or is far too long — "
                             "copy it again from the dashboard.")
        if f.prefix:
            other = LIVE if mode == TEST else TEST
            if v.startswith(f.prefix.get(other, ())):
                raise KeyProblem(f"That {f.label.lower()} is a {'live' if other == LIVE else 'test'} key, "
                                 f"and this is the {mode_word} slot. "
                                 + ("Live keys go under Live." if other == LIVE else f"{p.test_name} keys go under {p.test_name}."))
            if not v.startswith(f.prefix.get(mode, ())):
                want = " or ".join(f.prefix.get(mode, ()))
                raise KeyProblem(f"{p.name} {mode_word}: the {f.label.lower()} should start with {want}.")
        out[f.key] = v
    return out


def mask(value: str) -> str:
    """What the page shows of a stored key: its kind and last four."""
    v = str(value or "")
    if len(v) <= 8:
        return "••••"
    head = re.match(r"^([a-z]{2,4}_(?:test|live)_)", v)
    return f"{head.group(1) if head else ''}••••{v[-4:]}"


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #

def _base(pid: str, mode: str) -> str:
    emu = (os.environ.get("FORGE_PAYMENTS_EMULATOR") or "").rstrip("/")
    if emu:
        return f"{emu}/{pid}" + ("/sandbox" if pid == "paypal" and mode == TEST else "")
    if pid == "stripe":
        return "https://api.stripe.com"
    if pid == "razorpay":
        return "https://api.razorpay.com"
    return "https://api-m.sandbox.paypal.com" if mode == TEST else "https://api-m.paypal.com"


def _client() -> httpx.AsyncClient:
    """One client per check. Replaced in tests with a mock transport."""
    return httpx.AsyncClient(timeout=TIMEOUT_S)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


async def verify(pid: str, mode: str, keys: dict[str, str]) -> dict[str, Any]:
    """Ask the gateway whether these keys work. Never raises.

    ``{ok, reachable, account, accountId, country, currency, checkedAt, error}``
    — `ok` False with `reachable` True: the gateway refused them (say so, do
    not save); `reachable` False: we could not ask (save, say it is unchecked).
    """
    p = provider(pid)
    out: dict[str, Any] = {"ok": False, "reachable": True, "mode": mode, "checkedAt": _now()}
    try:
        async with _client() as http:
            if pid == "stripe":
                out.update(await _verify_stripe(http, mode, keys))
            elif pid == "razorpay":
                out.update(await _verify_razorpay(http, mode, keys))
            else:
                out.update(await _verify_paypal(http, mode, keys))
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        logger.info("[payments] %s %s unreachable: %s", pid, mode, type(exc).__name__)
        out.update(ok=False, reachable=False,
                   error=f"Forge could not reach {p.name} to check these keys ({type(exc).__name__}). "
                         "They are saved; check them again in a moment.")
    except Exception as exc:  # noqa: BLE001 — a check that broke is said, never a 500
        logger.exception("[payments] verifying %s %s failed", pid, mode)
        out.update(ok=False, reachable=False, error=f"The check could not finish: {type(exc).__name__}.")
    return out


def _refused(name: str, status: int, said: str) -> dict[str, Any]:
    if status in (401, 403):
        said = said.strip().rstrip(".")
        why = f"{name} refused these keys: {said}." if said else f"{name} refused these keys."
        return {"ok": False, "reachable": True, "error": why + " Copy them again from the dashboard."}
    if status >= 500:
        return {"ok": False, "reachable": False,
                "error": f"{name} answered with an error of its own ({status}). The keys are saved; check them again later."}
    return {"ok": False, "reachable": True, "error": f"{name} answered {status}: {said or 'no reason given'}."}


def _message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return ""
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err.get("description") or err.get("code") or "")[:240]
        return str(body.get("error_description") or body.get("message") or err or "")[:240]
    return ""


async def _verify_stripe(http: httpx.AsyncClient, mode: str, keys: dict[str, str]) -> dict[str, Any]:
    base = _base("stripe", mode)
    auth = {"Authorization": f"Bearer {keys['secret_key']}"}
    resp = await http.get(f"{base}/v1/account", headers=auth)
    if resp.status_code == 403 and keys["secret_key"].startswith("rk_"):
        # A restricted key without "read account": the balance read still proves it.
        resp2 = await http.get(f"{base}/v1/balance", headers=auth)
        if resp2.status_code == 200:
            live = bool(resp2.json().get("livemode"))
            return _mode_matches("Stripe", mode, live) or {"ok": True, "account": "", "accountId": ""}
        return _refused("Stripe", resp2.status_code, _message(resp2))
    if resp.status_code != 200:
        return _refused("Stripe", resp.status_code, _message(resp))
    acct = resp.json()
    name = ((acct.get("settings") or {}).get("dashboard") or {}).get("display_name") \
        or (acct.get("business_profile") or {}).get("name") or acct.get("email") or ""
    return {"ok": True, "account": str(name or ""), "accountId": str(acct.get("id") or ""),
            "country": str(acct.get("country") or "").upper() or None,
            "currency": str(acct.get("default_currency") or "").upper() or None}


async def _verify_razorpay(http: httpx.AsyncClient, mode: str, keys: dict[str, str]) -> dict[str, Any]:
    base = _base("razorpay", mode)
    resp = await http.get(f"{base}/v1/orders", params={"count": 1},
                          headers={"Authorization": _basic(keys["key_id"], keys["key_secret"])})
    if resp.status_code != 200:
        return _refused("Razorpay", resp.status_code, _message(resp))
    # The key id is not an account id, and a check never records a key.
    return {"ok": True, "account": "", "accountId": "", "country": "IN", "currency": "INR"}


async def _verify_paypal(http: httpx.AsyncClient, mode: str, keys: dict[str, str]) -> dict[str, Any]:
    base = _base("paypal", mode)
    resp = await http.post(f"{base}/v1/oauth2/token", data={"grant_type": "client_credentials"},
                           headers={"Authorization": _basic(keys["client_id"], keys["client_secret"]),
                                    "Accept": "application/json"})
    if resp.status_code != 200:
        said = _message(resp)
        if resp.status_code == 401 and mode == TEST:
            said = (said + " — if these are Live credentials, save them under Live.").strip(" —")
        elif resp.status_code == 401:
            said = (said + " — if these are Sandbox credentials, save them under Sandbox.").strip(" —")
        return _refused("PayPal", resp.status_code, said)
    body = resp.json()
    return {"ok": True, "account": "", "accountId": str(body.get("app_id") or "")}


def _mode_matches(name: str, mode: str, live: bool) -> dict[str, Any] | None:
    if (mode == LIVE) != live:
        return {"ok": False, "reachable": True,
                "error": f"{name} says these are {'live' if live else 'test'} keys; this is the {mode} slot."}
    return None


__all__ = ["COVERAGES", "KeyField", "KeyProblem", "LIVE", "MODES", "ORDER", "PROVIDERS", "Provider", "TEST",
           "catalog", "clean_keys", "mask", "provider", "verify"]
