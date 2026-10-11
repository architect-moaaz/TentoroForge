"""The check: a manifest, icons of their declared size, the worker and the
offline page answer; a device subscribed for a person receives a signed,
encrypted message when a notifying process runs, and nothing after it
unsubscribes. Smith turns push on and sends a test (2026-10-12). The
shipped worker and push module run under `run-pwa-tests.sh`."""
from __future__ import annotations

import json
import struct
import urllib.request
import zlib

from services.blueprint import pwa_check as pc

DOC = {"application": {"name": "Field Crew"}, "mobile": {"push": True}, "designSystem": {},
       "roles": [{"id": "ROLE-001", "name": "Worker"}],
       "workflows": [{"id": "FLOW-001", "name": "Tell the worker", "status": "APPROVED", "launchedFrom": {"roles": ["ROLE-001"]},
                      "steps": [{"id": "s1", "config": {"actionType": "send_notification", "channels": ["in_app", "push"], "toRole": "ROLE-001"}}]}]}


def _png(w: int, h: int) -> bytes:
    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IEND", b"")


def test_installable_is_proven_end_to_end(monkeypatch):
    manifest = {"name": "Field Crew", "icons": [{"src": "icons/icon-192.png", "sizes": "192x192"}, {"src": "icons/icon-512.png", "sizes": "512x512"}]}
    answers = {"/manifest.webmanifest": (200, json.dumps(manifest).encode()), "/icons/icon-192.png": (200, _png(192, 192)),
               "/icons/icon-512.png": (200, _png(512, 512)), "/sw.js": (200, b"forge-shell /api/"), "/offline": (200, b"<html>"),
               "/login": (200, b'<link rel="manifest" href="/manifest.webmanifest"><meta name="theme-color" content="#000">')}
    monkeypatch.setattr(pc, "_get", lambda app, path, cookies=None: (*answers.get(path, (404, b"")), ) if False else (answers.get(path, (404, b""))[0], {}, answers.get(path, (404, b""))[1]))
    app = type("App", (), {"base": "http://app"})()
    out = pc.check_installable(app, {**DOC, "security": {"authentication": "email_password"}})
    assert out["red"] == [] and out["green"][0]["why"].startswith("manifest, 2 icons")
    answers["/icons/icon-512.png"] = (200, _png(256, 256))
    out = pc.check_installable(app, {**DOC, "security": {"authentication": "email_password"}})
    assert out["red"] and "not a 512x512 PNG" in out["red"][0]["why"]
    assert pc.check_installable(app, {"mobile": {"installable": False}})["total"] == 0


def test_a_push_is_proven_with_the_checks_own_device(monkeypatch):
    assert [w["id"] for w in pc.pushing(DOC)] == ["FLOW-001"] and pc.pushing({**DOC, "mobile": {"push": False}}) == []
    state = {"endpoint": "", "subscribed": False}

    def rows(app, sql):
        if "select id::text from users" in sql:
            return [["u-1"]]
        if "insert into forge_push_subscriptions" in sql:
            state["endpoint"] = sql.split("', '")[1]
            state["subscribed"] = True
        if "delete from forge_push_subscriptions" in sql:
            state["subscribed"] = False
        return []

    def try_workflow(bench, doc, ref, payload, as_):
        assert ref == "FLOW-001" and as_ == "Worker"
        if state["subscribed"]:
            req = urllib.request.Request(state["endpoint"], data=b"\x00" * 40, method="POST",
                                         headers={"Authorization": "vapid t=abc, k=def", "Content-Encoding": "aes128gcm"})
            urllib.request.urlopen(req, timeout=10).read()
        return "ran"
    monkeypatch.setattr(pc, "_rows", rows)
    monkeypatch.setattr("services.smith.trials.try_workflow", try_workflow)
    app = type("App", (), {"base": "http://app"})()
    out = pc.check_push(app, DOC, bench=object())
    assert out["red"] == [] and out["green"][0]["cause"] == "FLOW-001" and "delivered once" in out["green"][0]["why"]
    pub, auth = pc.device_keys()
    assert len(pub) == 87 and len(auth) == 22


def test_smith_changes_the_phone_and_the_verbs_are_smiths(tmp_path):
    from services.blueprint.service import BlueprintService
    from services.smith import mobile_change
    svc = BlueprintService.create(output_dir=tmp_path, app_id="a", name="Field Crew", domain="field")
    out = mobile_change.edit_mobile(svc, str(tmp_path), change="turn on push notifications")
    doc = BlueprintService.load(output_dir=tmp_path).doc
    assert out["applied"] and doc["mobile"]["push"] is True and "bell" in out["diff_summary"]
    out = mobile_change.edit_mobile(svc, str(tmp_path), change="the app should be portrait only on phones")
    assert out["applied"] and BlueprintService.load(output_dir=tmp_path).doc["mobile"]["orientation"] == "portrait"
    out = mobile_change.edit_mobile(svc, str(tmp_path), change="a store wrapper")
    assert not out["applied"] and "bundle id" in out["reason"]
    out = mobile_change.edit_mobile(svc, str(tmp_path), change="a store wrapper with bundle id com.acme.crew")
    assert out["applied"] and BlueprintService.load(output_dir=tmp_path).doc["mobile"]["store"] == {"enabled": True, "bundleId": "com.acme.crew"}
    out = mobile_change.edit_mobile(svc, str(tmp_path), change="turn push notifications off")
    assert out["applied"] and BlueprintService.load(output_dir=tmp_path).doc["mobile"]["push"] is False
    out = mobile_change.test_notification(svc, str(tmp_path), change="send me a test notification")
    assert not out["applied"] and "turn on push" in out["reason"].lower()
    from services.smith.capabilities import GROUPS
    from services.smith.verbs import REQUIRED_BY_VERB, VERB_EXAMPLES, VERB_HELP
    from services.smith4.verbs import PERFORM
    for v in ("edit_mobile", "test_notification"):
        assert v in REQUIRED_BY_VERB and v in VERB_HELP and v in VERB_EXAMPLES and v in PERFORM and any(v in g[2] for g in GROUPS)
    from services.blueprint.fix_to_green import by_cause
    assert by_cause([{"cause": "mobile", "label": "x", "why": "y"}])[0]["kind"] == "mobile"
