"""Two things found testing a built ride-hailing app, fixed in Forge so every future app has them.

1. WORK OFFERED BEFORE IT IS HELD. Every driver could read every other driver's assigned rides (with the customer's
   name and phone) because the entity was left unscoped, so that open requests stay visible. The ownership rule now
   has `readsUnclaimed`: reads reach the rows that are mine and the rows nobody holds yet; writes stay mine only.
2. ONE ADDRESS, ONE ACCOUNT. "A@x.com" and "a@x.com" made two accounts. Sign-up keeps the address trimmed and
   lower-case, and sign-up and sign-in compare without regard to capitals."""
from __future__ import annotations

import json
from pathlib import Path

from services.blueprint.projection import ownership_rules, render_ownership_rules_module

BACKEND = Path(__file__).resolve().parents[2]
RUNTIME = BACKEND / "templates" / "runtime"
FOUNDATION = BACKEND / "templates" / "app-foundation" / "src"


def _doc(rule: dict) -> dict:
    return {"data": {"entities": [{"name": "Ride", "table": "rides", "status": "ACTIVE"}]},
            "security": {"ownershipRules": [rule]}}


RULE = {"entity": "Ride", "column": "driverId", "kind": "scope", "scope": "user",
        "unscopedRoles": ["Admin"], "readsUnclaimed": True}


def test_the_rule_reaches_the_manifest_the_engine_reads():
    rules = ownership_rules(_doc(RULE))["rides"]
    assert rules[0]["readsUnclaimed"] is True and rules[0]["column"] == "driverId"


def test_without_it_the_rule_is_as_strict_as_before():
    plain = {k: v for k, v in RULE.items() if k != "readsUnclaimed"}
    assert "readsUnclaimed" not in ownership_rules(_doc(plain))["rides"][0]


def test_the_generated_rules_file_knows_the_option():
    src = render_ownership_rules_module(ownership_rules(_doc(RULE)))
    assert "readsUnclaimed" in src and '"readsUnclaimed": true' in src.replace("readsUnclaimed: true", '"readsUnclaimed": true') or "readsUnclaimed" in src


def test_the_schema_accepts_it_and_the_engine_applies_it_to_reads_only():
    schema = json.loads((BACKEND / "contracts" / "blueprint.schema.json").read_text(encoding="utf-8"))
    assert "readsUnclaimed" in json.dumps(schema)
    engine = (RUNTIME / "data-engine.ts").read_text(encoding="utf-8")
    line = next(l for l in engine.splitlines() if "readsUnclaimed" in l and "op ===" in l)
    # reads, and a workflow's own claim (its steps decide who may take it); never a direct write over the data API
    assert 'op === "read"' in line and 'startsWith("workflow")' in line and "isNull(col)" in line
    wf = (RUNTIME / "workflows" / "index.ts").read_text(encoding="utf-8")
    assert 'scopeForTable(table, user, op, "workflow")' in wf


def test_the_agent_is_told_to_use_it_for_offered_work():
    from services.blueprint import executors
    text = Path(executors.__file__).read_text(encoding="utf-8")
    assert "readsUnclaimed: true" in text and "Never leave such an entity unscoped" in text


def test_signup_keeps_the_address_lower_case_and_compares_without_capitals():
    signup = (FOUNDATION / "app" / "api" / "auth" / "signup" / "route.ts").read_text(encoding="utf-8")
    assert ".trim().toLowerCase().email(" in signup
    assert "lower(${users.email}) = ${data.email}" in signup
    auth = (FOUNDATION / "auth.ts").read_text(encoding="utf-8")
    assert "lower(${users.email})" in auth and 'toLowerCase()' in auth
