"""F&B (fxa532bj, 2026-10-02): the build classified Admin and Customer and
then gave the owner no way to be a Customer — no login for one, and a person
who signed up held no role, so they saw no menu; two admin pages opened to
any signed-in customer; the menu handed Place Order a basket it never read;
the charts drew UUIDs and "true"/"false". Each is held here, at the part of
the generator that makes it, so a build — or Smith on an app built before —
gets it right without anybody stepping in.
"""
import json
import re
from pathlib import Path

import pytest

from services.blueprint import account_model as am
from services.blueprint.agent_contract import (
    AgentResult, ArtifactProposal, InconsistentPageAccess, access_findings, check_page_access,
)

_TEMPLATES = Path(__file__).resolve().parents[2] / "templates"


def _doc(**over):
    doc = {
        "security": {"authentication": "email_password"},
        "roles": [{"id": "ROLE-001", "name": "Admin"}, {"id": "ROLE-002", "name": "Customer"}],
        "modules": [{"id": "MOD-001", "name": "Back office"}, {"id": "MOD-002", "name": "Ordering"}],
        "data": {
            "entities": [
                {"id": "ENTITY-001", "name": "Category", "table": "categories", "labelField": "name",
                 "fields": [{"name": "id", "type": "uuid"}, {"name": "name", "type": "string"}]},
                {"id": "ENTITY-002", "name": "MenuItem", "table": "menu_items", "labelField": "name",
                 "fields": [{"name": "id", "type": "uuid"}, {"name": "name", "type": "string"},
                            {"name": "categoryId", "type": "uuid"}, {"name": "available", "type": "boolean"}]},
                {"id": "ENTITY-004", "name": "OrderItem", "table": "order_items", "labelField": "id",
                 "fields": [{"name": "id", "type": "uuid"}, {"name": "menuItemId", "type": "uuid"},
                            {"name": "lineId", "type": "uuid"}]},
            ],
            "relationships": [
                {"from": "ENTITY-002", "fromField": "categoryId", "to": "ENTITY-001", "toField": "id"},
                {"from": "ENTITY-004", "fromField": "menuItemId", "to": "ENTITY-002", "toField": "id"},
                # a target shown by its own id has no name to give
                {"from": "ENTITY-004", "fromField": "lineId", "to": "ENTITY-004", "toField": "id"},
            ],
        },
        "pages": [
            {"id": "PAGE-004", "route": "/admin/menu-items", "module": "MOD-001", "access": "role_restricted", "users": ["ROLE-001"]},
            {"id": "PAGE-006", "route": "/admin/menu-items/[id]", "module": "MOD-001", "access": "authenticated", "users": ["ROLE-001"]},
            {"id": "PAGE-001", "name": "Menu", "route": "/", "module": "MOD-002", "access": "public", "users": ["ROLE-002"]},
            {"id": "PAGE-009", "name": "Place Order", "route": "/order", "module": "MOD-002", "access": "public", "users": ["ROLE-002"]},
        ],
    }
    doc.update(over)
    return doc


# --- who signs up, and who can sign in ---------------------------------------

def test_the_one_role_besides_the_administrators_is_who_signs_up():
    assert am.admin_role(_doc()) == "Admin"
    assert am.signup_role(_doc()) == "Customer"


def test_two_roles_besides_the_administrators_stay_a_choice():
    doc = _doc(roles=[{"id": "ROLE-001", "name": "Admin"}, {"id": "ROLE-002", "name": "Customer"},
                      {"id": "ROLE-003", "name": "Kitchen"}])
    assert am.signup_role(doc) is None


def test_a_declared_signup_role_still_wins():
    assert am.signup_role(_doc(security={"authentication": "email_password", "signupRole": "ROLE-001"})) == "Admin"


def test_every_role_gets_a_demo_login_beside_the_administrator():
    assert am.demo_logins(_doc()) == [("admin@example.com", "Admin"), ("customer@example.com", "Customer")]
    assert am.demo_email("Front Desk") == "front.desk@example.com"


def test_the_app_is_told_every_role(tmp_path):
    am.project_account(_doc(), tmp_path)
    text = (tmp_path / "src/lib/account.ts").read_text()
    assert 'export const ROLES: string[] = ["Admin", "Customer"];' in text
    assert 'export const SIGNUP_ROLE: string | null = "Customer";' in text


def test_the_seed_makes_those_logins_with_the_same_addresses():
    seed = (_TEMPLATES / "runtime/seed.ts").read_text()
    assert "await seedRoleLogins();" in seed
    # the TS derivation is the Python one, so the announcement names real logins
    body = re.search(r"function demoEmail\(role: string\): string \{(.*?)\n\}", seed, re.S).group(1)
    assert '.replace(/[^a-z0-9]+/g, ".")' in body and "@example.com" in body
    assert "onConflictDoNothing" in seed.split("async function seedRoleLogins")[1].split("async function seedAdmin")[0]


def test_the_build_announces_each_login():
    from routers.blueprint_generate import _sign_in_line
    line = _sign_in_line(_doc())
    assert "**admin@example.com** (Admin)" in line and "**customer@example.com** (Customer)" in line
    assert "password" in line
    assert _sign_in_line(_doc(roles=[{"id": "ROLE-001", "name": "Admin"}])) == ""


# --- who may open a page ------------------------------------------------------

def test_one_modules_pages_for_the_same_people_agree_on_who_may_open_them():
    found = access_findings(_doc()["pages"])
    assert len(found) == 1
    assert "/admin/menu-items/[id]" in found[0] and "role_restricted" in found[0]


def test_a_page_written_with_the_disagreeing_access_is_refused_at_its_author():
    result = AgentResult(task_id="T", agent="ux_architecture", proposals=[
        ArtifactProposal(section="pages", natural_key="PAGE:/admin/orders", body={
            "route": "/admin/orders", "module": "MOD-001", "access": "authenticated", "users": ["ROLE-001"]})])
    doc = _doc(pages=_doc()["pages"][:1])
    with pytest.raises(InconsistentPageAccess) as refused:
        check_page_access(result, doc)
    assert "/admin/orders" in str(refused.value)


def test_an_edit_to_a_pages_content_is_not_held_hostage():
    result = AgentResult(task_id="T", agent="ux_architecture", proposals=[
        ArtifactProposal(section="pages", natural_key="PAGE:/admin/menu-items",
                         body={"id": "PAGE-004", "purpose": "Manage the menu."})])
    check_page_access(result, _doc())        # PAGE-006's slip is not this write's


def test_making_them_agree_passes():
    result = AgentResult(task_id="T", agent="ux_architecture", proposals=[
        ArtifactProposal(section="pages", natural_key="PAGE:/admin/menu-items/[id]",
                         body={"id": "PAGE-006", "access": "role_restricted"})])
    check_page_access(result, _doc())


# --- what one page hands another ---------------------------------------------

MENU_VIEW = '"use client";\nexport default function V(){ return <Link href={href(pages.placeOrder, {}, { items: ids.join(",") })}>Order</Link>; }'


def _with_code(order_load: str):
    return _doc(pageCode=[{"page": "PAGE-001", "load": "", "view": MENU_VIEW},
                          {"page": "PAGE-009", "load": order_load, "view": '"use client";'}])


def test_a_handoff_the_page_never_reads_is_a_finding():
    from services.blueprint.functional_completeness import functional_findings, handoffs
    doc = _with_code("export async function load() { return {}; }")
    assert handoffs(doc) == [("PAGE-001", "PAGE-009", "items")]
    found = [f for f in functional_findings(doc) if f["rule"] == "handoff-not-read"]
    assert len(found) == 1 and found[0]["page"] == "PAGE-009" and "?items=" in found[0]["detail"]


def test_a_handoff_that_is_read_is_not():
    from services.blueprint.functional_completeness import handoff_findings
    for load in ("export async function load(ctx) { const ids = ctx.searchParams.items; }",
                 "export async function load(ctx) { const { items } = ctx.searchParams; }",
                 'const q = useSearchParams(); q.get("items")'):
        assert handoff_findings(_with_code(load)) == [], load


def test_the_page_writer_is_sent_back_to_read_it():
    from services.blueprint.ui_engineer import _unread_handoffs
    doc = _with_code("")
    page = doc["pages"][3]
    assert _unread_handoffs(doc, page, "export async function load() {}", '"use client";')
    assert not _unread_handoffs(doc, page, "export async function load(ctx) { ctx.searchParams.items }", "")


def test_smith_hears_the_standing_faults_first():
    from services.smith4.turn import standing_faults
    faults = standing_faults(_with_code(""))
    assert any("?items=" in f for f in faults)
    assert any("/admin/menu-items/[id]" in f for f in faults)
    assert standing_faults(None) == []


# --- what a chart is labelled ------------------------------------------------

def test_a_reference_is_labelled_by_its_targets_name():
    from services.blueprint.projection import fk_label_map
    m = fk_label_map(_doc())
    assert m["MenuItem"] == {"categoryId": {"targetEntity": "Category", "labelField": "name"}}
    assert m["menu_items"] == m["MenuItem"] and m["menuitem"] == m["MenuItem"]
    assert "lineId" not in m["OrderItem"]


def test_the_fk_label_file_is_projected_and_owned():
    from services.blueprint.projection import FK_LABELS_PATH
    # the path the engine reads, and one assembly will not overwrite with a scaffold copy
    assert FK_LABELS_PATH == "src/lib/fk-labels.json"
    assert f'"{FK_LABELS_PATH}"' in (_TEMPLATES.parent / "services/blueprint/assembly.py").read_text()


def test_a_yes_no_group_stays_a_boolean_and_is_named():
    engine = (_TEMPLATES / "runtime/data-engine.ts").read_text()
    assert 'typeof v === "number" || typeof v === "boolean" ? v : String(v)' in engine
    assert 'if (typeof v === "boolean") out[`${d.field}Label`] = booleanLabel(d.field, v);' in engine
    assert "string | number | boolean | null" in (_TEMPLATES / "app-foundation/src/sdk/server.ts").read_text()


def test_built_apps_take_the_engine_and_seed_on_their_next_turn():
    from services.smith.sync_app import RUNTIME_FILES
    assert ("data-engine.ts", "src/lib/data-engine.ts") in RUNTIME_FILES
    assert ("seed.ts", "src/db/seed.ts") in RUNTIME_FILES


def test_the_engines_doorway_moves_with_it(tmp_path):
    from services.smith.sync_app import ENGINE_FOUNDATION_FILES, refresh_engine
    assert "src/lib/data-engine-bridge.ts" in ENGINE_FOUNDATION_FILES
    stale = tmp_path / "src/lib/data-engine-bridge.ts"
    stale.parent.mkdir(parents=True)
    stale.write_text("// an older bridge\n")
    assert "src/lib/data-engine-bridge.ts" in refresh_engine(tmp_path)
    assert "boolean" in stale.read_text()


def test_a_page_may_not_sign_people_in_by_itself():
    from services.blueprint.ui_engineer import _static_findings
    own = '"use client";\nimport { signIn } from "next-auth/react";\nexport default function V(){ return null; }'
    assert any("next-auth" in f for f in _static_findings("", own))
    sdk = '"use client";\nimport { SignInForm } from "@/sdk/client";\nexport default function V(){ return <SignInForm />; }'
    assert not any("next-auth" in f for f in _static_findings("", sdk))


def test_smith_hears_of_a_sign_in_page_written_before_the_rule():
    from services.smith4.turn import standing_faults
    doc = _doc(pages=[{"id": "PAGE-010", "route": "/login"}],
               pageCode=[{"page": "PAGE-010", "load": "", "view": 'import { signIn } from "next-auth/react";'}])
    assert any(f.startswith("/login signs people in through next-auth") for f in standing_faults(doc))
