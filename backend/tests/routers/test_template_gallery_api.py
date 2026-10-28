"""The Templates Gallery: a template is reviewed by Tentoro before anyone else sees it.

The journey, end to end, with three people: the builder (in their own
organisation), Tentoro's admin (admin@tentoro.ai) and someone from another
organisation. A saved template is a private draft; submitted, it waits for the
admin, who is told in Forge and by email; sent back, it carries the reason;
approved, it is in the Gallery, where the other organisation sees what it
holds, uses it — counted — and rates it, and can open the builder's profile.
Every refusal on the way is checked too, because each one guards something:
a private template stays private, a review copy is not a use, the builder
cannot rate their own, and nothing is published that holds a key.
"""
from __future__ import annotations

import io
import json
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from services import project_templates as templates

FIXTURE = Path(__file__).resolve().parents[2] / "fleet" / "blueprints" / "ats-live.json"
GOOD_DESCRIPTION = "Track candidates from application to offer, with interviews and scorecards."


def _png(w: int = 64, h: int = 40, color=(30, 90, 200)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def mailbox(monkeypatch):
    """Every email the gallery sends, as (to, template, context)."""
    sent: list[tuple[str, str, dict]] = []

    async def capture(to, template, context=None):
        sent.append((to, template, dict(context or {})))
        return True
    monkeypatch.setattr("services.email_service.send_email", capture)
    return sent


async def _person(email: str, name: str) -> AsyncClient:
    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    r = await c.post("/api/auth/signup", json={"email": email, "name": name, "password": "Testpass123"})
    assert r.status_code == 201, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


async def _org(c: AsyncClient, slug: str) -> str:
    r = await c.post("/api/orgs", json={"name": slug.title(), "slug": slug})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def _defined_project(client: AsyncClient, org_id: str, name: str, *, mutate=None) -> dict:
    from services.project_service import OUTPUT_BASE

    res = await client.post(f"/api/orgs/{org_id}/projects", json={"name": name})
    assert res.status_code == 201, res.text
    body = res.json()
    out = Path(OUTPUT_BASE) / body["short_id"]
    (out / ".forge" / "blueprint").mkdir(parents=True, exist_ok=True)
    doc = json.loads(FIXTURE.read_text())
    if mutate:
        mutate(doc)
    (out / ".forge" / "blueprint" / "current.json").write_text(json.dumps(doc))
    return {**body, "output_dir": out}


async def _ready_template(client: AsyncClient, org_id: str, name: str = "Hiring") -> tuple[dict, dict]:
    """A saved template with a description and one screenshot: ready to submit."""
    src = await _defined_project(client, org_id, name)
    tpl = (await client.post(f"/api/projects/{src['id']}/templates",
                             json={"name": f"{name} desk", "description": GOOD_DESCRIPTION})).json()
    r = await client.post(f"/api/project-templates/{tpl['id']}/screenshots",
                          files={"file": ("shot.png", _png(), "image/png")})
    assert r.status_code == 201, r.text
    return src, tpl


async def _notifications(c: AsyncClient) -> list[dict]:
    r = await c.get("/api/notifications")
    assert r.status_code == 200, r.text
    body = r.json()
    return body if isinstance(body, list) else body.get("notifications") or body.get("items") or []


@pytest.mark.asyncio
async def test_the_whole_journey_from_request_to_rating(auth_client, org_id, super_admin_client, mailbox):
    builder, admin = auth_client, super_admin_client
    src, tpl = await _ready_template(builder, org_id)
    assert tpl["status"] == "draft" and tpl["version"] == 1 and tpl["uses"] == 0

    outsider = await _person("visitor@example.com", "Vera Visitor")
    try:
        other_org = await _org(outsider, "visitors")
        # A draft is its organisation's alone.
        assert (await outsider.get(f"/api/project-templates/{tpl['id']}")).status_code == 404
        assert (await outsider.get("/api/template-gallery")).json()["templates"] == []

        # 1 + 3: submitted, it goes to Tentoro — in Forge and by email.
        r = await builder.post(f"/api/project-templates/{tpl['id']}/submit", json={"pricing_model": "free"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "pending"
        admin_notes = await _notifications(admin)
        assert any(n["type"] == "template_review_requested" and "Hiring desk" in n["title"] for n in admin_notes)
        assert [(to, t) for to, t, _ in mailbox] == [("admin@tentoro.ai", "template_review_requested")]
        assert mailbox[0][2]["review_url"].endswith(f"/admin/templates?request={tpl['id']}")

        # Still not anyone else's to see, and submitting twice is refused.
        assert (await outsider.get(f"/api/project-templates/{tpl['id']}")).status_code == 404
        assert (await builder.post(f"/api/project-templates/{tpl['id']}/submit", json={})).status_code == 409

        # 4: the admin's queue shows it with what a reviewer reads.
        queue = (await admin.get("/api/admin/template-requests")).json()
        assert [t["id"] for t in queue["requests"]] == [tpl["id"]] and queue["counts"]["pending"] == 1
        detail = (await admin.get(f"/api/project-templates/{tpl['id']}/detail")).json()
        assert detail["is_admin"] and detail["preview"]["screens"] and detail["preview"]["records"]
        assert all(c["ok"] for c in detail["checks"] if c["blocking"])
        assert detail["screenshots"][0]["width"] == 64
        # The reviewer can look at the screenshot; the outsider still cannot.
        shot = detail["screenshots"][0]["id"]
        img = await admin.get(f"/api/project-templates/{tpl['id']}/screenshots/{shot}")
        assert img.status_code == 200 and img.content.startswith(b"\x89PNG")
        assert (await outsider.get(f"/api/project-templates/{tpl['id']}/screenshots/{shot}")).status_code == 404

        # Changes asked for must say what; the builder reads the reason.
        r = await admin.post(f"/api/admin/template-requests/{tpl['id']}/decision", json={"decision": "reject"})
        assert r.status_code == 400
        r = await admin.post(f"/api/admin/template-requests/{tpl['id']}/decision",
                             json={"decision": "reject", "note": "Add a screenshot of the pipeline board."})
        assert r.status_code == 200 and r.json()["status"] == "rejected"

        # 2: the requester sees where it stands, and why.
        mine = (await builder.get(f"/api/project-templates/{tpl['id']}/detail")).json()
        assert mine["status"] == "rejected" and "pipeline board" in mine["review_note"]
        assert [h["status"] for h in mine["history"]] == ["pending", "rejected"]
        assert any(n["type"] == "template_changes_requested" for n in await _notifications(builder))
        assert mailbox[-1][:2] == ("test@example.com", "template_changes_requested")

        # Fixed and sent again; approved this time.
        r = await builder.post(f"/api/project-templates/{tpl['id']}/screenshots",
                               files={"file": ("board.png", _png(80, 50), "image/png")})
        assert r.status_code == 201
        assert (await builder.post(f"/api/project-templates/{tpl['id']}/submit", json={})).json()["status"] == "pending"
        r = await admin.post(f"/api/admin/template-requests/{tpl['id']}/decision",
                             json={"decision": "approve", "note": "Looks great."})
        assert r.status_code == 200 and r.json()["status"] == "approved"
        hist = (await builder.get(f"/api/project-templates/{tpl['id']}/detail")).json()["history"]
        assert [h["status"] for h in hist] == ["pending", "rejected", "pending", "approved"]
        assert hist[2]["note"] == "Sent again for review"
        assert mailbox[-1][:2] == ("test@example.com", "template_approved")

        # 5: in the Gallery, for another organisation, with who built it and when.
        g = (await outsider.get("/api/template-gallery")).json()
        card = g["templates"][0]
        assert card["id"] == tpl["id"] and card["status"] == "approved" and card["version"] == 1
        assert card["creator"]["name"] == "Test User" and card["org_name"] == "Test Org"
        assert card["created_at"] and card["published_at"] and len(card["screenshots"]) == 2
        # Rated only by someone who used it (PR #29 review): not yet.
        assert card["can_use"] and not card["can_rate"] and not card["can_manage"]
        r = await outsider.put(f"/api/project-templates/{tpl['id']}/reviews/mine", json={"rating": 5})
        assert r.status_code == 403 and "Start an app from this template first" in r.text
        assert card["source_project_id"] is None and card["review_note"] == ""  # not theirs to read
        detail = (await outsider.get(f"/api/project-templates/{tpl['id']}/detail")).json()
        assert {"screens", "records", "workflows", "roles", "rules"} <= set(detail["preview"])
        assert "checks" not in detail and "history" not in detail
        # An approved template is what was approved: changes are a new version.
        assert (await builder.patch(f"/api/project-templates/{tpl['id']}", json={"name": "X"})).status_code == 409
        assert (await builder.post(f"/api/project-templates/{tpl['id']}/screenshots",
                                   files={"file": ("x.png", _png(), "image/png")})).status_code == 409

        # 6: using it is counted, once per project.
        r = await outsider.post(f"/api/orgs/{other_org}/projects/from-project-template",
                                json={"template_id": tpl["id"], "name": "Our hiring"})
        assert r.status_code == 201, r.text
        assert (await outsider.get("/api/template-gallery")).json()["templates"][0]["uses"] == 1
        # A use is an organisation: a second app of the same one is not another.
        r = await outsider.post(f"/api/orgs/{other_org}/projects/from-project-template",
                                json={"template_id": tpl["id"], "name": "Our hiring 2"})
        assert r.status_code == 201, r.text
        card = (await outsider.get("/api/template-gallery")).json()["templates"][0]
        assert card["uses"] == 1 and card["can_rate"]

        # 8: rated and reviewed; rating again changes the review, not the count.
        assert (await outsider.put(f"/api/project-templates/{tpl['id']}/reviews/mine",
                                   json={"rating": 4, "comment": "Saved us a week."})).status_code == 200
        r = await outsider.put(f"/api/project-templates/{tpl['id']}/reviews/mine",
                               json={"rating": 5, "comment": "Saved us two weeks."})
        assert r.json() == {"new": False, "rating": 5.0, "ratings": 1,
                            "my_review": {"rating": 5, "comment": "Saved us two weeks."}}
        reviews = (await builder.get(f"/api/project-templates/{tpl['id']}/reviews")).json()["reviews"]
        assert len(reviews) == 1 and reviews[0]["used_it"] and reviews[0]["user"]["name"] == "Vera Visitor"
        assert any(n["type"] == "template_rated" for n in await _notifications(builder))
        for bad in (0, 6, 3.5, True, "5"):
            r = await outsider.put(f"/api/project-templates/{tpl['id']}/reviews/mine", json={"rating": bad})
            assert r.status_code in (400, 422), bad
        # The builder cannot rate their own.
        r = await builder.put(f"/api/project-templates/{tpl['id']}/reviews/mine", json={"rating": 5})
        assert r.status_code == 403

        # 7: the builder's profile, from the card.
        prof = (await outsider.get(f"/api/template-creators/{card['creator']['id']}")).json()
        assert prof["name"] == "Test User" and prof["organisations"] == ["Test Org"]
        assert prof["totals"] == {"templates": 1, "uses": 1, "ratings": 1, "rating": 5.0}
        # Not a way to look anyone up: someone with nothing published is not found.
        me = (await outsider.get("/api/auth/me")).json()
        assert (await builder.get(f"/api/template-creators/{me['id']}")).status_code == 404

        # Deleting a review takes it out of the average.
        assert (await outsider.delete(f"/api/project-templates/{tpl['id']}/reviews/mine")).status_code == 204
        assert (await outsider.get("/api/template-gallery")).json()["templates"][0]["ratings"] == 0
    finally:
        await outsider.aclose()


@pytest.mark.asyncio
async def test_a_template_that_is_not_ready_is_refused_and_says_why(auth_client, org_id, mailbox):
    src = await _defined_project(auth_client, org_id, "Bare")
    tpl = (await auth_client.post(f"/api/projects/{src['id']}/templates", json={"description": "Short"})).json()
    checks = (await auth_client.get(f"/api/project-templates/{tpl['id']}/checks")).json()
    failing = {c["key"] for c in checks["checks"] if not c["ok"] and c["blocking"]}
    assert not checks["ready"] and failing == {"description", "screenshots"}
    r = await auth_client.post(f"/api/project-templates/{tpl['id']}/submit", json={})
    assert r.status_code == 422 and "screenshot" in r.json()["detail"]
    # Paid is kept ready, not offered yet.
    await auth_client.patch(f"/api/project-templates/{tpl['id']}", json={"description": GOOD_DESCRIPTION})
    await auth_client.post(f"/api/project-templates/{tpl['id']}/screenshots",
                           files={"file": ("s.png", _png(), "image/png")})
    r = await auth_client.post(f"/api/project-templates/{tpl['id']}/submit",
                               json={"pricing_model": "paid", "price_cents": 4900, "currency": "USD"})
    assert r.status_code == 400 and "coming soon" in r.json()["detail"]
    assert mailbox == []  # nobody was told about a request that was refused


@pytest.mark.asyncio
async def test_a_key_left_in_the_app_is_never_published(auth_client, org_id):
    def leak(doc):
        doc["application"]["description"] = "Uses key sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345 for AI."
    src = await _defined_project(auth_client, org_id, "Leaky", mutate=leak)
    tpl = (await auth_client.post(f"/api/projects/{src['id']}/templates",
                                  json={"description": GOOD_DESCRIPTION})).json()
    await auth_client.post(f"/api/project-templates/{tpl['id']}/screenshots",
                           files={"file": ("s.png", _png(), "image/png")})
    r = await auth_client.post(f"/api/project-templates/{tpl['id']}/submit", json={})
    assert r.status_code == 422 and "Anthropic or OpenAI key" in r.json()["detail"]


@pytest.mark.asyncio
async def test_only_real_pictures_are_kept(auth_client, org_id):
    src = await _defined_project(auth_client, org_id, "Pics")
    tpl = (await auth_client.post(f"/api/projects/{src['id']}/templates", json={})).json()
    url = f"/api/project-templates/{tpl['id']}/screenshots"
    for name, data in (("evil.png", b"<script>alert(1)</script>"),            # named png, is not
                       ("half.png", b"\x89PNG\r\n\x1a\n" + b"\0" * 64),        # starts like one, is not
                       ("anim.gif", b"GIF89a" + b"\0" * 64),                   # a kind not taken
                       ("empty.png", b"")):
        r = await auth_client.post(url, files={"file": (name, data, "image/png")})
        assert r.status_code == 400, name
    big = b"\x89PNG\r\n\x1a\n" + b"\0" * (templates.SCREENSHOT_BYTES_MAX + 10)
    assert (await auth_client.post(url, files={"file": ("big.png", big, "image/png")})).status_code == 400
    for _ in range(templates.SCREENSHOT_MAX):
        assert (await auth_client.post(url, files={"file": ("s.png", _png(), "image/png")})).status_code == 201
    r = await auth_client.post(url, files={"file": ("s.png", _png(), "image/png")})
    assert r.status_code == 400 and "at most" in r.json()["detail"]
    shots = templates.get(tpl["id"])["screenshots"]
    # The order is the builder's; the first is the cover.
    r = await auth_client.put(f"{url}/order", json={"order": [shots[-1]["id"]]})
    assert r.json()["screenshots"][0]["id"] == shots[-1]["id"]
    assert (await auth_client.delete(f"{url}/{shots[0]['id']}")).status_code == 204
    assert (await auth_client.delete(f"{url}/{shots[0]['id']}")).status_code == 404
    assert (await auth_client.get(f"{url}/../../meta")).status_code == 404
    assert (await auth_client.get(f"{url}/{'0' * 32}")).status_code == 404


@pytest.mark.asyncio
async def test_the_apps_own_screens_are_added_once(auth_client, org_id):
    src = await _defined_project(auth_client, org_id, "Looks")
    doc = json.loads((src["output_dir"] / ".forge" / "blueprint" / "current.json").read_text())
    page = doc["pages"][0]
    for attempt in (1, 2):
        d = src["output_dir"] / ".forge" / "look" / page["id"] / f"look-{attempt}"
        d.mkdir(parents=True)
        (d / "desktop.png").write_bytes(_png(120 + attempt, 80))
    tpl = (await auth_client.post(f"/api/projects/{src['id']}/templates", json={})).json()
    r = (await auth_client.post(f"/api/project-templates/{tpl['id']}/screenshots/from-app")).json()
    assert len(r["added"]) == 1 and r["added"][0]["source"] == "app"
    assert r["added"][0]["width"] == 122  # the newest look of the page
    assert r["added"][0]["caption"] == (page.get("name") or page.get("title") or page.get("route"))
    again = (await auth_client.post(f"/api/project-templates/{tpl['id']}/screenshots/from-app")).json()
    assert again["added"] == []


@pytest.mark.asyncio
async def test_a_new_version_replaces_the_old_and_keeps_what_it_earned(auth_client, org_id, super_admin_client):
    builder, admin = auth_client, super_admin_client
    src, v1 = await _ready_template(builder, org_id)
    await builder.post(f"/api/project-templates/{v1['id']}/submit", json={})
    await admin.post(f"/api/admin/template-requests/{v1['id']}/decision", json={"decision": "approve"})
    fan = await _person("fan@example.com", "Fan")
    try:
        fan_org = await _org(fan, "fans")
        await fan.post(f"/api/orgs/{fan_org}/projects/from-project-template",
                       json={"template_id": v1["id"], "name": "Copy"})
        await fan.put(f"/api/project-templates/{v1['id']}/reviews/mine", json={"rating": 4})

        v2 = (await builder.post(f"/api/projects/{src['id']}/templates",
                                 json={"name": "Hiring desk", "description": GOOD_DESCRIPTION})).json()
        assert v2["version"] == 2 and v2["status"] == "draft"
        assert v2["uses"] == 1 and v2["rating"] == 4.0  # the lineage's, already
        await builder.post(f"/api/project-templates/{v2['id']}/screenshots",
                           files={"file": ("s.png", _png(), "image/png")})
        await builder.post(f"/api/project-templates/{v2['id']}/submit", json={})
        # Until v2 is approved, the Gallery still has v1.
        assert [t["id"] for t in (await fan.get("/api/template-gallery")).json()["templates"]] == [v1["id"]]
        await admin.post(f"/api/admin/template-requests/{v2['id']}/decision", json={"decision": "approve"})
        cards = (await fan.get("/api/template-gallery")).json()["templates"]
        assert [(c["id"], c["version"], c["uses"], c["rating"]) for c in cards] == [(v2["id"], 2, 1, 4.0)]
        assert (await builder.get(f"/api/project-templates/{v1['id']}")).json()["status"] == "superseded"
        # A project made from v1 is untouched, and v1 is no longer offered to others.
        assert (await fan.get(f"/api/project-templates/{v1['id']}")).status_code == 404
    finally:
        await fan.aclose()


@pytest.mark.asyncio
async def test_an_admins_review_copy_is_not_a_use(auth_client, org_id, super_admin_client):
    _src, tpl = await _ready_template(auth_client, org_id)
    await auth_client.post(f"/api/project-templates/{tpl['id']}/submit", json={})
    admin_org = await _org(super_admin_client, "tentoro")
    r = await super_admin_client.post(f"/api/orgs/{admin_org}/projects/from-project-template",
                                      json={"template_id": tpl["id"], "name": "Review copy"})
    assert r.status_code == 201, r.text
    assert (await auth_client.get(f"/api/project-templates/{tpl['id']}")).json()["uses"] == 0
    # Its own organisation may use its own pending template — but that is not a
    # use the Gallery counts: a builder could otherwise lift their own template
    # up the "popular" order by using it themselves.
    review_copy = (await super_admin_client.get(f"/api/orgs/{admin_org}/projects")).json()
    review_copy = review_copy.get("items", review_copy) if isinstance(review_copy, dict) else review_copy
    (review_copy,) = [p for p in review_copy if p["name"] == "Review copy"]
    r = await auth_client.post(f"/api/orgs/{org_id}/projects/from-project-template",
                               json={"template_id": tpl["id"], "name": "Ours"})
    assert r.status_code == 201
    ours = r.json()
    assert (await auth_client.get(f"/api/project-templates/{tpl['id']}")).json()["uses"] == 0
    # Decided: the admin's test copy is removed; the organisation's own app stays (PR #29 review).
    r = await super_admin_client.post(f"/api/admin/template-requests/{tpl['id']}/decision",
                                      json={"decision": "approve"})
    assert r.status_code == 200
    assert (await super_admin_client.get(f"/api/projects/{review_copy['id']}")).status_code == 404
    assert (await auth_client.get(f"/api/projects/{ours['id']}")).status_code == 200


@pytest.mark.asyncio
async def test_an_admins_app_from_a_gallery_template_is_a_real_app(auth_client, org_id, super_admin_client):
    """PR #29 re-review: an admin starting an app in their own organisation
    from a template already in the Gallery was marked a test copy, and
    deleted — database, domains and folder — when a later version was decided."""
    builder, admin = auth_client, super_admin_client
    src, v1 = await _ready_template(builder, org_id)
    await builder.post(f"/api/project-templates/{v1['id']}/submit", json={})
    await admin.post(f"/api/admin/template-requests/{v1['id']}/decision", json={"decision": "approve"})
    admin_org = await _org(admin, "tentoro")
    r = await admin.post(f"/api/orgs/{admin_org}/projects/from-project-template",
                         json={"template_id": v1["id"], "name": "Our real app"})
    assert r.status_code == 201, r.text
    real = r.json()
    # A real app is a real use.
    assert (await builder.get(f"/api/project-templates/{v1['id']}")).json()["uses"] == 1

    v2 = (await builder.post(f"/api/projects/{src['id']}/templates",
                             json={"name": "Hiring desk", "description": GOOD_DESCRIPTION})).json()
    await builder.post(f"/api/project-templates/{v2['id']}/screenshots",
                       files={"file": ("s.png", _png(), "image/png")})
    await builder.post(f"/api/project-templates/{v2['id']}/submit", json={})
    for decision in ("reject", "approve"):
        if decision == "approve":
            await builder.post(f"/api/project-templates/{v2['id']}/submit", json={})
        r = await admin.post(f"/api/admin/template-requests/{v2['id']}/decision",
                             json={"decision": decision, "note": "Please add a second screenshot."})
        assert r.status_code == 200, r.text
        assert (await admin.get(f"/api/projects/{real['id']}")).status_code == 200

    # Its own decision, run again, leaves it too.
    from database import async_session
    from routers.project_templates import _remove_test_copies
    from models.project import Project
    async with async_session() as db:
        project = await db.get(Project, uuid.UUID(real["id"]))
        assert "review_copy" not in (project.brief or {})["template"]
        assert await _remove_test_copies(db, v1["id"]) == 0
    assert (await admin.get(f"/api/projects/{real['id']}")).status_code == 200


@pytest.mark.asyncio
async def test_the_review_queue_is_tentoros_alone(auth_client, org_id):
    _src, tpl = await _ready_template(auth_client, org_id)
    await auth_client.post(f"/api/project-templates/{tpl['id']}/submit", json={})
    assert (await auth_client.get("/api/admin/template-requests")).status_code == 403
    r = await auth_client.post(f"/api/admin/template-requests/{tpl['id']}/decision",
                               json={"decision": "approve"})
    assert r.status_code == 403
    # Taking a request back returns it to a draft.
    r = await auth_client.post(f"/api/project-templates/{tpl['id']}/cancel-request")
    assert r.status_code == 200 and r.json()["status"] == "draft"
    assert (await auth_client.post(f"/api/project-templates/{tpl['id']}/cancel-request")).status_code == 409


@pytest.mark.asyncio
async def test_a_removed_or_deleted_template_leaves_the_gallery(auth_client, org_id, super_admin_client, mailbox):
    _src, tpl = await _ready_template(auth_client, org_id)
    await auth_client.post(f"/api/project-templates/{tpl['id']}/submit", json={})
    await super_admin_client.post(f"/api/admin/template-requests/{tpl['id']}/decision",
                                  json={"decision": "approve"})
    r = await super_admin_client.post(f"/api/admin/template-requests/{tpl['id']}/decision",
                                      json={"decision": "remove"})
    assert r.status_code == 400  # a reason is required
    r = await super_admin_client.post(f"/api/admin/template-requests/{tpl['id']}/decision",
                                      json={"decision": "remove", "note": "Duplicate of another."})
    assert r.json()["status"] == "removed"
    assert mailbox[-1][:2] == ("test@example.com", "template_removed")
    assert (await super_admin_client.get("/api/template-gallery")).json()["templates"] == []
    # Sent again and approved, then deleted by its builder: gone everywhere.
    await auth_client.post(f"/api/project-templates/{tpl['id']}/submit", json={})
    await super_admin_client.post(f"/api/admin/template-requests/{tpl['id']}/decision",
                                  json={"decision": "approve"})
    assert len((await super_admin_client.get("/api/template-gallery")).json()["templates"]) == 1
    assert (await auth_client.delete(f"/api/project-templates/{tpl['id']}")).status_code == 204
    assert (await super_admin_client.get("/api/template-gallery")).json()["templates"] == []
    assert (await super_admin_client.get("/api/admin/template-requests?status=all")).json()["requests"] == []


@pytest.mark.asyncio
async def test_a_template_name_is_text_in_the_email_not_markup(auth_client, org_id, super_admin_client, monkeypatch):
    seen = {}

    async def capture(to, template, context=None):
        from services.email_service import TEMPLATES, render
        seen[to] = render(TEMPLATES[template], context or {})
        return True
    monkeypatch.setattr("services.email_service.send_email", capture)
    src = await _defined_project(auth_client, org_id, "Esc")
    tpl = (await auth_client.post(f"/api/projects/{src['id']}/templates", json={
        "name": '<a href="https://evil.example">Click</a>', "description": GOOD_DESCRIPTION})).json()
    await auth_client.post(f"/api/project-templates/{tpl['id']}/screenshots",
                           files={"file": ("s.png", _png(), "image/png")})
    assert (await auth_client.post(f"/api/project-templates/{tpl['id']}/submit", json={})).status_code == 200
    subject, html = seen["admin@tentoro.ai"]
    assert '<a href="https://evil.example">' not in html and "&lt;a href=" in html
    # The subject is plain text: the name as written, not as HTML.
    assert subject == 'Template to review: <a href="https://evil.example">Click</a>'


def test_a_subject_is_one_line_and_plain_text():
    from services.email_service import TEMPLATES, render
    subject, body = render(TEMPLATES["template_approved"], {
        "name": "Dev", "template_name": "R&D Tracker\r\nBcc: everyone@example.com", "note": "ok",
        "template_url": "https://x"})
    assert "\n" not in subject and "\r" not in subject
    assert subject == "R&D Tracker Bcc: everyone@example.com is in the Templates Gallery"
    assert "R&amp;D Tracker" in body


@pytest.mark.asyncio
async def test_two_saves_of_one_app_at_once_are_two_versions(auth_client, org_id):
    import threading
    src = await _defined_project(auth_client, org_id, "Race")
    got, errors = [], []

    def save():
        try:
            got.append(templates.save(output_dir=src["output_dir"], org_id=org_id,
                                      source_project_id=src["id"])["version"])
        except Exception as exc:  # noqa: BLE001 — surfaced by the assert below
            errors.append(exc)
    threads = [threading.Thread(target=save) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and sorted(got) == [1, 2, 3, 4]


def test_a_small_file_that_unpacks_to_a_vast_picture_is_refused(tmp_path, monkeypatch):
    """A PNG of a few dozen kilobytes can describe a 20000×20000 bitmap; read
    in full, one upload would hold gigabytes of memory."""
    from PIL import Image
    monkeypatch.setenv("FORGE_OUTPUT_BASE", str(tmp_path))
    monkeypatch.setattr("services.project_service.OUTPUT_BASE", str(tmp_path))
    buf = io.BytesIO()
    Image.new("1", (20000, 20000)).save(buf, format="PNG")
    data = buf.getvalue()
    assert len(data) < templates.SCREENSHOT_BYTES_MAX
    with pytest.raises(templates.TemplateError, match="too large"):
        templates._decoded_size(data)


@pytest.mark.asyncio
async def test_a_gallery_of_pictures_does_not_spend_the_rate_limit():
    """Every card draws its cover with one request; a page of them used up the
    per-IP burst and the rest of the page answered 429."""
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    from middleware.rate_limit import RateLimitMiddleware

    async def ok(_request):
        return PlainTextResponse("ok")
    inner = Starlette(routes=[Route("/{path:path}", ok, methods=["GET", "POST"])])
    inner.add_middleware(RateLimitMiddleware, requests_per_minute=1, burst=1)
    import uuid

    from auth import create_access_token
    signed = {"Authorization": f"Bearer {create_access_token(uuid.uuid4())}"}
    async with AsyncClient(transport=ASGITransport(app=inner), base_url="http://t") as c:
        shot = f"/api/project-templates/{'a' * 32}/screenshots/{'b' * 32}"
        assert all([(await c.get(shot, headers=signed)).status_code == 200 for _ in range(30)])
        # Everything else still counts — including writes to the same address.
        assert (await c.get("/api/template-gallery")).status_code == 200
        assert (await c.get("/api/template-gallery")).status_code == 429
        assert (await c.post(shot, headers=signed)).status_code == 429
        # Nobody, or a made-up sign-in, counts like any request (PR #29 review).
        assert (await c.get(shot)).status_code == 429
        assert (await c.get(shot, headers={"Authorization": "Bearer made-up"})).status_code == 429


@pytest.mark.asyncio
async def test_a_deleted_versions_number_is_never_given_again(auth_client, org_id):
    src = await _defined_project(auth_client, org_id, "Numbers")
    v1 = (await auth_client.post(f"/api/projects/{src['id']}/templates", json={})).json()
    v2 = (await auth_client.post(f"/api/projects/{src['id']}/templates", json={})).json()
    assert (v1["version"], v2["version"]) == (1, 2)
    assert (await auth_client.delete(f"/api/project-templates/{v2['id']}")).status_code == 204
    v3 = (await auth_client.post(f"/api/projects/{src['id']}/templates", json={})).json()
    assert v3["version"] == 3


@pytest.mark.asyncio
async def test_an_unknown_domain_is_not_a_category(auth_client, org_id):
    def unknown(doc):
        doc["application"]["domain"] = "unknown"
    src = await _defined_project(auth_client, org_id, "NoDomain", mutate=unknown)
    tpl = (await auth_client.post(f"/api/projects/{src['id']}/templates", json={})).json()
    assert tpl["category"] == ""
    # One saved before this rule is shown without it too.
    meta = templates.get(tpl["id"])
    meta["category"] = "unknown"
    (templates.templates_root() / tpl["id"] / "meta.json").write_text(json.dumps(meta))
    assert (await auth_client.get(f"/api/project-templates/{tpl['id']}")).json()["category"] == ""


async def _member(org_id: str, email: str, name: str, role: str) -> AsyncClient:
    import uuid as _uuid

    from database import async_session
    from models.org import InviteStatus, OrgMember, OrgMemberRole
    c = await _person(email, name)
    me = (await c.get("/api/auth/me")).json()
    async with async_session() as db:
        db.add(OrgMember(org_id=_uuid.UUID(org_id), user_id=_uuid.UUID(me["id"]),
                         role=OrgMemberRole(role), invite_status=InviteStatus.accepted))
        await db.commit()
    return c


@pytest.mark.asyncio
async def test_whoever_raised_the_request_is_told_as_well_as_the_builder(
        auth_client, org_id, super_admin_client, mailbox):
    """An admin of the organisation may submit a colleague's template: both
    the person who asked and the builder hear the decision."""
    _src, tpl = await _ready_template(auth_client, org_id)
    boss = await _member(org_id, "boss@example.com", "Bea Boss", "admin")
    try:
        assert (await boss.post(f"/api/project-templates/{tpl['id']}/submit", json={})).status_code == 200
        hist = (await auth_client.get(f"/api/project-templates/{tpl['id']}/detail")).json()["history"]
        assert hist[0]["by"] == "Bea Boss"
        await super_admin_client.post(f"/api/admin/template-requests/{tpl['id']}/decision",
                                      json={"decision": "reject", "note": "Needs a clearer cover."})
        told = sorted(to for to, t, _ in mailbox if t == "template_changes_requested")
        assert told == ["boss@example.com", "test@example.com"]
        for c in (boss, auth_client):
            assert any(n["type"] == "template_changes_requested" for n in await _notifications(c))
    finally:
        await boss.aclose()


@pytest.mark.asyncio
async def test_tentoro_can_take_a_review_down_and_says_why(auth_client, org_id, super_admin_client):
    _src, tpl = await _ready_template(auth_client, org_id)
    await auth_client.post(f"/api/project-templates/{tpl['id']}/submit", json={})
    await super_admin_client.post(f"/api/admin/template-requests/{tpl['id']}/decision", json={"decision": "approve"})
    troll = await _person("troll@example.com", "Troll")
    try:
        # Only someone who used it may rate it.
        troll_org = await _org(troll, "trolls")
        assert (await troll.post(f"/api/orgs/{troll_org}/projects/from-project-template",
                                 json={"template_id": tpl["id"], "name": "Ours"})).status_code == 201
        await troll.put(f"/api/project-templates/{tpl['id']}/reviews/mine", json={"rating": 1, "comment": "spam spam"})
        review = (await troll.get(f"/api/project-templates/{tpl['id']}/reviews")).json()["reviews"][0]
        url = f"/api/admin/template-reviews/{review['id']}/remove"
        # Not the builder's, not the reviewer's own way out, and never without a reason.
        assert (await auth_client.post(url, json={"reason": "I dislike it"})).status_code == 403
        assert (await super_admin_client.post(url, json={"reason": ""})).status_code == 422
        assert (await super_admin_client.post(url, json={"reason": "Spam, not a review."})).status_code == 200
        assert (await super_admin_client.post(url, json={"reason": "again"})).status_code == 404
        card = (await troll.get(f"/api/project-templates/{tpl['id']}")).json()
        assert card["ratings"] == 0 and card["rating"] is None
        note = next(n for n in await _notifications(troll) if n["type"] == "template_review_removed")
        assert "Spam, not a review." in note["content"]
        audit = (await super_admin_client.get("/api/admin/audit")).json()
        assert any(row["action"] == "template_review.removed" for row in audit)
        # They may write a fresh one.
        assert (await troll.put(f"/api/project-templates/{tpl['id']}/reviews/mine",
                                json={"rating": 3})).status_code == 200
    finally:
        await troll.aclose()


@pytest.mark.asyncio
async def test_a_screenshot_says_what_it_shows_until_approved(auth_client, org_id, super_admin_client):
    _src, tpl = await _ready_template(auth_client, org_id)
    shot = templates.get(tpl["id"])["screenshots"][0]["id"]
    url = f"/api/project-templates/{tpl['id']}/screenshots/{shot}"
    r = await auth_client.patch(url, json={"caption": "  The pipeline board  "})
    assert r.status_code == 200 and r.json()["caption"] == "The pipeline board"
    assert (await auth_client.patch(url, json={"caption": "x" * 201})).status_code == 422
    assert (await auth_client.patch(f"/api/project-templates/{tpl['id']}/screenshots/{'0' * 32}",
                                    json={"caption": "x"})).status_code == 404
    await auth_client.post(f"/api/project-templates/{tpl['id']}/submit", json={})
    assert (await super_admin_client.get("/api/admin/template-requests/count")).json() == {"pending": 1}
    assert (await auth_client.get("/api/admin/template-requests/count")).status_code == 403
    await super_admin_client.post(f"/api/admin/template-requests/{tpl['id']}/decision", json={"decision": "approve"})
    assert (await super_admin_client.get("/api/admin/template-requests/count")).json() == {"pending": 0}
    assert (await auth_client.patch(url, json={"caption": "changed after approval"})).status_code == 409


@pytest.mark.asyncio
async def test_a_disabled_admin_is_not_written_to_and_no_admin_is_said_loudly(
        auth_client, org_id, client, mailbox, monkeypatch, caplog):
    from datetime import datetime, timezone

    from sqlalchemy import update

    from database import async_session
    from models.auth import PlatformUser
    monkeypatch.setenv("FORGE_SUPER_ADMIN_EMAILS", "gone@tentoro.ai, here@tentoro.ai")
    for email in ("gone@tentoro.ai", "here@tentoro.ai"):
        await client.post("/api/auth/signup", json={"email": email, "name": "A", "password": "Testpass123"})
    async with async_session() as db:
        await db.execute(update(PlatformUser).where(PlatformUser.email == "gone@tentoro.ai")
                         .values(disabled_at=datetime.now(timezone.utc)))
        await db.commit()
    _src, tpl = await _ready_template(auth_client, org_id)
    assert (await auth_client.post(f"/api/project-templates/{tpl['id']}/submit", json={})).status_code == 200
    assert [to for to, t, _ in mailbox if t == "template_review_requested"] == ["here@tentoro.ai"]

    # Nobody configured and nobody holding the role: kept, queued, and logged as an error.
    monkeypatch.setenv("FORGE_SUPER_ADMIN_EMAILS", "")
    async with async_session() as db:
        await db.execute(update(PlatformUser).values(platform_role=None))
        await db.commit()
    _src2, tpl2 = await _ready_template(auth_client, org_id, name="Second")
    with caplog.at_level("ERROR"):
        assert (await auth_client.post(f"/api/project-templates/{tpl2['id']}/submit", json={})).status_code == 200
    assert any("no Tentoro admin is configured" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_a_template_whose_files_are_gone_is_nowhere_and_never_counted(
        auth_client, org_id, super_admin_client):
    import shutil
    _src, tpl = await _ready_template(auth_client, org_id)
    await auth_client.post(f"/api/project-templates/{tpl['id']}/submit", json={})
    assert (await super_admin_client.get("/api/admin/template-requests/count")).json() == {"pending": 1}
    shutil.rmtree(templates.templates_root() / tpl["id"])  # a disk restored without it, say
    assert (await super_admin_client.get("/api/admin/template-requests/count")).json() == {"pending": 0}
    queue = (await super_admin_client.get("/api/admin/template-requests")).json()
    assert queue["requests"] == [] and queue["counts"]["pending"] == 0
    for path in (f"/api/project-templates/{tpl['id']}", f"/api/project-templates/{tpl['id']}/detail"):
        assert (await super_admin_client.get(path)).status_code == 404
    r = await super_admin_client.post(f"/api/admin/template-requests/{tpl['id']}/decision", json={"decision": "approve"})
    assert r.status_code == 404
    assert (await auth_client.get(f"/api/orgs/{org_id}/project-templates")).json()["templates"] == []


@pytest.mark.asyncio
async def test_oversized_words_are_refused_not_cut(auth_client, org_id, super_admin_client):
    src = await _defined_project(auth_client, org_id, "Long")
    url = f"/api/projects/{src['id']}/templates"
    assert (await auth_client.post(url, json={"name": "x" * 121})).status_code == 422
    assert (await auth_client.post(url, json={"description": "x" * 2001})).status_code == 422
    assert (await auth_client.post(url, json={"category": "x" * 61})).status_code == 422
    _src, tpl = await _ready_template(auth_client, org_id)
    await auth_client.post(f"/api/project-templates/{tpl['id']}/submit", json={})
    r = await super_admin_client.post(f"/api/admin/template-requests/{tpl['id']}/decision",
                                      json={"decision": "reject", "note": "x" * 2001})
    assert r.status_code == 422
    r = await super_admin_client.post(f"/api/admin/template-requests/{tpl['id']}/decision",
                                      json={"decision": "publish-everything"})
    assert r.status_code == 422
    assert (await auth_client.get(f"/api/project-templates/{tpl['id']}")).json()["status"] == "pending"


@pytest.mark.asyncio
async def test_one_request_per_app_the_newest_version(auth_client, org_id, super_admin_client):
    builder, admin = auth_client, super_admin_client
    src, v1 = await _ready_template(builder, org_id)

    async def new_version() -> dict:
        v = (await builder.post(f"/api/projects/{src['id']}/templates",
                                json={"name": "Hiring desk", "description": GOOD_DESCRIPTION})).json()
        await builder.post(f"/api/project-templates/{v['id']}/screenshots", files={"file": ("s.png", _png(), "image/png")})
        return v

    v2 = await new_version()
    assert (await builder.post(f"/api/project-templates/{v1['id']}/submit", json={})).status_code == 200
    # The newer one takes the older request's place: one request in the queue.
    assert (await builder.post(f"/api/project-templates/{v2['id']}/submit", json={})).status_code == 200
    assert (await builder.get(f"/api/project-templates/{v1['id']}")).json()["status"] == "draft"
    queue = (await admin.get("/api/admin/template-requests?status=pending")).json()
    queue = queue.get("requests", queue.get("templates", queue)) if isinstance(queue, dict) else queue
    assert [t["id"] for t in queue if t["id"] in (v1["id"], v2["id"])] == [v2["id"]]
    # An older version cannot be sent while a newer one waits, or once it is live.
    r = await builder.post(f"/api/project-templates/{v1['id']}/submit", json={})
    assert r.status_code == 409 and "Version 2" in r.text and "waiting for review" in r.text
    await admin.post(f"/api/admin/template-requests/{v2['id']}/decision", json={"decision": "approve"})
    r = await builder.post(f"/api/project-templates/{v1['id']}/submit", json={})
    assert r.status_code == 409 and "in the Gallery" in r.text


@pytest.mark.asyncio
async def test_tentoros_admins_judge_the_gallery_and_do_not_rate_it(auth_client, org_id, super_admin_client):
    builder, admin = auth_client, super_admin_client
    _, tpl = await _ready_template(builder, org_id)
    await builder.post(f"/api/project-templates/{tpl['id']}/submit", json={})
    await admin.post(f"/api/admin/template-requests/{tpl['id']}/decision", json={"decision": "approve"})
    assert (await admin.get(f"/api/project-templates/{tpl['id']}")).json()["can_rate"] is False
    r = await admin.put(f"/api/project-templates/{tpl['id']}/reviews/mine", json={"rating": 5})
    assert r.status_code == 403 and "do not rate" in r.text
