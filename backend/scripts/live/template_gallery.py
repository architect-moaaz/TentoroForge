"""Live check: the Templates Gallery, end to end, against a running Forge.

Run:  backend/.venv/bin/python backend/scripts/live/template_gallery.py [--races]

Three people: the builder (dev.tester, Forge Dev Org), Tentoro's admin
(admin@tentoro.ai) and a visitor from another organisation. Each line names
the ask it proves (1-8). `--races` adds the two-people-at-once probe. What it
makes is removed at the end, except one approved Task Board version.
"""
from __future__ import annotations

import asyncio
import sys
from collections import Counter

from _live import (API, DSN, admin, builder_token, check, client, done, login, png,  # noqa: F401
                   visitor)

TASK_BOARD = "46c361ff-6688-4ed2-9881-880c41150f5c"   # Task Board, Forge Dev Org
DESC = "A shared task board for small teams: plan work in columns, assign owners and track due dates."


def journey() -> None:
    tok, _org = builder_token()
    B, A, V = client(tok), admin(), visitor()
    v_org = V.get("/api/auth/me").json()["orgs"][0]["org_id"]
    a_org = A.get("/api/auth/me").json()["orgs"][0]["org_id"]
    unread = lambda c: c.get("/api/notifications/count").json()["unread_count"]  # noqa: E731

    r = B.post(f"/api/projects/{TASK_BOARD}/templates", json={"name": "Task Board", "description": DESC, "category": "Productivity"})
    check(r.status_code == 201, "1  save -> 201")
    t = r.json(); tid = t["id"]
    check(t["status"] == "draft" and t["family"], f"1  a private draft of the app's family, v{t['version']}")
    check(V.get(f"/api/project-templates/{tid}").status_code == 404, "1  another organisation cannot see a draft")
    c = B.get(f"/api/project-templates/{tid}/checks").json()
    check(not c["ready"] and any(x["key"] == "screenshots" and not x["ok"] for x in c["checks"]), "4  checks: a screenshot is missing")
    check(B.post(f"/api/project-templates/{tid}/submit", json={}).status_code == 422, "4  submit without screenshots refused")
    added = B.post(f"/api/project-templates/{tid}/screenshots/from-app").json()["added"]
    check(len(added) >= 1, f"4  added {len(added)} of the app's own screens")
    check(B.post(f"/api/project-templates/{tid}/screenshots", files={"file": ("hero.png", png(), "image/png")}).status_code == 201, "4  upload a real PNG")
    check(B.post(f"/api/project-templates/{tid}/screenshots", files={"file": ("x.png", b"<svg onload=alert(1)>", "image/png")}).status_code == 400, "4  a fake 'png' refused")
    shot = B.get(f"/api/project-templates/{tid}").json()["screenshots"][0]["id"]
    check(B.patch(f"/api/project-templates/{tid}/screenshots/{shot}", json={"caption": "The board"}).json()["caption"] == "The board", "4  caption a screenshot")
    check(B.post(f"/api/project-templates/{tid}/submit", json={"pricing_model": "paid", "price_cents": 900, "currency": "USD"}).status_code == 400, "4  paid refused: coming soon")
    check(B.get(f"/api/project-templates/{tid}/checks").json()["ready"], "4  checks pass")
    before = unread(A)
    r = B.post(f"/api/project-templates/{tid}/submit", json={"pricing_model": "free"})
    check(r.status_code == 200 and r.json()["status"] == "pending", "1  submitted -> pending")
    check(unread(A) == before + 1, "3  admin@tentoro.ai has a new notification")
    n = A.get("/api/notifications?limit=5").json()[0]
    check(n["type"] == "template_review_requested" and n["link"] == f"/admin/templates?request={tid}", "3  it links to the review")
    check(A.get("/api/admin/template-requests/count").json()["pending"] >= 1, "3  the cockpit's badge counts it")
    check(B.post(f"/api/project-templates/{tid}/submit", json={}).status_code == 409, "1  submitting twice refused")
    check(all(x["id"] != tid for x in V.get("/api/template-gallery").json()["templates"]), "5  not in the Gallery while pending")
    check(B.get("/api/admin/template-requests").status_code == 403, "4  the builder cannot open the review queue")
    d = A.get(f"/api/project-templates/{tid}/detail").json()
    check(d["is_admin"] and d["preview"]["screens"] and d["preview"]["records"] and d["preview"]["workflows"], "4  admin sees screens, data models, workflows")
    check(A.get(f"/api/project-templates/{tid}/screenshots/{shot}").status_code == 200, "4  admin sees the screenshots")
    check(V.get(f"/api/project-templates/{tid}/screenshots/{shot}").status_code == 404, "1  others cannot see a pending screenshot")
    check(A.post(f"/api/orgs/{a_org}/projects/from-project-template", json={"template_id": tid, "name": "Review copy"}).status_code == 201, "4  admin opens a test copy")
    check(B.get(f"/api/project-templates/{tid}").json()["uses"] == t["uses"], "6  a review copy is not a use")
    b0 = unread(B)
    check(A.post(f"/api/admin/template-requests/{tid}/decision", json={"decision": "reject"}).status_code == 400, "4  changes need a note")
    check(A.post(f"/api/admin/template-requests/{tid}/decision", json={"decision": "reject", "note": "Add the board view."}).json()["status"] == "rejected", "4  admin asks for changes")
    check(unread(B) == b0 + 1, "2  the builder is notified")
    d = B.get(f"/api/project-templates/{tid}/detail").json()
    check(d["review_note"] == "Add the board view." and [h["status"] for h in d["history"]] == ["pending", "rejected"], "2  the builder sees the reason and the history")
    check(B.post(f"/api/project-templates/{tid}/submit", json={}).json()["status"] == "pending", "2  resubmitted")
    check(A.post(f"/api/admin/template-requests/{tid}/decision", json={"decision": "approve", "note": "Great."}).json()["status"] == "approved", "5  admin approves")
    check(B.patch(f"/api/project-templates/{tid}", json={"name": "Hacked"}).status_code == 409, "5  approved content is locked")
    card = next(x for x in V.get("/api/template-gallery").json()["templates"] if x["id"] == tid)
    check(card["creator"]["name"] == "Dev Tester" and card["org_name"] == "Forge Dev Org" and card["created_at"] and card["version"] == t["version"], "5  card: who built it, when, version")
    check(card["source_project_id"] is None and card["review_note"] == "" and "lineage" not in card, "5  card hides private fields")
    d = V.get(f"/api/project-templates/{tid}/detail").json()
    check("checks" not in d and d["preview"]["records"][0]["fields"] and d["screenshots"][0]["caption"] == "The board", "5  detail: data models with fields, captions; no checks")
    uses0 = card["uses"]
    check(V.post(f"/api/orgs/{v_org}/projects/from-project-template", json={"template_id": tid, "name": "Our board"}).status_code == 201, "6  another organisation uses it")
    check(V.get(f"/api/project-templates/{tid}").json()["uses"] == uses0 + 1, f"6  uses {uses0} -> {uses0 + 1}")
    check(V.put(f"/api/project-templates/{tid}/reviews/mine", json={"rating": True}).status_code == 422, "8  rating 'true' refused")
    r = V.put(f"/api/project-templates/{tid}/reviews/mine", json={"rating": 5, "comment": "Set up in minutes."})
    check(r.status_code == 200, f"8  the visitor rates it -> avg {r.json()['rating']}")
    check(B.put(f"/api/project-templates/{tid}/reviews/mine", json={"rating": 5}).status_code == 403, "8  the builder's organisation cannot rate it")
    rv = B.get(f"/api/project-templates/{tid}/reviews").json()["reviews"]
    check(any(x["used_it"] and x["user"]["name"] == "Vera Visitor" for x in rv), "8  the review shows 'Used this template'")
    p = V.get(f"/api/template-creators/{card['creator']['id']}").json()
    check(p["totals"]["templates"] >= 1 and "Forge Dev Org" in p["organisations"] and "email" not in p, "7  builder profile, no email")
    check(B.get(f"/api/template-creators/{V.get('/api/auth/me').json()['id']}").status_code == 404, "7  no profile for someone with nothing published")
    t2 = B.post(f"/api/projects/{TASK_BOARD}/templates", json={"name": "Task Board", "description": DESC, "category": "Productivity"}).json()
    check(t2["version"] > t["version"] and t2["family"] == t["family"], f"5  saving again makes v{t2['version']}, same family")
    B.post(f"/api/project-templates/{t2['id']}/screenshots/from-app")
    B.post(f"/api/project-templates/{t2['id']}/submit", json={})
    A.post(f"/api/admin/template-requests/{t2['id']}/decision", json={"decision": "approve"})
    ids = [x["id"] for x in V.get("/api/template-gallery").json()["templates"]]
    check(t2["id"] in ids and tid not in ids, "5  the Gallery shows the new version only")
    check(B.get(f"/api/project-templates/{tid}").json()["status"] == "superseded", "5  the old version is superseded")
    check(A.put(f"/api/project-templates/{t2['id']}/reviews/mine", json={"rating": 5}).status_code == 403,
          "8  Tentoro's admins judge the Gallery and do not rate it")
    # One request per app: a newer version takes an older request's place; an older one is not sent.
    t3 = B.post(f"/api/projects/{TASK_BOARD}/templates", json={"name": "Task Board", "description": DESC, "category": "Productivity"}).json()
    t4 = B.post(f"/api/projects/{TASK_BOARD}/templates", json={"name": "Task Board", "description": DESC, "category": "Productivity"}).json()
    for x in (t3, t4):
        B.post(f"/api/project-templates/{x['id']}/screenshots/from-app")
    check(B.post(f"/api/project-templates/{t3['id']}/submit", json={}).status_code == 200, "1  v-next submitted")
    check(B.post(f"/api/project-templates/{t4['id']}/submit", json={}).status_code == 200
          and B.get(f"/api/project-templates/{t3['id']}").json()["status"] == "draft",
          "1  a newer version takes the older request's place")
    r = B.post(f"/api/project-templates/{t3['id']}/submit", json={})
    check(r.status_code == 409 and "older version" in r.text, "1  an older version is not sent while a newer one waits")
    A.post(f"/api/admin/template-requests/{t4['id']}/decision", json={"decision": "approve"})
    for x in (t3,):
        B.delete(f"/api/project-templates/{x['id']}")


async def races(tok: str) -> None:
    import asyncpg
    import httpx

    mk = lambda t: httpx.AsyncClient(base_url=API, timeout=120, headers={"Authorization": f"Bearer {t}"})  # noqa: E731
    B = mk(tok)
    A = mk(login("TEMPLATE_GALLERY_ADMIN", "admin@tentoro.ai"))
    V = mk(login("TEMPLATE_GALLERY_VISITOR", "visitor@example.com"))
    c = await asyncpg.connect(DSN)
    made = []
    try:
        desc = "A board used to probe two people acting on one template at the same moment."
        t = (await B.post(f"/api/projects/{TASK_BOARD}/templates", json={"name": "Race board", "description": desc})).json()
        tid = t["id"]; made.append(tid)
        await B.post(f"/api/project-templates/{tid}/screenshots/from-app"); await asyncio.sleep(1.5)
        rs = await asyncio.gather(*[B.post(f"/api/project-templates/{tid}/submit", json={}) for _ in range(6)])
        k = Counter(r.status_code for r in rs)
        check(k.get(200) == 1 and not k.get(500), f"R  six submits at once: one wins {dict(k)}")
        await asyncio.sleep(2)
        rs = await asyncio.gather(*([A.post(f"/api/admin/template-requests/{tid}/decision", json={"decision": "approve"}) for _ in range(3)] +
                                    [A.post(f"/api/admin/template-requests/{tid}/decision", json={"decision": "reject", "note": "x"}) for _ in range(3)]))
        k = Counter(r.status_code for r in rs)
        ev = [e["status"] for e in await c.fetch("select status from template_events where template_id=$1 order by created_at", tid)]
        check(k.get(200) == 1 and not k.get(500) and len(ev) == 2, f"R  six decisions at once: one wins {dict(k)} {ev}")
        if ev[-1] == "rejected":
            await B.post(f"/api/project-templates/{tid}/submit", json={}); await asyncio.sleep(0.6)
            await A.post(f"/api/admin/template-requests/{tid}/decision", json={"decision": "approve"})
        await asyncio.sleep(2)
        rs = await asyncio.gather(*[V.put(f"/api/project-templates/{tid}/reviews/mine", json={"rating": 4, "comment": f"r{i}"}) for i in range(6)])
        k = Counter(r.status_code for r in rs)
        n = await c.fetchval("select count(*) from template_reviews where template_id=$1", tid)
        check(not k.get(500) and n == 1, f"R  six ratings at once: one review {dict(k)}")
        await asyncio.sleep(2)
        vs = []
        for _ in range(2):
            t2 = (await B.post(f"/api/projects/{TASK_BOARD}/templates", json={"name": "Race board", "description": desc})).json()
            made.append(t2["id"]); vs.append(t2["id"])
            await B.post(f"/api/project-templates/{t2['id']}/screenshots/from-app")
            await B.post(f"/api/project-templates/{t2['id']}/submit", json={}); await asyncio.sleep(1)
        rs = await asyncio.gather(*[A.post(f"/api/admin/template-requests/{v}/decision", json={"decision": "approve"}) for v in vs])
        lineage = await c.fetchval("select lineage from template_listings where template_id=$1", vs[0])
        live = await c.fetch("select template_id from template_listings where lineage=$1 and status='approved'", lineage)
        check(not any(r.status_code == 500 for r in rs) and len(live) == 1, "R  two versions approved at once: one stays live")
    finally:
        for tid in made:  # the probe's own templates go; the Gallery keeps a clean Task Board
            await B.delete(f"/api/project-templates/{tid}"); await asyncio.sleep(0.6)
        await c.close()
        for x in (A, B, V):
            await x.aclose()


def republish_clean_task_board() -> None:
    """After the probe, one tidy Task Board version is what the Gallery shows."""
    tok, _org = builder_token()
    B, A = client(tok), admin()
    t = B.post(f"/api/projects/{TASK_BOARD}/templates", json={"name": "Task Board", "description": DESC, "category": "Productivity"}).json()
    B.post(f"/api/project-templates/{t['id']}/screenshots/from-app")
    B.post(f"/api/project-templates/{t['id']}/submit", json={})
    A.post(f"/api/admin/template-requests/{t['id']}/decision", json={"decision": "approve", "note": "Demo version."})


if __name__ == "__main__":
    journey()
    if "--races" in sys.argv:
        asyncio.run(races(builder_token()[0]))
        republish_clean_task_board()
    done()
