"""F&B (forge-v3 fxa532bj, 2026-10-01): an administrator who signed in landed
on the customers' menu at `/` — outside the frame that carries the notification
bell — so "admin notifications are not seen". The Blueprint did say where an
admin starts (`initialRoute: {"ROLE-001": "/admin/categories"}`), keyed by the
role's id; only role names were matched, and the sign-in form sent everyone
HOME regardless."""
from __future__ import annotations

from pathlib import Path

from services.blueprint.account_model import landing_by_role, project_account

DOC = {"roles": [{"id": "ROLE-001", "name": "Admin"}, {"id": "ROLE-002", "name": "Customer"}],
       "navigation": {"initialRoute": {"ROLE-001": "/admin/categories", "ROLE-002": "/",
                                       "default": "/", "nobody": "/x"}},
       "data": {"entities": []}}
SDK = Path(__file__).resolve().parents[2] / "templates/app-foundation/src/sdk"


def test_a_landing_keyed_by_role_id_or_name_is_kept_by_name():
    assert landing_by_role(DOC) == {"Admin": "/admin/categories", "Customer": "/"}
    by_name = {**DOC, "navigation": {"initialRoute": {"admin": "/admin", "Customer": "/menu"}}}
    assert landing_by_role(by_name) == {"Admin": "/admin", "Customer": "/menu"}
    dynamic = {**DOC, "navigation": {"initialRoute": {"ROLE-001": "/orders/[id]"}}}
    assert landing_by_role(dynamic) == {}


def test_the_app_is_told_each_roles_landing(tmp_path):
    project_account(DOC, tmp_path)
    account = (tmp_path / "src/lib/account.ts").read_text()
    assert 'export const LANDING_FOR: Record<string, string> = {\n  "Admin": "/admin/categories",' in account


def test_signing_in_goes_to_the_roles_page_and_old_apps_still_compile():
    auth = (SDK / "auth.tsx").read_text()
    assert 'import * as accountModule from "@/lib/account";' in auth
    assert "to = (role && LANDING_FOR[role]) || HOME;" in auth
    # An explicit return address still wins.
    assert 'let to = search?.get("callbackUrl") || "";' in auth


def test_the_nav_flow_map_comes_from_the_same_place():
    import inspect
    from services.blueprint import projection
    assert "initial_for = landing_by_role(doc)" in inspect.getsource(projection)
