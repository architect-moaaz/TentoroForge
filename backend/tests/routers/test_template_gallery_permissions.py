"""Who may do what to a template — every route, every kind of person.

The Gallery mixes three audiences on one set of routes: the template's own
organisation (its builder, its admins, its other members), Tentoro's admins,
and everyone else. A wrong answer in either direction is a bug: a private
template shown to another organisation, a member deleting a colleague's
template, an admin decision made under someone else's name. So each route is
asked by each kind of person, while the template is waiting for review and
again once it is in the Gallery, and the answer each must get is written out.

  builder    made the template (and owns the organisation)
  org_admin  an admin of the same organisation, not the builder
  member     a plain member of the same organisation
  outsider   signed in, another organisation
  tentoro    a Tentoro admin (admin@tentoro.ai)
  imperson   a Tentoro admin impersonating the outsider — the outsider's rights, never an admin's
  anon       not signed in
"""
from __future__ import annotations

import io
import json
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from main import app

FIXTURE = Path(__file__).resolve().parents[2] / "fleet" / "blueprints" / "ats-live.json"
DESCRIPTION = "Track candidates from application to offer, with interviews and scorecards."
PEOPLE = ("builder", "org_admin", "member", "outsider", "tentoro", "imperson", "anon")


def _png() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


async def _signup(email: str, name: str) -> tuple[AsyncClient, str]:
    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    r = await c.post("/api/auth/signup", json={"email": email, "name": name, "password": "Testpass123"})
    assert r.status_code == 201, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    me = (await c.get("/api/auth/me")).json()
    return c, me["id"]


async def _join(org_id: str, user_id: str, role: str) -> None:
    from database import async_session
    from models.org import InviteStatus, OrgMember, OrgMemberRole
    async with async_session() as db:
        db.add(OrgMember(org_id=uuid.UUID(org_id), user_id=uuid.UUID(user_id),
                         role=OrgMemberRole(role), invite_status=InviteStatus.accepted))
        await db.commit()


@pytest_asyncio.fixture
async def cast(auth_client, org_id, super_admin_client):
    """Everyone, and a template waiting for review."""
    from services.project_service import OUTPUT_BASE
    builder = auth_client
    res = await builder.post(f"/api/orgs/{org_id}/projects", json={"name": "Hiring"})
    project = res.json()
    out = Path(OUTPUT_BASE) / project["short_id"]
    (out / ".forge" / "blueprint").mkdir(parents=True, exist_ok=True)
    (out / ".forge" / "blueprint" / "current.json").write_text(FIXTURE.read_text())
    tpl = (await builder.post(f"/api/projects/{project['id']}/templates",
                              json={"name": "Hiring desk", "description": DESCRIPTION})).json()
    shot = (await builder.post(f"/api/project-templates/{tpl['id']}/screenshots",
                               files={"file": ("s.png", _png(), "image/png")})).json()
    assert (await builder.post(f"/api/project-templates/{tpl['id']}/submit", json={})).status_code == 200

    org_admin, oa_id = await _signup("orgadmin@example.com", "Olga Admin")
    member, m_id = await _signup("member@example.com", "Mo Member")
    await _join(org_id, oa_id, "admin")
    await _join(org_id, m_id, "member")
    outsider, o_id = await _signup("outsider@example.com", "Otto Outsider")
    own = (await outsider.post("/api/orgs", json={"name": "Elsewhere", "slug": "elsewhere"})).json()["id"]
    grant = (await super_admin_client.post(f"/api/admin/people/{o_id}/impersonate")).json()
    imperson = AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           headers={"Authorization": f"Bearer {grant['access_token']}"})
    anon = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    who = {"builder": builder, "org_admin": org_admin, "member": member, "outsider": outsider,
           "tentoro": super_admin_client, "imperson": imperson, "anon": anon}
    try:
        yield {"who": who, "tpl": tpl, "shot": shot["id"], "org": org_id, "other_org": own,
               "project": project}
    finally:
        for c in (org_admin, member, outsider, imperson, anon):
            await c.aclose()


def _expect(table: dict[str, int | tuple[int, ...]], person: str, got: int, what: str) -> None:
    want = table[person]
    ok = got in want if isinstance(want, tuple) else got == want
    assert ok, f"{what}: {person} got {got}, expected {want}"


@pytest.mark.asyncio
async def test_reading_a_template_waiting_for_review(cast):
    t, shot = cast["tpl"]["id"], cast["shot"]
    # Its organisation and Tentoro read it; everyone else is told it does not exist.
    seen = {"builder": 200, "org_admin": 200, "member": 200, "outsider": 404,
            "tentoro": 200, "imperson": 404, "anon": 401}
    for path in (f"/api/project-templates/{t}", f"/api/project-templates/{t}/detail",
                 f"/api/project-templates/{t}/reviews", f"/api/project-templates/{t}/screenshots/{shot}"):
        for person in PEOPLE:
            r = await cast["who"][person].get(path)
            _expect(seen, person, r.status_code, path)
    # The checks are the builder's and Tentoro's; a plain member sees the
    # template but not its review workings.
    checks = {"builder": 200, "org_admin": 200, "member": 403, "outsider": 404,
              "tentoro": 200, "imperson": 404, "anon": 401}
    for person in PEOPLE:
        r = await cast["who"][person].get(f"/api/project-templates/{t}/checks")
        _expect(checks, person, r.status_code, "checks")
    # The detail carries the history and checks only for those who may act on them.
    member_detail = (await cast["who"]["member"].get(f"/api/project-templates/{t}/detail")).json()
    assert "history" not in member_detail and "checks" not in member_detail
    assert member_detail["can_manage"] is False and member_detail["source_project_id"] is None
    assert (await cast["who"]["org_admin"].get(f"/api/project-templates/{t}/detail")).json()["can_manage"]


@pytest.mark.asyncio
async def test_changing_a_template_is_its_builders_or_its_org_admins(cast):
    t = cast["tpl"]["id"]
    manage = {"builder": 200, "org_admin": 200, "member": 403, "outsider": 404,
              "tentoro": 403, "imperson": 404, "anon": 401}
    for person in PEOPLE:
        r = await cast["who"][person].patch(f"/api/project-templates/{t}", json={"description": DESCRIPTION + " "})
        _expect(manage, person, r.status_code, "rename")
    upload = {**manage, "builder": 201, "org_admin": 201}
    for person in PEOPLE:
        r = await cast["who"][person].post(f"/api/project-templates/{t}/screenshots",
                                           files={"file": ("x.png", _png(), "image/png")})
        _expect(upload, person, r.status_code, "upload")
    order = {**manage}
    for person in PEOPLE:
        r = await cast["who"][person].put(f"/api/project-templates/{t}/screenshots/order", json={"order": []})
        _expect(order, person, r.status_code, "order")
    # Nobody outside the template's managers can take its request back or delete it.
    for person in ("member", "outsider", "tentoro", "imperson", "anon"):
        r = await cast["who"][person].post(f"/api/project-templates/{t}/cancel-request")
        assert r.status_code in (401, 403, 404), (person, r.status_code)
        r = await cast["who"][person].delete(f"/api/project-templates/{t}")
        assert r.status_code in (401, 403, 404), (person, r.status_code)
        r = await cast["who"][person].delete(f"/api/project-templates/{t}/screenshots/{cast['shot']}")
        assert r.status_code in (401, 403, 404), (person, r.status_code)
    assert (await cast["who"]["builder"].get(f"/api/project-templates/{t}")).json()["status"] == "pending"


@pytest.mark.asyncio
async def test_only_tentoro_in_its_own_name_decides(cast):
    t = cast["tpl"]["id"]
    queue = {"builder": 403, "org_admin": 403, "member": 403, "outsider": 403,
             "tentoro": 200, "imperson": 403, "anon": 401}
    for person in PEOPLE:
        r = await cast["who"][person].get("/api/admin/template-requests")
        _expect(queue, person, r.status_code, "queue")
    for person in ("builder", "org_admin", "member", "outsider", "imperson", "anon"):
        r = await cast["who"][person].post(f"/api/admin/template-requests/{t}/decision",
                                           json={"decision": "approve"})
        assert r.status_code in (401, 403), (person, r.status_code)
    assert (await cast["who"]["builder"].get(f"/api/project-templates/{t}")).json()["status"] == "pending"
    r = await cast["who"]["tentoro"].post(f"/api/admin/template-requests/{t}/decision",
                                          json={"decision": "approve"})
    assert r.status_code == 200 and r.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_once_approved_everyone_signed_in_may_see_use_and_rate(cast):
    t, shot = cast["tpl"]["id"], cast["shot"]
    await cast["who"]["tentoro"].post(f"/api/admin/template-requests/{t}/decision", json={"decision": "approve"})
    seen = {"builder": 200, "org_admin": 200, "member": 200, "outsider": 200,
            "tentoro": 200, "imperson": 200, "anon": 401}
    for path in (f"/api/project-templates/{t}", f"/api/project-templates/{t}/detail",
                 f"/api/project-templates/{t}/screenshots/{shot}", "/api/template-gallery"):
        for person in PEOPLE:
            _expect(seen, person, (await cast["who"][person].get(path)).status_code, path)
    # Rating: not the organisation that built it; anyone else signed in may.
    rate = {"builder": 403, "org_admin": 403, "member": 403, "outsider": 200,
            "tentoro": 200, "imperson": 200, "anon": 401}
    for person in PEOPLE:
        r = await cast["who"][person].put(f"/api/project-templates/{t}/reviews/mine", json={"rating": 4})
        _expect(rate, person, r.status_code, "rate")
    # Using it: into an organisation the person belongs to, never into someone else's.
    r = await cast["who"]["outsider"].post(f"/api/orgs/{cast['other_org']}/projects/from-project-template",
                                           json={"template_id": t, "name": "Ours"})
    assert r.status_code == 201
    r = await cast["who"]["outsider"].post(f"/api/orgs/{cast['org']}/projects/from-project-template",
                                           json={"template_id": t, "name": "Into theirs"})
    assert r.status_code == 403
    # Still the builder's to change, nobody else's — not even Tentoro's.
    for person in ("member", "outsider", "tentoro", "imperson"):
        r = await cast["who"][person].post(f"/api/project-templates/{t}/unpublish")
        assert r.status_code in (403, 404), (person, r.status_code)
    # The builder's profile is now public to the signed-in.
    builder_id = (await cast["who"]["builder"].get("/api/auth/me")).json()["id"]
    for person in PEOPLE:
        r = await cast["who"][person].get(f"/api/template-creators/{builder_id}")
        _expect(seen, person, r.status_code, "profile")


@pytest.mark.asyncio
async def test_an_impersonating_admin_is_the_person_and_nothing_more(cast):
    """Acting as the outsider, a Tentoro admin sees what the outsider sees —
    a pending template does not exist — and cannot decide, open a review copy
    or read the checks, though their own account could."""
    t = cast["tpl"]["id"]
    imp = cast["who"]["imperson"]
    detail = await imp.get(f"/api/project-templates/{t}/detail")
    assert detail.status_code == 404
    r = await imp.post(f"/api/orgs/{cast['other_org']}/projects/from-project-template",
                       json={"template_id": t, "name": "Sneaky review copy"})
    assert r.status_code == 404
    r = await imp.post(f"/api/admin/template-requests/{t}/decision", json={"decision": "approve"})
    assert r.status_code == 403
