"""A BIG SHIFT is a change that touches most of the app.

"Make it Dubai centric" is not one edit: the market, the currency (INR -> AED)
in every label, rule and sample row, the merchant allowlist, the wording. Done
by hand it became a five-step plan and the user rebuilt the project from
scratch (UAT SnapIT). Smith recognises the shift, says what it touches, and on
a yes does the part that can be done from chat: the currency swap in what
people READ.

What it does, exactly (:func:`apply_currency`):

* changes DISPLAY TEXT only - requirements, descriptions, labels, copy, rule
  statements, sample-data prose: the code, the symbol, "rupees" -> "dirhams",
  "₹50,000" -> "AED 50,000", "INR (₹)" -> "AED";
* NEVER touches an identifier: no dict key, no field/entity/table/route/column
  name, no id, no workflow variable inside ``{{ }}``, no expression;
* does NOT convert amounts (the exchange rate is the owner's decision);
* leaves a bare currency VALUE alone ("INR" as a stored value, a
  ``currency == 'INR'`` check): records already saved say INR, and changing the
  literal without the rows would make the two disagree. They are COUNTED and
  reported as needing a data migration, never silently desynced;
* is atomic: it works on a copy, validates it, and only then replaces the
  Blueprint; and idempotent.

What it does not do (and :func:`proposal` says so): re-derive page layouts and
the built app from the updated requirements, change an allowlist of shops, or
migrate saved records. Those need the build (Approve and build) or a separate
ask.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

#: market name -> (market label, currency code)
_PLACES: dict[str, tuple[str, str]] = {
    "dubai": ("the UAE (Dubai)", "AED"), "abu dhabi": ("the UAE (Abu Dhabi)", "AED"), "uae": ("the UAE", "AED"),
    "emirates": ("the UAE", "AED"), "emirati": ("the UAE", "AED"), "sharjah": ("the UAE", "AED"),
    "india": ("India", "INR"), "indian": ("India", "INR"), "mumbai": ("India", "INR"), "delhi": ("India", "INR"),
    "ksa": ("Saudi Arabia", "SAR"), "saudi": ("Saudi Arabia", "SAR"), "saudi arabia": ("Saudi Arabia", "SAR"),
    "riyadh": ("Saudi Arabia", "SAR"), "qatar": ("Qatar", "QAR"), "doha": ("Qatar", "QAR"),
    "kuwait": ("Kuwait", "KWD"), "bahrain": ("Bahrain", "BHD"), "oman": ("Oman", "OMR"),
    "uk": ("the UK", "GBP"), "britain": ("the UK", "GBP"), "london": ("the UK", "GBP"),
    "europe": ("Europe", "EUR"), "european": ("Europe", "EUR"), "germany": ("Germany", "EUR"), "france": ("France", "EUR"),
    "usa": ("the US", "USD"), "america": ("the US", "USD"), "american": ("the US", "USD"),
    "japan": ("Japan", "JPY"), "singapore": ("Singapore", "SGD"), "egypt": ("Egypt", "EGP"),
}
#: code -> (symbols, word singular, word plural)
_CURRENCIES: dict[str, tuple[tuple[str, ...], str, str]] = {
    "AED": (("د.إ",), "dirham", "dirhams"), "INR": (("₹", "Rs.", "Rs"), "rupee", "rupees"),
    "SAR": (("ر.س",), "riyal", "riyals"), "QAR": (("ر.ق",), "riyal", "riyals"),
    "KWD": ((), "dinar", "dinars"), "BHD": ((), "dinar", "dinars"), "OMR": ((), "rial", "rials"),
    "GBP": (("£",), "pound", "pounds"), "EUR": (("€",), "euro", "euros"), "USD": (("US$", "$"), "dollar", "dollars"),
    "JPY": (("¥", "円"), "yen", "yen"), "SGD": (("S$",), "dollar", "dollars"), "EGP": (("E£",), "pound", "pounds"),
}
MARKETS = {k: (v[0], v[1], (v[1],)) for k, v in _PLACES.items()}     # kept for callers: place -> (label, code, symbols)
_CODES = {code: syms for code, (syms, _, _) in _CURRENCIES.items()}

_PLACE_RE = "|".join(sorted((re.escape(p) for p in _PLACES), key=len, reverse=True))
_PL = r"(?P<place>" + _PLACE_RE + r")"
_APP = r"(?:it|this|that|this app|this application|the app|the application|the whole app|the whole thing|everything|the product|the platform)"
#: The place must be the OBJECT of a shift phrase about the WHOLE app or its market.
#: A place word merely near "make" / "only" / "based" ("Only show orders from the UK",
#: "Make the Dubai office address required") is an ordinary request, not this.
_SHIFT_PHRASES = tuple(re.compile(x, re.I) for x in (
    rf"\b(?:make|turn|convert|adapt|tailor|localise|localize|shift|move|switch|port|rebuild|redo)\s+{_APP}\s+"
    rf"(?:(?:into|to be|for|to|towards?)\s+)?(?:a\s+|an\s+|the\s+)?{_PL}(?:\s+(?:centric|focused|based|first|oriented|specific|market|style))?\b",
    rf"\b{_PL}\s+(?:centric|focused|oriented)\b",
    rf"\b(?:be|should be|to be|needs to be|has to be)\s+(?:very\s+)?{_PL}\s+(?:based|first|specific)\b",
    rf"^\W*(?:let'?s\s+|please\s+)?go\s+{_PL}(?:\s+first)?\W*$",
    rf"\b(?:localise|localize|adapt|tailor|target|launch|release|roll out)\s+(?:{_APP}\s+)?(?:for|in|to|at)\s+(?:the\s+)?{_PL}(?:\s+market)?\b",
    rf"\bfor the\s+{_PL}\s+market\b",
    rf"\btarget(?:ing)?\s+the\s+{_PL}\s+market\b",
    rf"\b(?:make|turn)\s+{_APP}\s+centric\s+(?:to|on|around)\s+{_PL}\b",
    rf"\b(?:switch|change|move)\s+(?:the\s+)?(?:market|country|region)\s+(?:to|into)\s+{_PL}\b",
    rf"^\W*(?:build|make|do)\s+{_APP}\s+for\s+{_PL}\W*$",
))
#: Only a WHOLE-APP currency phrase: "switch the currency to X", "use X everywhere", "make everything X",
#: "show prices in X", "change everything to X". A bare code beside a number ("change the amount to eur 5")
#: is an ordinary edit. `cur` is a code (AED) or a currency word (dirhams).
_CURRENCY_SHIFT = tuple(re.compile(x, re.I) for x in (
    r"\b(?:change|switch|convert|set|move)\s+(?:the\s+)?(?:app'?s?\s+)?currency(?:\s+in\s+the\s+app)?\s+(?:to|into)\s+(?P<cur>[A-Za-z]{3,10})\b",
    r"\b(?:use|show|display)\s+(?P<cur>[A-Za-z]{3,10})\s+(?:everywhere|throughout|across the app)\b",
    r"\bmake\s+everything\s+(?:in\s+)?(?P<cur>[A-Za-z]{3,10})\b",
    r"\b(?:change|switch|convert)\s+everything\s+(?:to|into)\s+(?P<cur>[A-Za-z]{3,10})\b",
    r"\b(?:show|display)\s+(?:all\s+)?prices\s+in\s+(?P<cur>[A-Za-z]{3,10})\b",
))


def _currency_code(word: str) -> str | None:
    w = word.lower().rstrip("s")
    if word.upper() in _CURRENCIES:
        return word.upper()
    for code, (_syms, one, many) in _CURRENCIES.items():
        if w == one.rstrip("s") or word.lower() == many:
            return code
    return None
_LANGUAGE = re.compile(
    rf"\b(?:translate|switch|convert|rewrite|make)\s+{_APP}\s+(?:to|into|in)\s+"
    r"(?P<lang>arabic|hindi|french|german|spanish|japanese|chinese|portuguese)\b", re.I)
_FILLER = frozenset("please can you could would let's lets now just the a an".split())


def _whole_message(t: str, m: re.Match) -> bool:
    """The shift phrase IS the ask: what is left over is a few filler words, not
    another change ("make it dubai centric and add a refund button" is two asks)."""
    rest = (t[:m.start()] + " " + t[m.end():])
    words = [w for w in re.findall(r"[a-z']+", rest.lower()) if w not in _FILLER]
    return not words


def detect(text: str) -> dict | None:
    """``{kind, market?, currency?, language?, touches: [...]}`` when the WHOLE ask
    is to shift the app (a market, a currency, a language), else None. Anything
    that merely mentions a place or a currency, or that shifts AND asks for
    something else, is an ordinary request and goes through Smith's normal turn."""
    t = " ".join((text or "").replace("-", " ").split())
    for rx in _SHIFT_PHRASES:
        m = rx.search(t)
        if m and _whole_message(t, m):
            name, code = _PLACES[m.group("place").lower()]
            return {"kind": "market", "market": name, "currency": code, "language": None,
                    "touches": ["the market the app is for", f"the currency (what people read becomes {code})",
                                "the list of allowed shops or suppliers", "rules and descriptions that name the old currency",
                                "the sample data"]}
    for rx in _CURRENCY_SHIFT:
        c = rx.search(t)
        if not (c and _whole_message(t, c)):
            continue
        code = _currency_code(c.group("cur"))
        if not code:
            continue
        return {"kind": "currency", "market": None, "currency": code, "language": None,
                "touches": [f"what people read becomes {code}",
                            "rules and descriptions that name the old currency", "the sample data"]}
    lg = _LANGUAGE.search(t)
    if lg and _whole_message(t, lg):
        return {"kind": "language", "market": None, "currency": None, "language": lg.group("lang").lower(),
                "touches": ["the interface language", "every screen's own text", "the sample data"]}
    return None


# --- what is display text, and what is an identifier ------------------------------------------------

#: Keys whose string value is an identifier or a machine word, never prose.
_KEEP_KEYS = frozenset({"id", "key", "slug", "table", "entity", "route", "name", "naturalKey", "natural_key", "field",
                        "column", "fromField", "toField", "variableName", "property", "type", "kind", "status",
                        "actionType", "pattern", "trigger", "page", "workflow", "source", "op", "references",
                        "expression", "condition", "when", "formula", "predicate", "visibleIf", "where", "path",
                        "href", "navigate", "rowHref", "src", "url"})
_IDENT = re.compile(r"[A-Za-z_$][\w$.\-/]*")
_EXPRY = re.compile(r"==|!=|<=|>=|&&|\|\||=>|\bthen\b.*\belse\b|\(.*\)\s*[<>=]")
#: Protected inside prose: a template, and a comparison fragment (`currency == 'INR'`,
#: `price > 10000`) - display text around them is swapped, they are not.
_TEMPLATE = re.compile(r"\{\{.*?\}\}|[\w.]+\s*(?:==|!=|<=|>=|<|>)\s*(?:'[^']*'|\"[^\"]*\"|[\w.]+)|&&|\|\|")


def _words(code: str) -> tuple[str, str]:
    return _CURRENCIES[code][1], _CURRENCIES[code][2]


def _compile(old: str, new: str):
    syms = _CURRENCIES.get(old, ((), "", ""))[0]
    sym_alt = "|".join(re.escape(s) for s in syms)
    code = r"(?<![A-Za-z0-9_])" + re.escape(old) + r"(?![A-Za-z0-9_])"
    pats: list[tuple[re.Pattern, Any]] = []
    if sym_alt:
        pats.append((re.compile(rf"{code}\s*\(\s*(?:{sym_alt})\s*\)"), new))                 # INR (₹)
        pats.append((re.compile(rf"(?:{sym_alt})\s*\(\s*{code}\s*\)"), new))                 # ₹ (INR)
        pats.append((re.compile(rf"(?:{sym_alt})\s*(?=\d)"), f"{new} "))                      # ₹50,000
    pats.append((re.compile(code + r"\s*(?=\d)"), f"{new} "))                                # INR50,000
    if sym_alt:
        pats.append((re.compile(rf"(?<![A-Za-z0-9_])(?:{sym_alt})(?![A-Za-z0-9_])"), new))   # a bare symbol
    pats.append((re.compile(code), new))
    if old in _CURRENCIES and new in _CURRENCIES:
        (os_, op_), (ns, np_) = _words(old), _words(new)
        pats.append((re.compile(rf"(?<![A-Za-z]){op_}(?![A-Za-z])", re.I), lambda m: np_.capitalize() if m.group(0)[0].isupper() else np_))
        pats.append((re.compile(rf"(?<![A-Za-z]){os_}(?![A-Za-z])", re.I), lambda m: ns.capitalize() if m.group(0)[0].isupper() else ns))
    collapse = re.compile(rf"{re.escape(new)}\s*\(\s*{re.escape(new)}\s*\)")
    return pats, collapse, new


def _swap_text(value: str, pats, collapse, new: str) -> str:
    """Substitute outside ``{{ }}`` templates so a variable name is never touched."""
    out, last = [], 0
    for m in _TEMPLATE.finditer(value):
        out.append(_sub_plain(value[last:m.start()], pats, collapse, new))
        out.append(m.group(0))
        last = m.end()
    out.append(_sub_plain(value[last:], pats, collapse, new))
    return "".join(out)


def _sub_plain(text: str, pats, collapse, new: str) -> str:
    for rx, rep in pats:
        text = rx.sub(rep, text)
    return collapse.sub(new, text)


def _is_display(path_last: str, value: str, old_syms: tuple[str, ...], old: str) -> bool:
    if path_last in _KEEP_KEYS:
        return False
    v = value.strip()
    if _IDENT.fullmatch(v):                      # a bare code, a name: a VALUE or an identifier
        return False
    return True


def _walk(node: Any, key: str, fn) -> Any:
    """Rebuild ``node`` with ``fn(key, string)`` applied to string VALUES; dict keys are never touched."""
    if isinstance(node, dict):
        return {k: _walk(v, k, fn) for k, v in node.items()}
    if isinstance(node, list):
        return [_walk(v, key, fn) for v in node]
    if isinstance(node, str):
        return fn(key, node)
    return node


def _section_of(path: str) -> str:
    return path or "document"


def _scan(doc: Any, old: str, new: str, *, collect: dict | None = None, bare: list | None = None) -> Any:
    pats, collapse, newc = _compile(old, new)
    syms = _CURRENCIES.get(old, ((), "", ""))[0]
    top = {"sec": ""}

    def fn(key: str, value: str) -> str:
        if _is_display(key, value, syms, old):
            out = _swap_text(value, pats, collapse, newc)
            if out != value and collect is not None:
                collect[top["sec"]] = collect.get(top["sec"], 0) + 1
            return out
        if bare is not None and re.search(r"(?<![A-Za-z0-9_])" + re.escape(old) + r"(?![A-Za-z0-9_])", value) \
                and key not in ("name", "id", "key", "table", "entity", "route", "field", "column"):
            bare.append(top["sec"])
        return value

    if isinstance(doc, dict) and not _is_flat(doc):
        return {k: _with_section(top, k, lambda v=v, k=k: _walk(v, k, fn)) for k, v in doc.items()}
    return _walk(doc, "", fn)


def _is_flat(doc: dict) -> bool:
    return False


def _with_section(top: dict, name: str, thunk):
    top["sec"] = name
    return thunk()


def current_currency(doc: dict) -> str | None:
    """The code the Blueprint uses most, among the known ones."""
    blob = json.dumps(doc, ensure_ascii=False)
    best, n = None, 0
    for code, (syms, *_rest) in _CURRENCIES.items():
        k = len(re.findall(r"(?<![A-Za-z0-9_])" + re.escape(code) + r"(?![A-Za-z0-9_])", blob))
        k += sum(blob.count(s) for s in syms if s not in ("$", "Rs", "Rs."))
        if k > n:
            best, n = code, k
    return best


def preview_currency(doc: dict, old: str, new: str, *, output_dir: str | Path | None = None) -> dict:
    """What would change, by section, and what would be left alone; changes nothing."""
    hits: dict[str, int] = {}
    bare: list[str] = []
    _scan(doc, old, new, collect=hits, bare=bare)
    seed, seed_bare = 0, 0
    plan = _seed_path(output_dir)
    if plan is not None:
        try:
            sh: dict[str, int] = {}
            sb: list[str] = []
            _scan(json.loads(plan.read_text(encoding="utf-8")), old, new, collect=sh, bare=sb)
            seed, seed_bare = sum(sh.values()), len(sb)
        except (OSError, ValueError):
            pass
    return {"from": old, "to": new, "blueprint": hits, "seed_rows": seed, "total": sum(hits.values()) + seed,
            "kept_values": len(bare) + seed_bare}


def _seed_path(output_dir: str | Path | None) -> Path | None:
    if not output_dir:
        return None
    p = Path(output_dir) / "contracts" / "seed-plan.json"
    return p if p.is_file() else None


def apply_currency(svc: Any, old: str, new: str, *, output_dir: str | Path | None = None) -> dict:
    """Swap ``old`` for ``new`` in what people READ, across the Blueprint and the
    seed plan. Atomic (copy, validate, swap), idempotent, identifiers and stored
    values untouched, amounts not converted."""
    before = json.dumps(svc.doc, sort_keys=True, ensure_ascii=False)
    candidate = _scan(copy.deepcopy(svc.doc), old, new)
    changed = json.dumps(candidate, sort_keys=True, ensure_ascii=False) != before
    bare: list[str] = []
    _scan(candidate, old, new, bare=bare)
    if changed:
        snapshot = copy.deepcopy(svc.doc)
        svc.doc.clear()
        svc.doc.update(candidate)
        try:
            svc.validate()
        except Exception:
            svc.doc.clear()
            svc.doc.update(snapshot)               # an invalid result never stays half-applied
            raise
        svc.save()
    seed = 0
    plan = _seed_path(output_dir)
    if plan is not None:
        try:
            from services.guard_io import dump_like, read_raw, write_atomic
            raw = read_raw(str(plan))
            data = json.loads(raw)
            new_data = _scan(data, old, new)
            if new_data != data:
                seed = 1
                write_atomic(str(plan), dump_like(raw, new_data))
            sb: list[str] = []
            _scan(new_data, old, new, bare=sb)
            bare += sb
        except (OSError, ValueError):
            pass
    return {"applied": changed or bool(seed), "blueprint_changed": changed, "seed_changed": bool(seed),
            "from": old, "to": new, "kept_values": len(bare)}


# --- the offer, and the turn ----------------------------------------------------------------------------

def proposal(shift: dict, preview: dict | None = None) -> str:
    """The offer, in plain words: exactly what will happen now, and what will not."""
    what = {"market": f"moves the app to {shift.get('market')}", "currency": f"changes the currency to {shift.get('currency')}",
            "language": f"changes the app's language to {shift.get('language')}"}[shift["kind"]]
    s = f"This {what}, which touches most of the app: " + "; ".join(shift["touches"]) + "."
    if shift["kind"] == "language":
        return (s + " I have changed nothing, and I cannot switch the whole app's language from chat yet. Tell me which "
                "screens to rewrite, or say \"also in <language>\" to add it as a choice.")
    if not preview or not preview.get("total"):
        return (s + " I have changed nothing: the definition names no currency in what people read that differs from "
                    "the new market's, so there is nothing to swap, and the market itself, the allowed shops and the "
                    "sample data are not something I can switch from chat yet. Say what specific thing should change "
                    "and I will do that.")
    parts = ", ".join(f"{n} in {sec}" for sec, n in sorted(preview["blueprint"].items()))
    s += (f" If you say \"go ahead\" I will now change {preview['from']} to {preview['to']} in what people read: "
          f"{preview['total']} place(s) ({parts}"
          + (f", {preview['seed_rows']} in the sample data" if preview.get("seed_rows") else "") + "). "
          "I will not touch names or identifiers, and I will not convert any amount (the exchange rate is yours to decide).")
    if preview.get("kept_values"):
        s += (f" {preview['kept_values']} stored value(s) or checks say {preview['from']} as plain data; records already "
              f"saved still say {preview['from']}, so those need a data migration that I will not do silently.")
    s += (" Not done by this step: re-deriving the screens from the updated requirements (that needs a rebuild - "
          "Approve and build), and the list of allowed shops.")
    return s


#: What the one pending question is called, so a yes reaches it and nothing else.
VERB = "big_shift"


def _target(shift: dict, old: str) -> str:
    return f"{old}->{shift['currency']}"


def handle(output_dir: str, message: str) -> str | None:
    """Smith's turn for a big shift: returns what to say, or None when the
    message is not about one. Asks once (the confirm mechanism shared with
    field removal); a yes runs the swap."""
    from services.smith import confirm
    from services.blueprint.service import BlueprintService
    pending = confirm.pending_fingerprint(output_dir)
    if pending.startswith(VERB + ":"):
        target = pending.partition(":")[2]
        if confirm.is_yes(message, target) and confirm.granted(output_dir, message, VERB, target):
            old, new = (x.upper() for x in target.split("->", 1))
            try:
                svc = BlueprintService.load(output_dir=output_dir)
                out = apply_currency(svc, old.upper(), new.upper(), output_dir=output_dir)
            except Exception as exc:  # noqa: BLE001
                return f"I could not change {old.upper()} to {new.upper()}: nothing was changed ({exc})."
            if not out["applied"]:
                return f"Nothing in the definition said {old} where people read it, so nothing changed."
            said = (f"Changed {old} to {new} in what people read (the requirements, labels, rules and sample data); "
                    "names, identifiers and amounts are untouched.")
            if out["kept_values"]:
                said += (f" {out['kept_values']} stored value(s) or checks still say {old} because records already saved "
                         "say it too: they need a data migration, which is a separate step.")
            return said + " The built screens carry it after the next build (Approve and build)."
        return None                       # a no / anything else: handled by the confirmation's own clearing
    shift = detect(message)
    if not shift:
        return None
    try:
        svc = BlueprintService.load(output_dir=output_dir)
    except Exception:  # noqa: BLE001 - no definition yet: nothing to shift
        return None
    old = current_currency(svc.doc)
    prev = None
    if shift.get("currency") and old and old != shift["currency"]:
        prev = preview_currency(svc.doc, old, shift["currency"], output_dir=output_dir)
        if prev["total"]:
            confirm.remember(output_dir, confirm.fingerprint(VERB, _target(shift, old)))
    return proposal(shift, prev)


__all__ = ["detect", "current_currency", "preview_currency", "apply_currency", "proposal", "handle", "MARKETS", "VERB"]
