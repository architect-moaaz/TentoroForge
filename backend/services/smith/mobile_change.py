"""The application on a phone is Smith's to change.

"Make it installable", "turn on push notifications", "portrait only",
"send me a test notification": the policy lives in the Blueprint's
`mobile`, is projected into the app (manifest, icons, service worker,
`src/lib/mobile.ts`) and read by its frame. A test notification is sent
through the running copy to the named person's subscribed devices, and
the reply says how many were reached — or that none is subscribed.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from services.llm_client import tell

logger = logging.getLogger(__name__)

VERBS = ("edit_mobile", "test_notification")
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")


def _envelope(applied: bool, *, reason: str = "", diff: str = "", paths: list[str] | None = None,
              options: list[str] | None = None, **more: Any) -> dict:
    return {"applied": applied, "reason": reason, "diff_summary": diff,
            "edited_paths": list(paths or []), "options": list(options or []), **more}


def _mobile(svc: Any) -> dict:
    mob = svc.doc.setdefault("mobile", {})
    mob.setdefault("installable", True)
    mob.setdefault("display", "standalone")
    mob.setdefault("orientation", "any")
    mob.setdefault("push", False)
    mob.setdefault("store", {"enabled": False})
    return mob


def _project(svc: Any, app_root: Any, output_dir: str) -> list[str]:
    if app_root is None:
        return []
    from services.blueprint.projection import project_pwa
    return list(project_pwa(svc.doc, app_root, output_dir).get("files") or [])


def edit_mobile(svc: Any, output_dir: str, *, change: str = "", app_root: Any = None, reasoning: Any = None, **_: Any) -> dict:
    text = (change or "").lower()
    mob = _mobile(svc)
    before = svc.snapshot()
    said: list[str] = []
    off = any(w in text for w in ("off", "stop", "no ", "not ", "remove", "disable", "without"))
    if "push" in text or "notification" in text:
        mob["push"] = not off
        said.append("push notifications reach people's devices" if mob["push"] else "no push notifications")
    if "install" in text or "home screen" in text or "homescreen" in text:
        mob["installable"] = not off
        said.append("it installs on a phone" if mob["installable"] else "it does not offer itself for the home screen")
    for word in ("portrait", "landscape"):
        if word in text:
            mob["orientation"] = word
            said.append(f"{word} only")
    if "any orientation" in text or "either orientation" in text or "rotate" in text:
        mob["orientation"] = "any"
        said.append("any orientation")
    if "full screen" in text or "fullscreen" in text:
        mob["display"] = "fullscreen"
        said.append("full screen")
    elif "standalone" in text or "like an app" in text:
        mob["display"] = "standalone"
        said.append("shown like an app, without the browser's bar")
    elif "in the browser" in text or "browser tab" in text:
        mob["display"] = "browser"
        said.append("shown in the browser")
    m = re.search(r"\b(?:bundle|package)\s*id\s*(?:is|=|:)?\s*([a-z][a-z0-9]*(?:\.[a-z][a-z0-9]*)+)", text, re.I)
    if "store" in text or "app store" in text or "play store" in text or m:
        store = mob.setdefault("store", {"enabled": False})
        if m:
            store["bundleId"] = m.group(1)
        if off and not m:
            store["enabled"] = False
            said.append("no store wrapper")
        elif store.get("bundleId"):
            store["enabled"] = True
            said.append(f"a store wrapper with the bundle id {store['bundleId']}")
        else:
            return _envelope(False, reason="A store wrapper needs its bundle id (com.example.app): what should it be?")
    if not said:
        return _envelope(False, reason="Which of these? \"make it installable\", \"turn on push notifications\", \"portrait only\", "
                                       "\"full screen\", \"a store wrapper with bundle id com.acme.app\".",
                         options=["Turn on push notifications", "Portrait only", "Make it installable"])
    svc.save()
    svc.commit(user_request=change, smith_interpretation="; ".join(said), before=before, affected=[])
    files = _project(svc, app_root, output_dir)
    tell(reasoning, "; ".join(said).capitalize() + ".", "step")
    note = ""
    if mob.get("push") and "push" in text:
        note = " People turn notifications on from the bell on their device; a process reaches them with `channels: [\"in_app\", \"push\"]`."
    return _envelope(True, diff="On a phone: " + "; ".join(said) + "." + note, paths=files)


def test_notification(svc: Any, output_dir: str, *, change: str = "", app_root: Any = None, reasoning: Any = None, **_: Any) -> dict:
    from services.blueprint.projection import mobile_policy
    if not mobile_policy(svc.doc)["push"]:
        return _envelope(False, reason="This application does not send push notifications yet. Say \"turn on push notifications\" first.",
                         options=["Turn on push notifications"])
    m = _EMAIL.search(change or "")
    email = m.group(0).lower() if m else ""
    from services.blueprint.page_review import ADMIN_EMAIL
    from services.smith import trials
    bench = trials.Bench(output_dir)
    try:
        try:
            app = bench.app()
        except trials.TrialUnavailable as exc:
            return _envelope(False, reason=f"The app could not be started to send one: {exc}")
        from services.blueprint.page_review import _query
        who = email or ADMIN_EMAIL
        rows = _query(app, f"select id::text, coalesce(name, email), coalesce(role, account_type, '') from users where lower(email) = '{who.replace(chr(39), chr(39)*2).lower()}' limit 1")
        if not rows or not rows[0]:
            return _envelope(False, reason=f"{who} has no login here. Who should get it? Give the email they sign in with.")
        user_id, name, role = rows[0][0], rows[0][1], rows[0][2]
        from services.preview_session import Session, cookies
        jar = cookies(Session(sub=user_id, name=name, email=who, role=role), base_url=app.base)
        status, _loc, text = trials._http(app, "POST", "/api/push/test", {}, jar)
        import json as _json
        try:
            out = _json.loads(text) if text else {}
        except ValueError:
            out = {}
    finally:
        try:
            bench.close()
        except Exception:  # noqa: BLE001
            pass
    if status != 200:
        return _envelope(False, reason=f"The test could not be sent ({status}): {str(out)[:200]}")
    sent = int(out.get("sent") or 0)
    tell(reasoning, f"Sent a test notification to {who}: {sent} device(s).", "step")
    if sent == 0:
        return _envelope(True, diff=f"No device of {who} is subscribed{(' — ' + str(out.get('notice'))) if out.get('notice') else ''}. "
                                    "They turn notifications on from the bell on their phone (on iPhone, after adding the app to the Home Screen).")
    return _envelope(True, diff=f"A test notification reached {sent} device(s) of {who}" + (f" ({out['pruned']} stale subscription(s) removed)" if out.get("pruned") else "") + ".")


def run(output_dir: str, verb: str, *, change: str = "", reasoning: Any = None) -> dict:
    from pathlib import Path

    from services.blueprint.service import BlueprintService
    if verb not in VERBS:
        return _envelope(False, reason=f"not a mobile verb: {verb}")
    try:
        svc = BlueprintService.load(output_dir=output_dir)
    except FileNotFoundError:
        return _envelope(False, reason="this project has no Blueprint yet.")
    app_root = Path(output_dir) / "app"
    fn = {"edit_mobile": edit_mobile, "test_notification": test_notification}[verb]
    try:
        return fn(svc, output_dir, change=change, app_root=app_root if app_root.is_dir() else None, reasoning=reasoning)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[mobile-change] %s failed", verb, exc_info=True)
        return _envelope(False, reason=f"{type(exc).__name__}: {str(exc)[:300]}")


__all__ = ["VERBS", "edit_mobile", "run", "test_notification"]
