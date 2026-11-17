"""Does this application take money — and how?

Read from what the person asked for and what the definition says, in this
order:

1. **The person's own words.** "No payments", "free to use", "we do not
   charge": nothing is added, whatever else is said. A person who decided in
   the build dialog or told Smith is never overruled (`decidedBy`).
2. **A model**, asked one narrow question with a fixed JSON answer: does the
   application ITSELF charge its users through a payment gateway — and is it
   one-time payments (an order, a booking, a fee, a donation), a subscription
   (a membership, a plan renewed every month or year), or both? The
   difference that matters is the one a keyword list cannot see: an expense
   tracker *records* payments made elsewhere; a gym's member portal *takes*
   them.
3. **What the definition already holds**, as evidence the model's answer is
   checked against: a workflow that opens a checkout is one-time payments,
   whatever the model said; a Subscription or Plan record with a price is a
   subscription. With no model (offline, a test, an outage) these signals and
   the words alone decide, conservatively.

The answer carries a suggested plan list for a subscription (names, prices in
the app's currency, what each includes) — a starting point the person edits in
the build dialog, never charged as it stands without them seeing it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Callable

logger = logging.getLogger(__name__)

ONE_TIME = "one_time"
SUBSCRIPTION = "subscription"

_NO = re.compile(
    r"\b(?:no|without|never|not)\s+(?:any\s+)?(?:online\s+)?(?:payments?|billing|subscriptions?|checkout|charges?|charging)\b"
    r"|\b(?:do(?:es)?\s*n[o']?t|won'?t|will\s+not|doesn'?t)\s+(?:take|charge|accept|need|require|handle|collect)\s+"
    r"(?:any\s+)?(?:payments?|money|fees?|subscriptions?)\b"
    r"|\bfree\s+(?:to\s+use|of\s+charge|for\s+everyone|for\s+all)\b|\b(?:100%|completely|entirely|totally)\s+free\b",
    re.I)
_OFFLINE = re.compile(
    r"\b(?:pay(?:s|ing)?|paid|payments?|charged?)\s+(?:(?:at|in|on|by)\s+(?:the\s+)?(?:front\s+desk|counter|reception|venue|door|"
    r"person|cash|cheque|check|store|shop|site|location|bank\s+transfer)|offline|in\s+cash|outside\s+(?:the\s+)?app)\b", re.I)
#: Someone paying, in any words: beside a "free"/"no payments", it makes the
#: decline a part of the app's ("free to list, students pay per session").
_PAYING = re.compile(r"\b(?:pay(?:s|ing)?|paid|purchas(?:e|es|ing)|buy(?:s|ing)?|charged?|fees?|prices?|priced|tickets?|deposits?)\b", re.I)
_SUBSCRIPTION_WORDS = re.compile(
    r"\b(?:subscri(?:be|bers?|ption|ptions|bing)|membership(?:s)?|monthly\s+(?:plan|fee|membership|subscription)|"
    r"yearly\s+(?:plan|fee)|annual\s+(?:plan|fee|membership)|premium\s+(?:plan|tier|members?|features?)|paid\s+(?:plan|tier)s?|"
    r"pricing\s+(?:plans?|tiers?)|(?:pro|plus|basic|starter)\s+plan|recurring\s+(?:payment|billing|charge)s?|"
    r"billing\s+cycle|auto[-\s]?renew(?:al|s)?|saas)\b", re.I)
_ONE_TIME_WORDS = re.compile(
    r"\b(?:buy|buys|buying|purchas(?:e|es|ing)|checkout|check\s+out\s+and\s+pay|pay\s+(?:for|online|now|at\s+booking)|"
    r"(?:take|accept|collect)s?\s+(?:online\s+)?payments?|online\s+payments?|"
    r"sell(?:s|ing)?\s+(?:products?|items?|tickets?|courses?|goods)|e-?commerce|online\s+(?:store|shop)|storefront|"
    r"add\s+to\s+cart|shopping\s+cart|book(?:ing)?\s+(?:and|&)\s+pay|deposits?|donat(?:e|ions?)|tickets?\s+sales?|"
    r"(?:entry|registration|booking|consultation|course|admission)\s+fees?)\b", re.I)
_SUB_ENTITIES = re.compile(r"^(?:subscriptions?|memberships?|plans?|pricing ?plans?|tiers?|billing ?plans?)$", re.I)
_SALE_ENTITIES = re.compile(r"^(?:orders?|purchases?|carts?|checkouts?|bookings?|tickets?|donations?|invoices?|payments?)$", re.I)
_PRICE_FIELD = re.compile(r"(?:price|amount|fee|cost|total|rate)", re.I)

#: The currency an app's locale suggests, when it has none of its own.
_LOCALE_CURRENCY = {"in": "INR", "ae": "AED", "sa": "SAR", "qa": "QAR", "kw": "KWD", "bh": "BHD", "om": "OMR",
                    "gb": "GBP", "us": "USD", "sg": "SGD", "au": "AUD", "ca": "CAD", "jp": "JPY", "my": "MYR",
                    "de": "EUR", "fr": "EUR", "es": "EUR", "it": "EUR", "nl": "EUR", "ie": "EUR"}


def app_currency(doc: dict) -> str:
    product = doc.get("product") or {}
    cur = str(product.get("currency") or "").strip().upper()
    if re.fullmatch(r"[A-Z]{3}", cur):
        return cur
    loc = str(product.get("locale") or "").lower()
    region = loc.split("-")[1] if "-" in loc else ""
    return _LOCALE_CURRENCY.get(region, "USD")


def _live(rows: Any) -> list[dict]:
    return [r for r in rows or [] if isinstance(r, dict)
            and str(r.get("status") or "").upper() not in ("DEPRECATED", "REMOVED", "SUPERSEDED", "REJECTED")]


def text_of(doc: dict) -> str:
    """What the person asked for and what was worked out from it, as prose."""
    app = doc.get("application") or {}
    parts = [str(app.get("name") or ""), str(app.get("description") or "")]
    parts += [str(r.get("description") or "") for r in _live(doc.get("requirements"))]
    product = doc.get("product") or {}
    parts += [str(o) for o in product.get("objectives") or []]
    parts += [f"{c.get('name', '')}: {c.get('description', '')}" for c in product.get("capabilities") or [] if isinstance(c, dict)]
    parts += [f"{m.get('name', '')}: {m.get('description', '')}" for m in _live(doc.get("modules"))]
    return "\n".join(p for p in parts if p.strip())


def _person_said(doc: dict) -> str:
    app = doc.get("application") or {}
    asked = [str(app.get("description") or "")]
    asked += [str(r.get("description") or "") for r in _live(doc.get("requirements")) if str(r.get("source") or "user") in ("user", "brief", "")]
    return "\n".join(asked)


def signals(doc: dict) -> dict[str, Any]:
    """What the definition itself says about money, without a model."""
    out: dict[str, Any] = {"checkout": [], "sub_entities": [], "sale_entities": [], "sub_words": [], "one_time_words": [],
                           "declined": ""}
    for w in _live(doc.get("workflows")):
        for st in w.get("steps") or []:
            if isinstance(st, dict) and str((st.get("config") or {}).get("actionType") or "") == "create_checkout":
                out["checkout"].append(str(w.get("name") or w.get("id")))
                break
    for e in _live((doc.get("data") or {}).get("entities")):
        name = str(e.get("name") or "")
        priced = any(_PRICE_FIELD.search(str(f.get("name") or "")) for f in e.get("fields") or [] if isinstance(f, dict))
        if _SUB_ENTITIES.match(name.strip()) and priced:
            out["sub_entities"].append(name)
        elif _SALE_ENTITIES.match(name.strip()) and priced:
            out["sale_entities"].append(name)
    text = text_of(doc)
    out["sub_words"] = sorted({m.group(0).lower() for m in _SUBSCRIPTION_WORDS.finditer(text)})[:6]
    out["one_time_words"] = sorted({m.group(0).lower() for m in _ONE_TIME_WORDS.finditer(text)})[:6]
    declined = _NO.search(_person_said(doc))
    out["declined"] = declined.group(0) if declined else ""
    return out


def basis(doc: dict) -> str:
    """A digest of what a decision is read from: it changes when they do."""
    sig = signals(doc)
    payload = json.dumps({"text": text_of(doc), "checkout": sig["checkout"], "entities": sig["sub_entities"] + sig["sale_entities"]},
                         sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


_PROMPT = """You decide whether a business application must TAKE MONEY from its users through a payment gateway (Razorpay, Stripe, PayPal), and how.

Answer "needed": true ONLY when the application itself charges people: they buy something in it, pay a fee, pay a deposit, donate, or pay a recurring subscription/membership to use it or its premium parts.
Answer "needed": false when money is only RECORDED or TRACKED (an expense tracker, an accounting ledger, invoices sent and paid elsewhere, a payroll or budgeting tool, a CRM that notes deal values), when the app is internal to a company, or when the request says it is free.

"models": ["one_time"] for purchases, orders, bookings, fees, tickets, donations; ["subscription"] for memberships, plans, recurring billing, SaaS tiers; both when both happen.
"access": "app" when people must hold an active subscription to use the application at all (a members-only service, a SaaS product); "none" when subscriptions only add perks or nothing is locked.
"plans": when "subscription" is in models, 1 to 3 plans a business like this would sell, priced in {currency} (major units, realistic for the market), each {{"id": "slug", "name": "...", "interval": "month"|"year", "price": number, "features": ["...", "..."]}}; otherwise [].
"reason": ONE short sentence a non-technical owner understands, saying what is paid for ("Members pay a monthly fee to book classes.").

Return ONLY this JSON object, no prose, no code fence:
{{"needed": true|false, "models": [...], "access": "app"|"none", "plans": [...], "reason": "..."}}

THE APPLICATION:
{app}
"""


def _default_provider(prompt: str) -> str:
    from services.llm_client import complete
    return complete(content=prompt, max_tokens=900, temperature=0)


def _parse(text: str) -> dict | None:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _slug(text: str, used: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:30] or "plan"
    if not re.match(r"^[a-z0-9]", base):
        base = "plan-" + base
    slug, n = base, 2
    while slug in used:
        slug, n = f"{base}-{n}", n + 1
    used.add(slug)
    return slug


#: Currencies with no minor unit, and with three (the gateways' own lists).
ZERO_DECIMAL = frozenset({"BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA", "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF"})
THREE_DECIMAL = frozenset({"BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"})


def decimals(currency: str) -> int:
    c = str(currency or "").upper()
    return 0 if c in ZERO_DECIMAL else 3 if c in THREE_DECIMAL else 2


def clean_plans(raw: Any, currency: str, *, limit: int = 3) -> list[dict]:
    """Plans as the Blueprint holds them, from whatever shape was proposed
    (a suggestion keeps three; a person may keep up to eight)."""
    out: list[dict] = []
    used: set[str] = set()
    for p in raw if isinstance(raw, list) else []:
        if not isinstance(p, dict) or not str(p.get("name") or "").strip():
            continue
        prices: dict[str, float] = {}
        if isinstance(p.get("prices"), dict):
            for k, v in p["prices"].items():
                try:
                    if re.fullmatch(r"[A-Z]{3}", str(k)) and float(v) > 0:
                        prices[str(k)] = round(float(v), decimals(str(k)))
                except (TypeError, ValueError):
                    continue
        else:
            try:
                price = float(p.get("price"))
                if price > 0:
                    prices[currency] = round(price, decimals(currency))
            except (TypeError, ValueError):
                pass
        if not prices:
            continue
        interval = str(p.get("interval") or "month").lower()
        interval = {"monthly": "month", "yearly": "year", "annual": "year", "weekly": "week", "daily": "day"}.get(interval, interval)
        if interval not in ("day", "week", "month", "year"):
            interval = "month"
        out.append({
            "id": _slug(p.get("id") or p.get("name"), used), "name": str(p.get("name")).strip()[:60],
            "description": str(p.get("description") or "")[:300], "interval": interval,
            "intervalCount": max(1, min(12, int(p.get("intervalCount") or 1))) if str(p.get("intervalCount") or "1").isdigit() else 1,
            "prices": prices, "trialDays": max(0, min(365, int(p.get("trialDays") or 0))) if str(p.get("trialDays") or "0").isdigit() else 0,
            "features": [str(f)[:120] for f in (p.get("features") or []) if str(f).strip()][:20],
            "highlighted": bool(p.get("highlighted")),
        })
        if len(out) == limit:
            break
    if out and not any(p["highlighted"] for p in out):
        out[min(1, len(out) - 1)]["highlighted"] = True
    return out


# --------------------------------------------------------------------------- #
# Plans in a person's own words
# --------------------------------------------------------------------------- #

_CUR = {"₹": "INR", "rs": "INR", "rs.": "INR", "rupee": "INR", "rupees": "INR", "inr": "INR", "$": "USD", "usd": "USD", "dollar": "USD",
        "dollars": "USD", "€": "EUR", "eur": "EUR", "euro": "EUR", "euros": "EUR", "£": "GBP", "gbp": "GBP", "pound": "GBP", "pounds": "GBP",
        "aed": "AED", "dirham": "AED", "dirhams": "AED", "sar": "SAR", "riyal": "SAR", "riyals": "SAR"}
_PRE = r"(?P<pre>₹|\$|€|£|rs\.?|inr|usd|eur|gbp|aed|sar)"
_POST = r"(?P<post>rupees?|inr|dollars?|usd|euros?|eur|pounds?|gbp|aed|dirhams?|sar|riyals?)"
#: 1999, 1,999, 1,99,999 (Indian grouping), 9.99 — a comma followed by three digits groups, by one or two is a decimal.
_AMT = r"(?P<amt>\d{1,3}(?:,\d{2,3})*,\d{3}(?:\.\d{1,2})?|\d+(?:[.,]\d{1,2})?)(?!\d|,\d)"
_UNIT = {"month": "month", "mo": "month", "monthly": "month", "year": "year", "yr": "year", "yearly": "year", "annual": "year",
         "annually": "year", "week": "week", "weekly": "week"}
#: "₹999 a month", "$9/mo", "Rs 1,999 per month", "999 rupees every year".
_PRICE_THEN_PER = re.compile(rf"(?:{_PRE}\s*)?{_AMT}\s*(?:{_POST})?\s*(?:a|per|/|every)\s*(?P<per>month|mo|year|yr|week)\b", re.I)
#: "a yearly membership of Rs 9999", "annual plan at $99", "monthly: ₹999".
_PER_THEN_PRICE = re.compile(rf"\b(?P<per>monthly|yearly|annual|annually|weekly)\b[^.;\n₹$€£\d]{{0,30}}?{_PRE}\s*{_AMT}(?!\s*(?:a|per|/|every)\s*(?:month|mo|year|yr|week))", re.I)
_NAMED = (re.compile(r"\b([A-Za-z][\w-]*)\s+(?:plan|tier|membership|package)\b[^.;\n]{0,12}$", re.I),
          re.compile(r"\b([A-Z][\w-]*)\s*(?:at|for|:|-|–|—|=|costs?|is)\s*$"))
_NOT_A_NAME = {"a", "an", "the", "one", "monthly", "yearly", "annual", "weekly", "membership", "plan", "of", "at", "for", "and", "or",
               "members", "member", "buy", "pay", "costs", "cost", "price", "subscription", "with", "is", "are", "be"}


def plans_in_words(text: str, currency: str) -> list[dict]:
    """The plans a person priced in their own words, in the order they said them:
    "Basic at Rs 999 a month", "Unlimited at ₹1,999 per month", "a yearly membership
    of Rs 9999". What has no recurring price (a one-off fee) is not a plan."""
    found: list[tuple[int, int, re.Match, str]] = []
    for m in _PRICE_THEN_PER.finditer(text or ""):
        found.append((m.start(), m.end(), m, _UNIT[m.group("per").lower()]))
    for m in _PER_THEN_PRICE.finditer(text or ""):
        if not any(s <= m.start("amt") < e for s, e, _, _ in found):
            found.append((m.start(), m.end(), m, _UNIT[m.group("per").lower()]))
    out: list[dict] = []
    names: set[str] = set()
    for start, _end, m, per in sorted(found, key=lambda f: f[0]):
        word = (m.group("pre") or m.groupdict().get("post") or "").lower()
        cur = _CUR.get(word) or _CUR.get(word.rstrip("s")) or currency
        raw = m.group("amt")
        amount = float(raw.replace(",", "")) if re.search(r",\d{3}(?:\.|$)", raw) else float(raw.replace(",", "."))
        before = text[max(0, start - 48):start]
        name = ""
        for pat in _NAMED:
            hit = None
            for hit in pat.finditer(before):
                pass
            if hit and hit.group(1).lower() not in _NOT_A_NAME:
                name = hit.group(1)
                break
        generic = not name
        name = name[:1].upper() + name[1:] if name else {"month": "Monthly", "year": "Yearly", "week": "Weekly"}[per]
        # THE SAME PRICE ON THE SAME CYCLE IS THE SAME PLAN, said twice ("a
        # monthly membership of Rs 999 … Basic at Rs 999 a month"): kept once,
        # by the name that says which it is.
        same = next((p for p in out if p["interval"] == per and p["prices"] == {cur: amount}), None)
        if same is not None:
            if not generic and same.get("_generic"):
                names.discard(same["name"].lower())
                same["name"], same["_generic"] = name, False
                names.add(name.lower())
            continue
        if name.lower() in names:
            name = f"{name} ({per}ly)" if f"{name} ({per}ly)".lower() not in names else f"{name} {len(out) + 1}"
        names.add(name.lower())
        out.append({"name": name, "interval": per, "prices": {cur: amount}, "features": [], "_generic": generic})
    return [{k: v for k, v in p.items() if k != "_generic"} for p in out]


_PRICED = re.compile(rf"(?:{_PRE}\s*{_AMT}|{_AMT.replace('?P<amt>', '?P<amt2>')}\s*{_POST})", re.I)
#: What a person says just before a price they charge once: "pay Rs 400", "a class pass for ₹300", "a ₹50 fee".
_BUYING = re.compile(r"\b(?:pay|pays|paying|paid|buy|buys|buying|purchase|purchases|fee|fees|charge|charged|charges|ticket|tickets|"
                     r"pass|passes|costs?|price[ds]?|deposit|book(?:ing)?s? for)\b[^.;\n]{0,24}$", re.I)

#: ... or just after it: "a ₹50 late fee", "₹300 per class", "$25 each".
_CHARGED_AS = re.compile(r"\s*(?:[a-z-]+\s+)?(?:fee|fees|charge|deposit|ticket|pass|each|per\s+(?:class|session|ticket|visit|booking|order|item|"
                         r"person|night|seat|lesson|hour))\b", re.I)


def one_off_prices(text: str) -> list[str]:
    """Prices charged once, in the person's words — a currency-marked amount after
    a word of buying, that is not a plan's recurring price ("pay Rs 400 for a
    drop-in class"). A salary or a budget is not one."""
    plans = [(m.start(), m.end()) for m in _PRICE_THEN_PER.finditer(text or "")] + \
            [(m.start(), m.end()) for m in _PER_THEN_PRICE.finditer(text or "")]
    out = []
    for m in _PRICED.finditer(text or ""):
        if any(s <= m.start() < e for s, e in plans):
            continue
        if _BUYING.search(text[max(0, m.start() - 48):m.start()]) or _CHARGED_AS.match(text[m.end():m.end() + 32]):
            out.append(m.group(0).strip())
    return out


def _from_signals(sig: dict) -> dict:
    """Without a model: only what the definition and the words make plain."""
    models = []
    if sig["checkout"] or (sig["sale_entities"] and sig["one_time_words"]):
        models.append(ONE_TIME)
    said_sub = " ".join(sig["sub_words"])
    if sig["sub_entities"] or ("subscri" in said_sub or "membership" in said_sub):
        models.append(SUBSCRIPTION)
    if not models and sig["one_time_words"]:
        models.append(ONE_TIME)
    if not models:
        return {"needed": False, "models": [], "reason": "Nothing in the request says the app charges its users."}
    what = " and ".join({"one_time": "one-time payments", "subscription": "subscriptions"}[m] for m in models)
    said = (sig["sub_words"] + sig["one_time_words"])[:2]
    return {"needed": True, "models": models,
            "reason": f"The request mentions {', '.join(repr(w) for w in said)}: the app takes {what}." if said
                      else f"The app's processes take {what}."}


def decide(doc: dict, *, provider: Callable[[str], str] | None = None) -> dict[str, Any]:
    """`{needed, models, reason, plans, access, by}` — `by` is "words",
    "model" or "signals". Never raises; never calls a model when the person
    said there are no payments."""
    sig = signals(doc)
    currency = app_currency(doc)
    if sig["declined"]:
        # "NO PAYMENTS" DECIDES ONLY WHEN NOTHING ELSE TAKES MONEY. "Free to use
        # for browsing; members pay ₹999 a month" and "staff have no
        # subscription" decline a part, not the app: with a checkout, a priced
        # record, a price, or money words outside the declining phrase, the
        # whole request is read (the model is told to say "free" where it is).
        # Money paid OUTSIDE the app ("members pay at the front desk", "paid
        # offline") is no money the app takes.
        rest = _OFFLINE.sub(" ", _NO.sub(" ", text_of(doc)))
        money = (sig["checkout"] or sig["sub_entities"] or sig["sale_entities"] or plans_in_words(rest, currency)
                 or one_off_prices(rest) or _SUBSCRIPTION_WORDS.search(rest) or _ONE_TIME_WORDS.search(rest)
                 or _PAYING.search(rest))
        if not money:
            return {"needed": False, "models": [], "plans": [], "access": "none", "by": "words",
                    "reason": f"You said “{sig['declined']}”, so the app takes no payments."}
    text = text_of(doc).strip()
    if not text:
        return {"needed": False, "models": [], "plans": [], "access": "none", "by": "signals",
                "reason": "There is no description yet to decide from."}
    answer: dict | None = None
    try:
        answer = _parse((provider or _default_provider)(_PROMPT.format(currency=currency, app=text[:8000])))
    except Exception:  # noqa: BLE001 — no model is a decision from the signals, not a failure
        logger.warning("[payments] the need could not be asked of a model", exc_info=True)
    if answer is None:
        out = _from_signals(sig)
        # The plans the person priced are theirs whether or not a model answered,
        # and a price "a month" is a subscription whatever it was called.
        priced = clean_plans(plans_in_words(text, currency), currency)
        once = one_off_prices(text)
        if (priced and SUBSCRIPTION not in out.get("models", [])) or (once and ONE_TIME not in out.get("models", [])):
            models = [m for m in (ONE_TIME, SUBSCRIPTION) if m in out.get("models", [])
                      or (m == SUBSCRIPTION and priced) or (m == ONE_TIME and once)]
            what = " and ".join({"one_time": "one-time payments", "subscription": "subscriptions"}[m] for m in models)
            named = [f"plans ({', '.join(p['name'] for p in priced)})"] if priced else []
            named += [f"a one-off {once[0]}"] if once else []
            out = {"needed": True, "models": models, "reason": f"The request prices {' and '.join(named)}: the app takes {what}."}
        out.update(by="signals", plans=priced if SUBSCRIPTION in out["models"] else [], access="none")
        return out
    needed = bool(answer.get("needed"))
    models = [m for m in (answer.get("models") or []) if m in (ONE_TIME, SUBSCRIPTION)] if needed else []
    # THE DEFINITION OUTRANKS THE MODEL where it is plain: a checkout step
    # takes money whatever was said about it.
    if sig["checkout"] and ONE_TIME not in models:
        models.append(ONE_TIME)
        needed = True
    if sig["sub_entities"] and needed and SUBSCRIPTION not in models:
        models.append(SUBSCRIPTION)
    if needed and not models:
        models = [ONE_TIME]
    plans = clean_plans(answer.get("plans"), currency) if SUBSCRIPTION in models else []
    if SUBSCRIPTION in models and not plans:
        plans = clean_plans([{"name": "Monthly", "interval": "month", "price": _default_price(currency),
                              "features": ["Everything in the app"]}], currency)
    reason = re.sub(r"\s+", " ", str(answer.get("reason") or "")).strip()[:300]
    if not reason:
        reason = "The app takes payments." if needed else "The app does not charge its users."
    access = "app" if str(answer.get("access") or "") == "app" and SUBSCRIPTION in models else "none"
    return {"needed": needed, "models": models if needed else [], "reason": reason, "plans": plans,
            "access": access, "by": "model"}


def _default_price(currency: str) -> float:
    return {"INR": 499, "AED": 39, "SAR": 39, "USD": 9, "EUR": 9, "GBP": 8, "JPY": 1200}.get(currency, 9)


__all__ = ["ONE_TIME", "SUBSCRIPTION", "app_currency", "basis", "clean_plans", "decide", "one_off_prices", "plans_in_words", "signals", "text_of"]
