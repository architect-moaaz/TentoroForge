"""An order is a customer's, a restaurant's and the driver's who carries it. Found building a Zomato-like app: the data engine
ANDed every ownership rule of an entity, so no one could reach any order, and a workspace column of the person's own record
(a manager's restaurant) never reached the session at all. A rule can now name the `roles` it applies to, and the session
carries the account's own fields."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from services.blueprint import projection

BACKEND = Path(__file__).resolve().parents[2]
RUNTIME = BACKEND / "templates" / "runtime"

DOC = {
    "data": {"entities": [
        {"id": "ENTITY-001", "name": "Account", "table": "accounts", "account": True,
         "fields": [{"name": "id", "type": "uuid"}, {"name": "restaurantId", "type": "uuid"}]},
        {"id": "ENTITY-002", "name": "Order", "table": "orders",
         "fields": [{"name": "id", "type": "uuid"}, {"name": "customerId", "type": "uuid"}, {"name": "restaurantId", "type": "uuid"},
                    {"name": "driverId", "type": "uuid"}]},
    ]},
    "security": {"ownershipRules": [
        {"entity": "Order", "column": "customerId", "kind": "scope", "scope": "user", "roles": ["Customer"], "unscopedRoles": ["Admin"]},
        {"entity": "Order", "column": "restaurantId", "kind": "scope", "scope": "workspace", "actorColumn": "restaurantId",
         "roles": ["Restaurant Manager"], "unscopedRoles": ["Admin"]},
        {"entity": "Order", "column": "driverId", "kind": "scope", "scope": "user", "readsUnclaimed": True,
         "roles": ["Delivery Partner"], "unscopedRoles": ["Admin"]},
    ]},
}


def test_the_contract_accepts_a_rule_for_certain_roles():
    schema = json.loads((BACKEND / "contracts" / "blueprint.schema.json").read_text(encoding="utf-8"))
    rule = [a for a in schema["properties"]["security"]["properties"]["ownershipRules"]["items"]["anyOf"] if a.get("type") == "object"][0]
    assert rule["properties"]["roles"]["type"] == "array"


def test_the_manifest_the_engine_reads_carries_the_roles():
    rules = [r for k, rs in projection.ownership_rules(DOC).items() for r in rs if r["column"] in ("customerId", "restaurantId", "driverId")]
    by_column = {r["column"]: r for r in rules}
    assert by_column["customerId"]["roles"] == ["Customer"]
    assert by_column["restaurantId"]["roles"] == ["Restaurant Manager"] and by_column["restaurantId"]["actorColumn"] == "restaurantId"
    assert by_column["driverId"]["roles"] == ["Delivery Partner"] and by_column["driverId"]["readsUnclaimed"] is True


def test_a_rule_for_every_one_has_no_roles_in_the_manifest():
    doc = {**DOC, "security": {"ownershipRules": [{"entity": "Order", "column": "customerId", "kind": "scope", "scope": "user"}]}}
    rule = next(r for rs in projection.ownership_rules(doc).values() for r in rs)
    assert "roles" not in rule


def test_the_data_engine_holds_each_role_to_its_own_rules_everywhere_it_applies_them():
    engine = (RUNTIME / "data-engine.ts").read_text(encoding="utf-8")
    assert 'from "./ownership-roles"' in engine and "reachesNothing(rules.filter(" in engine
    assert 'op === "read" && r.reads === "everyone"' in engine      # a rule that lets everyone read shuts nobody out of reading
    assert engine.count("appliesTo(rule,") >= 4          # the read filter, the through check, the create fill and the update check
    assert "roles?: string[]" in Path(projection.__file__).read_text(encoding="utf-8")   # the manifest's type


def test_every_app_carries_the_role_file_the_engine_imports():
    from services.smith import sync_app
    from services import runtime_injector
    assert ("ownership-roles.ts", "src/lib/ownership-roles.ts") in sync_app.RUNTIME_FILES
    assert sync_app._runtime_modules()["lib/ownership-roles"] == "ownership-roles.ts"
    assert "ownership-roles.ts" in Path(runtime_injector.__file__).read_text(encoding="utf-8")


def test_the_session_carries_the_account_s_own_fields():
    auth = (BACKEND / "templates" / "app-foundation" / "src" / "auth.ts").read_text(encoding="utf-8")
    assert "async function accountProfile" in auth and "@/lib/account-table" in auth
    assert auth.count("await accountProfile(") >= 3       # at sign-in and at both refreshes, or the fields would vanish after fifteen minutes


def test_smith_is_taught_one_rule_per_role():
    from services.blueprint.executors import NODE_TASKS
    text = NODE_TASKS["security"]
    assert "ONE ENTITY, SEVERAL KINDS OF PERSON" in text and "ONE RULE PER ROLE" in text and "`roles`" in text


def test_the_access_check_tests_a_role_only_against_the_rules_addressed_to_it():
    code = (BACKEND / "services" / "blueprint" / "access_check.py").read_text(encoding="utf-8")
    assert 'named = {str(x) for x in rule.get("roles") or []}' in code and "role not in named and role not in exempt" in code


@pytest.mark.skipif(shutil.which("node") is None, reason="node is needed to run the shipped code")
def test_the_role_logic_runs_under_node():
    run = subprocess.run(["node", "--experimental-strip-types", "--no-warnings",
                          str(RUNTIME / "__tests__" / "a-rule-for-certain-roles-applies-only-to-them.test.mts")],
                         capture_output=True, text=True, timeout=120)
    if "unknown option" in run.stderr or "bad option" in run.stderr:
        pytest.skip("this node cannot strip types")
    assert run.returncode == 0, run.stdout[-2000:] + run.stderr[-2000:]
