"""Several organisations, side by side — proven on a running copy.

Signing up with an organisation makes it, its first membership and the
active one; an invite into an organisation joins it in the role it was sent
for; switching changes what is seen; a stranger's organisation is refused.
Each is tried through the app's own routes, as a person would, on the copy.
Nothing to prove when the application serves one.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Callable

from services.blueprint.scorecard import item

logger = logging.getLogger(__name__)


def _rows(app: Any, sql: str) -> list[list[str]]:
    from services.blueprint.page_review import _query
    return _query(app, sql)


def _q(s: Any) -> str:
    return str(s).replace("'", "''")


def _call(app: Any, method: str, path: str, body: Any, cookies: list[dict]) -> tuple[int, dict]:
    from services.smith.trials import _http
    status, _loc, text = _http(app, method, path, body, cookies)
    try:
        parsed = json.loads(text) if text else {}
    except ValueError:
        parsed = {}
    return int(status), parsed if isinstance(parsed, dict) else {}


def check_tenancy(app: Any, doc: dict, *, cancelled: Callable[[], bool] = lambda: False) -> dict:
    from services.blueprint.projection import tenancy_policy
    from services.smith.trials import _session
    pol = tenancy_policy(doc)
    if pol["kind"] != "organisation":
        return {"total": 0, "green": [], "red": [], "untried": []}
    green: list[dict] = []
    red: list[dict] = []
    untried: list[dict] = []
    it = lambda what, why: item(f"tenancy::{what}", "Organisations", why, "tenancy")  # noqa: E731
    if cancelled():
        return {"total": 1, "green": [], "red": [], "untried": [it("signup", "stopped by the person")]}
    table, name_col = pol["table"], pol["nameColumn"] or "name"
    # 1. Signup with an organisation.
    if pol["signup"] != "joins_by_invite":
        tag = uuid.uuid4().hex[:8]
        status, body = _call(app, "POST", "/api/auth/signup", {"name": "Check Person", "email": f"check-{tag}@example.com",
                                                               "password": "Checkpass123", "organisation": {"name": f"Check Org {tag}"}}, [])
        if status >= 400:
            red.append(it("signup", f"signing up with an organisation was answered {status}: {str(body.get('error') or '')[:120]}"))
        else:
            org = _rows(app, f"select id::text from \"{table}\" where \"{name_col}\" = 'Check Org {tag}'")
            mem = _rows(app, f"select m.role from forge_memberships m join users u on u.id::text = m.user_id "
                             f"where u.email = 'check-{tag}@example.com'")
            active = _rows(app, f"select coalesce(active_org_id, '') from users where email = 'check-{tag}@example.com'")
            if org and mem and active and active[0] and org[0] and active[0][0] == org[0][0]:
                green.append(it("signup", "a signup makes the organisation, its first membership and the active one"))
            else:
                red.append(it("signup", "a signup did not make the organisation, the membership and the active one together"))
    # 2. Invite into an organisation, as an organisation admin (or a platform role).
    admin_role = pol["adminRole"] or (pol["platformRoles"][0] if pol["platformRoles"] else None)
    if admin_role:
        try:
            _who, jar = _session(app, doc, admin_role)
            tag = uuid.uuid4().hex[:8]
            role = pol["memberRoles"][0] if pol["memberRoles"] else "member"
            status, body = _call(app, "POST", "/api/org/members", {"email": f"invited-{tag}@example.com", "role": role}, jar)
            if status == 409:
                untried.append(it("invite", f"the {admin_role} login on the copy is in no organisation"))
            elif status >= 400:
                red.append(it("invite", f"an invite was answered {status}: {str(body.get('error') or '')[:120]}"))
            else:
                inv = _rows(app, f"select coalesce(org_id, ''), coalesce(role, '') from forge_invites where email = 'invited-{tag}@example.com'")
                if inv and inv[0] and inv[0][0] and inv[0][1] == role:
                    green.append(it("invite", f"an invite carries the organisation and the role ({role}) the membership is made in"))
                else:
                    red.append(it("invite", "an invite did not record the organisation and role it was sent for"))
        except Exception as exc:  # noqa: BLE001
            untried.append(it("invite", f"could not sign in as {admin_role}: {str(exc)[:120]}"))
    # 3. Switching changes what is seen, for a member of two organisations; a stranger's is refused.
    member_role = pol["memberRoles"][0] if pol["memberRoles"] else None
    two = _rows(app, f"select id::text from \"{table}\" order by 1 limit 2") if table else []
    if member_role and len(two) == 2:
        person = _rows(app, f"select u.id::text, u.email from users u join forge_memberships m on m.user_id = u.id::text "
                            f"where m.role = '{_q(member_role)}' and m.status = 'active' limit 1")
        if person and person[0]:
            uid = person[0][0]
            _rows(app, f"insert into forge_memberships (user_id, org_id, role, status) values ('{_q(uid)}', '{_q(two[1][0])}', "
                       f"'{_q(member_role)}', 'active') on conflict (user_id, org_id) do nothing")
            try:
                from services.preview_session import Session, cookies
                jar = cookies(Session(sub=uid, name="Member", email=person[0][1], role=member_role, active_org_id=two[0][0]), base_url=app.base)
                status, body = _call(app, "POST", "/api/org", {"orgId": two[1][0]}, jar)
                now = _rows(app, f"select coalesce(active_org_id, '') from users where id::text = '{_q(uid)}'")
                if status == 200 and now and now[0] and now[0][0] == two[1][0]:
                    green.append(it("switch", "a member of two organisations switches, and the active one follows"))
                else:
                    red.append(it("switch", f"switching organisation was answered {status} or did not change the active one"))
                status, _b = _call(app, "POST", "/api/org", {"orgId": "00000000-0000-0000-0000-000000000000"}, jar)
                (green if status == 403 else red).append(it("stranger", "an organisation the person does not belong to is refused"
                                                            if status == 403 else f"switching into a stranger's organisation was answered {status}"))
            except Exception as exc:  # noqa: BLE001
                untried.append(it("switch", f"could not act as a member: {str(exc)[:120]}"))
        else:
            untried.append(it("switch", f"no {member_role} with a membership on the copy"))
    else:
        untried.append(it("switch", "fewer than two organisations on the copy to switch between"))
    return {"total": len(green) + len(red) + len(untried), "green": green, "red": red, "untried": untried}


__all__ = ["check_tenancy"]
