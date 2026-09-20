"""Who signs in, and what they must have done first — 036farqu (Tool Share).

Tool Share had every piece and none of the connections: a template signup
that made a login and nothing else, a public "Create Profile" that made a
Member belonging to nobody, a KYC form whose `memberId` no login could fill,
"KYC approval required for listing and borrowing" as prose nothing enforced,
and sign-in screens the build never designed. Each connection is held here,
at the part of the generator that makes it.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from services.blueprint import account_model as am
from services.blueprint.agent_contract import (
    AgentResult, ArtifactProposal, InvalidEntityFields, check_entity_fields, prerequisite_findings,
)

_ROOT = Path(__file__).resolve().parents[3]


def _doc(**over):
    doc = {
        "security": {"authentication": "email_password"},
        "roles": [{"id": "ROLE-001", "name": "Member"}],
        "navigation": {"initialRoute": {"authenticated": "/tools", "public": "/login"}},
        "data": {"entities": [
            {"id": "ENTITY-001", "name": "Member", "table": "members", "account": True, "labelField": "fullName",
             "fields": [{"name": "id", "type": "uuid", "primaryKey": True},
                        {"name": "fullName", "type": "string", "required": True},
                        {"name": "email", "type": "string", "required": True},
                        {"name": "phone", "type": "string"},
                        {"name": "city", "type": "string", "required": True},
                        {"name": "homeHubId", "type": "uuid", "references": "ENTITY-003"},
                        {"name": "avatar", "type": "image"},
                        {"name": "createdAt", "type": "timestamp"}]},
            {"id": "ENTITY-002", "name": "KycVerification", "table": "kyc_verifications",
             "fields": [{"name": "id", "type": "uuid"}, {"name": "memberId", "type": "uuid", "references": "ENTITY-001"},
                        {"name": "status", "type": "enum", "enumValues": ["pending", "approved", "rejected"]}]},
        ]},
        "pages": [{"id": "PAGE-006", "name": "Verify Identity", "route": "/kyc/new"}],
        "workflows": [{"id": "FLOW-004", "name": "Request to Borrow"}],
        "businessRules": [],
    }
    doc.update(over)
    return doc


KYC = {"id": "RULE-001", "name": "KYC first", "kind": "prerequisite", "statement": "Verify before borrowing.",
       "gates": ["FLOW-004"], "requires": {"entity": "ENTITY-002", "account": "memberId", "where": {"status": "approved"}},
       "message": "Verify your identity before you borrow.", "page": "PAGE-006"}


# --- the account entity -----------------------------------------------------

def test_signup_asks_for_what_a_person_types_required_first():
    fields = am.account_fields(_doc())
    assert [f["name"] for f in fields] == ["fullName", "email", "city", "phone"], \
        "no id, no timestamp, no reference to another record, no image — required first"
    assert next(f for f in fields if f["name"] == "email")["kind"] == "email"
    assert next(f for f in fields if f["name"] == "phone")["kind"] == "tel"


def test_the_signup_role_is_declared_or_the_only_one():
    assert am.signup_role(_doc()) == "Member"
    two = _doc(roles=[{"id": "ROLE-001", "name": "Member"}, {"id": "ROLE-002", "name": "Moderator"}])
    assert am.signup_role(two) is None, "never guessed between two roles"
    two["security"]["signupRole"] = "ROLE-001"
    assert am.signup_role(two) == "Member"


def test_a_new_account_goes_where_its_prerequisite_is_done():
    assert am.after_signup_route(_doc()) == "/tools"
    assert am.after_signup_route(_doc(businessRules=[KYC])) == "/kyc/new"


def test_project_account_writes_what_signup_and_the_sdk_read(tmp_path):
    am.project_account(_doc(businessRules=[KYC]), tmp_path)
    acct = (tmp_path / "src/lib/account.ts").read_text()
    assert '"entity": "Member"' in acct and 'SIGNUP_ROLE: string | null = "Member"' in acct
    assert 'AFTER_SIGNUP: string = "/kyc/new"' in acct
    table = (tmp_path / "src/lib/account-table.ts").read_text()
    assert 'import { members } from "@/db/schema/member";' in table
    doc = _doc()
    doc["data"]["entities"][0].pop("account")
    am.project_account(doc, tmp_path)
    assert "ACCOUNT: null | {" in (tmp_path / "src/lib/account.ts").read_text()
    assert "accountTable: any = null" in (tmp_path / "src/lib/account-table.ts").read_text()


def test_the_sdk_knows_the_account_entity():
    from services.blueprint.app_sdk import emit_schema
    assert 'export type AccountEntity = "Member";' in emit_schema(_doc())
    doc = _doc()
    doc["data"]["entities"][0].pop("account")
    assert "export type AccountEntity = never;" in emit_schema(doc)


def _entities(*bodies):
    return AgentResult(task_id="t", agent="data_model", confidence=0.9, proposals=[
        ArtifactProposal(section="data.entities", natural_key=b["name"], body=b) for b in bodies])


def test_one_account_entity_created_at_signup():
    doc = _doc()
    with pytest.raises(InvalidEntityFields, match="already on Member"):
        check_entity_fields(_entities({"name": "Customer", "account": True, "fields": []}), doc)
    # The fields arrive later, per entity, without repeating the flag — still held.
    with pytest.raises(InvalidEntityFields, match="created at signup"):
        check_entity_fields(_entities({"name": "Member", "fields": [
            {"name": "hubId", "type": "uuid", "references": "ENTITY-003", "required": True}]}), doc)


def test_a_vector_names_the_field_it_is_taken_of():
    with pytest.raises(InvalidEntityFields, match="set `of` to one of: photo"):
        check_entity_fields(_entities({"name": "Tool", "fields": [
            {"name": "photo", "type": "image"}, {"name": "photoEmbedding", "type": "vector", "embedding": {"of": ""}}]}), {})
    check_entity_fields(_entities({"name": "Tool", "fields": [
        {"name": "photo", "type": "image"}, {"name": "photoEmbedding", "type": "vector", "embedding": {"of": "photo"}}]}), {})


def test_the_field_author_cannot_move_the_account_flag(tmp_path):
    from services.blueprint.executors import pin_entity_identity
    from services.blueprint.service import BlueprintService

    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="T", domain="ops")
    svc.upsert("data.entities", {"name": "Member", "table": "members", "account": True, "fields": []},
               natural_key="Member")
    eid = svc.doc["data"]["entities"][0]["id"]
    result = _entities({"name": "Member", "account": False, "fields": [{"name": "id", "type": "uuid"}]})
    pin_entity_identity(svc, eid, result)
    assert result.proposals[0].body["account"] is True


# --- the auth pages ---------------------------------------------------------

def test_every_app_with_a_sign_in_gets_both_auth_pages_once():
    bodies = am.auth_page_bodies(_doc())
    assert [(b["route"], b["auth"], b["pattern"], b["access"]) for b in bodies] == [
        ("/login", "login", "auth", "public"), ("/signup", "signup", "auth", "public")]
    assert am.auth_page_bodies(_doc(pages=[{"id": "P", "route": "/login"}, {"id": "Q", "route": "/signup"}])) == []
    assert am.auth_page_bodies(_doc(security={"authentication": "none"})) == []


def test_the_build_declares_them_before_pages_are_laid_out_and_written():
    from services.blueprint.orchestrator import DAG, page_features
    assert DAG["auth_pages"].kind == "service"
    assert "auth_pages" in DAG["page_layouts"].depends_on
    assert page_features({"pages": [{"id": "PAGE-019", "pattern": "auth", "route": "/login"}]}) == [], \
        "an auth page is not a feature `page_details` rewrites"


def test_an_auth_page_is_the_whole_screen_at_its_reserved_segment():
    from services.blueprint.app_sdk import code_page_dir, page_module
    page = {"id": "PAGE-019", "name": "Sign in", "route": "/login", "pattern": "auth", "access": "public"}
    assert code_page_dir(page) == "src/app/login", "not inside the session gate"
    module = page_module({"pages": [page], "data": {"entities": []}}, page, {"page": "PAGE-019", "load": "", "view": ""})
    assert "PageFrame" not in module and "PublicPageFrame" not in module


def test_an_auth_page_without_code_is_the_template_sign_in(tmp_path):
    from services.blueprint.app_sdk import CODE_PAGE_MARKER, project_code_pages
    stale = tmp_path / "src/app/login/page.tsx"
    stale.parent.mkdir(parents=True)
    stale.write_text(f"{CODE_PAGE_MARKER} PAGE-019\n")
    (stale.parent / "view.tsx").write_text("x")
    project_code_pages({"application": {"name": "Tool Share"}, "pages": [], "pageCode": []}, tmp_path)
    text = stale.read_text()
    assert "useLogin" in text and "Tool Share" in text and "__APP_NAME__" not in text
    assert not (stale.parent / "view.tsx").exists()


# --- prerequisites ----------------------------------------------------------

def test_a_prerequisite_must_be_checkable():
    doc = _doc()
    assert prerequisite_findings(KYC, doc) == []
    bad = {**KYC, "gates": ["FLOW-099"], "requires": {"entity": "ENTITY-002", "account": "ownerId"}, "message": ""}
    found = " ".join(prerequisite_findings(bad, doc))
    assert "FLOW-099" in found and "ownerId" not in found.split("one of:")[-1] and "`message`" in found


def test_every_gated_workflow_starts_with_its_prerequisite(tmp_path):
    from services.blueprint.projection import project_workflows
    doc = _doc(businessRules=[KYC])
    doc["workflows"] = [{"id": "FLOW-004", "name": "Request to Borrow", "trigger": {"kind": "manual"}, "steps": [
        {"key": "save", "type": "action", "entity": "ENTITY-002",
         "config": {"actionType": "db_insert", "table": "kyc_verifications", "values": {"status": "pending"}}},
        {"key": "done", "type": "end"}]}]
    project_workflows(doc, tmp_path)
    (defn,) = list((tmp_path / "src/lib/workflows/definitions").glob("*.json"))
    graph = json.loads(defn.read_text())["definition"]
    nodes = {n["id"]: n for n in graph["nodes"]}
    assert [e["target"] for e in graph["edges"] if e["source"] == "trigger"] == ["prereq_rule_001"]
    assert nodes["prereq_rule_001"]["data"]["config"]["where"] == {"memberId": "$user.id", "status": "approved"}
    refused = nodes["prereq_rule_001_refused"]["data"]["config"]
    assert refused["refused"] is True and refused["message"] == KYC["message"]
    assert ("prereq_rule_001_met", "save") in {(e["source"], e["target"]) for e in graph["edges"]}


@pytest.mark.skipif(not (_ROOT / "node_modules/.bin/tsx").exists() or not shutil.which("node"),
                    reason="tsx is not installed")
def test_the_engine_refuses_until_the_prerequisite_is_met(tmp_path):
    from services.blueprint.projection import project_workflows
    doc = _doc(businessRules=[KYC])
    doc["workflows"] = [{"id": "FLOW-004", "name": "Request to Borrow", "trigger": {"kind": "manual"}, "steps": [
        {"key": "save", "type": "action", "config": {"actionType": "set_variable", "variableName": "saved", "value": "yes"}},
        {"key": "done", "type": "end"}]}]
    project_workflows(doc, tmp_path)
    (defn,) = list((tmp_path / "src/lib/workflows/definitions").glob("*.json"))
    engine = _ROOT / "backend/templates/runtime/workflows/engine.ts"
    script = tmp_path / "run.mts"
    script.write_text(f'''
import * as mod from {json.dumps(str(engine))};
import {{ readFileSync }} from "node:fs";
const e: any = (mod as any).executeWorkflow ? mod : (mod as any).default;
const wf = JSON.parse(readFileSync({json.dumps(str(defn))}, "utf8"));
const out: any[] = [];
for (const n of [0, 1]) {{
  e.registerActionHandler("db_query", async () => ({{ rows: Array(n).fill({{}}), count: n }}));
  const r = await e.executeWorkflow(wf, {{}}, {{ id: "member-1", role: "Member" }});
  out.push({{ status: r.status, refused: r.refused ?? null, error: r.error ?? null }});
}}
console.log(JSON.stringify(out));
''')
    proc = subprocess.run([str(_ROOT / "node_modules/.bin/tsx"), str(script)], cwd=_ROOT,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-800:]
    none, met = json.loads(proc.stdout.strip().splitlines()[-1])
    assert none == {"status": "failed", "refused": True, "error": KYC["message"]}
    assert met["status"] == "completed"


def test_an_embedding_on_an_ordinary_field_is_dropped_not_refused(tmp_path):
    """0l133sp2: `embedding: {of: ""}` on non-vector fields failed the contract,
    the retry was blocked for low confidence, and the build stopped."""
    from services.blueprint.executors import pin_entity_identity
    from services.blueprint.service import BlueprintService

    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="T", domain="ops")
    svc.upsert("data.entities", {"name": "Tool", "table": "tools", "fields": []}, natural_key="Tool")
    eid = svc.doc["data"]["entities"][0]["id"]
    result = _entities({"name": "Tool", "fields": [
        {"name": "status", "type": "string", "embedding": {"of": ""}},
        {"name": "photo", "type": "image"},
        {"name": "photoEmbedding", "type": "vector", "embedding": {"of": "photo"}}]})
    pin_entity_identity(svc, eid, result)
    fields = {f["name"]: f for f in result.proposals[0].body["fields"]}
    assert "embedding" not in fields["status"]
    assert fields["photoEmbedding"]["embedding"] == {"of": "photo"}, "a vector field keeps what it embeds"


def test_rules_are_written_when_there_are_workflows_to_gate():
    """0l133sp2: rules ran before workflows existed, the KYC prerequisite could
    name nothing in `gates`, was refused, and was dropped on the retry."""
    from services.blueprint.orchestrator import DAG, levels
    assert "workflows" in DAG["business_rules"].depends_on
    at = {k: i for i, level in enumerate(levels()) for k in level}
    assert at["workflows"] < at["business_rules"] < at["integration"]


def test_the_person_behind_a_login_never_stores_a_password():
    """0l133sp2's Member had a required passwordHash; signup creates the row
    without one, so every signup would have failed."""
    import pytest
    from services.blueprint.agent_contract import InvalidEntityFields, check_entity_fields
    from services.blueprint.executors import NODE_TASKS

    result = _entities({"name": "Member", "account": True, "fields": [
        {"name": "id", "type": "uuid"}, {"name": "passwordHash", "type": "string", "required": True}]})
    with pytest.raises(InvalidEntityFields, match="login already holds their password"):
        check_entity_fields(result, {"data": {"entities": []}})
    assert "never has a password" in NODE_TASKS["entity_fields"]


# --- what the form asks for, and what the app fills in ----------------------

STATEFUL = _doc(
    data={"entities": [{
        "id": "ENTITY-001", "name": "Member", "table": "members", "account": True,
        "fields": [{"name": "id", "type": "uuid", "primaryKey": True},
                   {"name": "email", "type": "string", "required": True},
                   {"name": "passwordHash", "type": "string", "required": True},
                   {"name": "displayName", "type": "string", "required": True},
                   {"name": "bio", "type": "text"},
                   {"name": "kycStatus", "type": "string", "required": True,
                    "enumValues": ["unverified", "pending", "verified", "rejected"]},
                   {"name": "kycVerifiedAt", "type": "datetime"}]}]},
    workflows=[
        {"id": "FLOW-018", "name": "Submit Identity Verification", "steps": [
            {"key": "save", "type": "action", "entity": "ENTITY-001",
             "config": {"actionType": "db_update", "values": {"kycStatus": "pending"}}}]},
        {"id": "FLOW-016", "name": "Approve Member Verification", "steps": [
            {"key": "ok", "type": "action", "entity": "ENTITY-001",
             "config": {"actionType": "db_update", "values": {"kycStatus": "verified", "kycVerifiedAt": "$now"}}}]},
        {"id": "FLOW-019", "name": "Update Member Profile", "steps": [
            {"key": "save", "type": "action", "entity": "ENTITY-001",
             "config": {"actionType": "db_update",
                        "values": {"displayName": "{{displayName}}", "bio": "{{bio}}"}}}]},
    ])


def test_signup_never_asks_for_what_a_process_decides():
    """0l133sp2's sign-up asked a new neighbour for "Password hash", "Kyc
    status" and "Kyc verified at" — their login's, and the verification
    workflow's. Answering them would let an account claim to be verified."""
    asked = [f["name"] for f in am.account_fields(STATEFUL)]
    assert asked == ["email", "displayName", "bio"]
    assert "passwordHash" not in asked and "kycStatus" not in asked and "kycVerifiedAt" not in asked


def test_a_field_a_workflow_saves_from_what_someone_typed_is_still_theirs():
    """"Update Member Profile" writes `{{displayName}}` — the person's own
    value passing through. Reading that as "the system decides it" took the
    display name and the bio off the form."""
    assert "displayName" in [f["name"] for f in am.account_fields(STATEFUL)]


def test_the_app_starts_a_new_account_where_no_process_has_taken_it():
    """A required state nobody is asked for still has to hold something: the
    one value the workflows never write is where a record begins."""
    initial = am.account_initial(STATEFUL)
    assert initial["kycStatus"] == "unverified"
    assert initial["passwordHash"] == am.UNUSABLE_CREDENTIAL, "the column is NOT NULL and nobody may sign in with it"
    assert "kycVerifiedAt" not in initial, "not required, so it starts empty"
    route = (_ROOT / "backend/templates/app-foundation/src/app/api/auth/signup/route.ts").read_text()
    assert "const values: Record<string, unknown> = { ...ACCOUNT_INITIAL };" in route
