"""A recording of the person's own session comes in with every credential
and goes out as call shapes with none of them."""
from __future__ import annotations

import json

import pytest

from services.drafts_room import calls as callrec
from services.drafts_room import har, store
from services.smith.secrets_scrub import carries_secret

COOKIE = "session=abcdef0123456789abcdef"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlc2lnbmF0dXJl"
STRIPE = "sk_live_" + "A1b2C3d4E5f6G7h8I9j0"


def _har():
    return {"log": {"entries": [
        {"startedDateTime": "2026-10-15T10:00:00Z", "pageref": "page_1",
         "request": {"method": "GET", "url": "https://app.shop.test/api/orders/8821?token=abc123secret&page=2",
                     "headers": [{"name": "Cookie", "value": COOKIE}, {"name": "Authorization", "value": "Bearer " + JWT},
                                 {"name": "Accept", "value": "application/json"}], "cookies": [{"name": "session", "value": COOKIE}]},
         "response": {"status": 200, "headers": [{"name": "Set-Cookie", "value": COOKIE}],
                      "content": {"mimeType": "application/json",
                                  "text": json.dumps({"id": 8821, "status": "paid", "total": 42.5, "customer": {"email": "a@b.test", "key": STRIPE},
                                                      "lines": [{"sku": "X1", "qty": 2}]})}}},
        {"request": {"method": "POST", "url": "https://api.shop.test/v2/orders/8821/refunds",
                     "headers": [], "postData": {"mimeType": "application/json", "text": json.dumps({"amount": 10, "reason": "late", "apiKey": STRIPE})}},
         "response": {"status": 201, "headers": [], "content": {"mimeType": "application/json", "text": json.dumps({"id": "r1", "status": "pending"})}}},
        {"request": {"method": "GET", "url": "https://cdn.other.test/a.png", "headers": []},
         "response": {"status": 200, "headers": [], "content": {"mimeType": "image/png", "text": "AAAA", "encoding": "base64"}}},
        {"request": {"method": "GET", "url": "https://tracker.evil.test/collect", "headers": []},
         "response": {"status": 200, "headers": [], "content": {"mimeType": "application/json", "text": "{}"}}},
    ]}}


def test_the_recording_keeps_the_sites_call_shapes_and_none_of_the_secrets():
    calls = har.scrub_har(json.dumps(_har()).encode(), "https://app.shop.test")
    assert [c["method"] + " " + c["path"] for c in calls] == ["GET /api/orders/{id}", "POST /v2/orders/{id}/refunds"]
    text = json.dumps(calls)
    for secret in (COOKIE, JWT, STRIPE, "abc123secret", "a@b.test", "42.5"):
        assert secret not in text, secret
    assert not carries_secret(text)
    get = calls[0]
    assert get["query_keys"] == ["page"] and "token" not in get["url"]
    assert get["response_shape"]["status"] == "text" and get["response_shape"]["total"] == "number"
    assert get["response_shape"]["customer"]["email"] == "email"
    assert get["response_shape"]["lines"] == {"list": 1, "of": {"sku": "text", "qty": "number"}}
    assert get["enums"]["status"] == {"values": ["paid"], "seen": 1}
    post = calls[1]
    assert post["request_keys"] == ["amount", "apiKey", "reason"] and post["source"] == "har"
    assert post["host"] == "api.shop.test"


def test_a_file_that_is_not_a_recording_or_too_large_is_refused():
    with pytest.raises(har.BadRecording, match="not JSON"):
        har.scrub_har(b"<html>", "x.test")
    with pytest.raises(har.BadRecording, match="log.entries"):
        har.scrub_har(b'{"log": {}}', "x.test")
    with pytest.raises(har.BadRecording, match="50 MB"):
        har.scrub_har(b"x" * (har.MAX_UPLOAD + 1), "x.test")


def test_headers_and_query_names_that_carry_credentials_are_dropped():
    for name in ("Cookie", "set-cookie", "Authorization", "X-Api-Key", "X-Session-Id", "x-forge-token"):
        assert not callrec.keep_header(name), name
    assert callrec.keep_header("Accept") and callrec.keep_header("Content-Type")
    url, keys = callrec.clean_url("https://x.test/a?access_token=1&q=shoes&sig=2&state=3")
    assert url == "https://x.test/a?q=shoes" and keys == ["q"]
    assert callrec.normalise_path("/orders/8f3a9b2c-1d2e-4f5a-8b9c-0d1e2f3a4b5c/items/42/v1") == "/orders/{id}/items/{id}/v1"


def test_the_raw_upload_is_never_on_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path / "s")
    from services.drafts_room import capture
    monkeypatch.setattr(capture, "_cards_after", lambda sid, rid: None)   # the writer is a model call
    s = store.create("org", "u", "")
    ref = store.new_reference(s["id"], "Shop", "https://app.shop.test", added_by="u")
    calls = har.scrub_har(json.dumps(_har()).encode(), ref["url"])
    job = capture.from_recording(s, ref, calls)
    assert job["status"] == "done" and job["source"] == "har" and job["capture"]["calls"] == 2
    kinds = {(i["kind"], i["text"]) for i in job["evidence"]}
    assert ("record", "orders") in kinds and ("action", "POST /v2/orders/{id}/refunds") in kinds
    assert all(s_["type"] == "har" for i in job["evidence"] for s_ in i["sources"])
    everything = "".join(p.read_text(errors="ignore") for p in (tmp_path / "s").rglob("*") if p.is_file())
    for secret in (COOKIE, JWT, STRIPE, "abc123secret"):
        assert secret not in everything, secret
