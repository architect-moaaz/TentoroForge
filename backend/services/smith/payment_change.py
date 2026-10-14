"""Refunds and the currency are Smith's.

"Refund order 1234": the application's refund process runs on a copy as
the administrator and says what it did; when there is none, Smith says so
and offers to declare one. "Prices are in dirhams": `product.currency`,
re-projected.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from services.llm_client import tell

logger = logging.getLogger(__name__)

VERBS = ("refund", "set_currency")
_CODE = re.compile(r"\b([A-Z]{3})\b")
_NAMES = {"dirham": "AED", "dirhams": "AED", "pound": "GBP", "pounds": "GBP", "sterling": "GBP", "dollar": "USD", "dollars": "USD",
          "euro": "EUR", "euros": "EUR", "rupee": "INR", "rupees": "INR", "riyal": "SAR", "riyals": "SAR", "yen": "JPY",
          "rand": "ZAR", "naira": "NGN", "shilling": "KES", "shillings": "KES", "peso": "MXN", "pesos": "MXN", "real": "BRL",
          "ringgit": "MYR", "rupiah": "IDR", "baht": "THB", "won": "KRW", "yuan": "CNY", "franc": "CHF", "krona": "SEK",
          "dinar": "KWD", "taka": "BDT"}


def _envelope(applied: bool, *, reason: str = "", diff: str = "", paths: list[str] | None = None,
              options: list[str] | None = None, **more: Any) -> dict:
    return {"applied": applied, "reason": reason, "diff_summary": diff,
            "edited_paths": list(paths or []), "options": list(options or []), **more}


def set_currency(svc: Any, output_dir: str, *, change: str = "", reasoning: Any = None, **_: Any) -> dict:
    text = (change or "").strip()
    code = next((m.group(1) for m in _CODE.finditer(text)), None)
    if not code:
        code = next((v for k, v in _NAMES.items() if re.search(rf"\b{k}\b", text.lower())), None)
    if not code:
        return _envelope(False, reason=f"I could not read a currency from {text!r}. Say it as a code (AED, GBP) or a name (dirhams, pounds).",
                         options=["AED", "USD", "GBP", "EUR"])
    before = svc.snapshot()
    product = svc.doc.setdefault("product", {})
    product["currency"] = code
    svc.commit(user_request=text, smith_interpretation=f"money in {code}", before=before, affected=[])
    paths: list[str] = []
    app_root = Path(output_dir) / "app"
    if app_root.is_dir():
        from services.blueprint.projection import project_money
        paths = list(project_money(svc.doc, app_root).get("files") or [])
    tell(reasoning, f"Money is in {code} now.", "step")
    return _envelope(True, diff=f"Money is kept and shown in {code} now (major units). Prices already entered are not converted.", paths=paths)


def refund(svc: Any, output_dir: str, *, change: str = "", reasoning: Any = None, **_: Any) -> dict:
    flows = [w for w in svc.doc.get("workflows") or [] if isinstance(w, dict)
             and str(w.get("status") or "").upper() not in ("DEPRECATED", "REMOVED")
             and any(isinstance(s, dict) and str((s.get("config") or {}).get("actionType") or "") == "refund_payment"
                     for s in w.get("steps") or [])]
    if not flows:
        return _envelope(False, reason="This application has no refund process yet. Say \"add a refund process for orders\" and I will "
                                       "declare one that refunds a paid order through the payment service.",
                         options=["Add a refund process for orders"])
    from services.smith import trials
    wf = flows[0]
    m = re.search(r"\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[A-Za-z0-9-]{4,})\s*$", change or "")
    ref = m.group(1) if m else ""
    inputs = {str(i.get("name")): ref for i in wf.get("inputs") or [] if isinstance(i, dict) and i.get("name")} if ref else {}
    bench = trials.Bench(output_dir)
    try:
        said = trials.run("try_workflow", {"workflow": str(wf.get("id")), "input": inputs, "as": ""}, bench=bench, doc=svc.doc)
    finally:
        try:
            bench.close()
        except Exception:  # noqa: BLE001
            pass
    ok = not trials.failed(said)
    return _envelope(True, diff=(f"Ran {wf.get('name')} on a copy" + (f" for {ref}" if ref else "") + ": "
                                 + ("it went through. On the live application the same button does this for real." if ok
                                    else f"it did not go through —\n{said[:600]}")))


def run(output_dir: str, verb: str, *, change: str = "", reasoning: Any = None) -> dict:
    from services.blueprint.service import BlueprintService
    if verb not in VERBS:
        return _envelope(False, reason=f"not a payment verb: {verb}")
    try:
        svc = BlueprintService.load(output_dir=output_dir)
    except FileNotFoundError:
        return _envelope(False, reason="this project has no Blueprint yet.")
    fn = {"refund": refund, "set_currency": set_currency}[verb]
    try:
        return fn(svc, output_dir, change=change, reasoning=reasoning)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[payment-change] %s failed", verb, exc_info=True)
        return _envelope(False, reason=f"{type(exc).__name__}: {str(exc)[:300]}")


__all__ = ["VERBS", "refund", "run", "set_currency"]
