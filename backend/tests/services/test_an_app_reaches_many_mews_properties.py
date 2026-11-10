"""An application reaches many Mews properties, each with its own token,
managed by its administrator inside the application.

Mews issues one client token per integration and one access token per hotel.
The first Mews adapter read both from the organisation's settings — one value
per name, baked into the app's environment — so an application serving many
hotels could reach exactly one, and adding a hotel meant a redeploy. Now the
hotels are rows of `forge_mews_properties` (token sealed, read back as a
mask), added and removed on the app's own page; a step names the hotel
(`auth.property`) and the runtime opens that property's token inside the call.

And the contract said what the runtime could do: `auth: {"provider": "mews"}`,
which the steps prompt told agents to write, was refused by the Blueprint
schema (it required `secretRef`). The runtime halves are
`templates/runtime/__tests__/a-mews-call-reaches-the-property-it-names` and
`a-step-reaches-mews-the-way-mews-reads-it`.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from services.blueprint.agent_contract import AgentResult, ArtifactProposal, InvalidTrigger, check_workflow_triggers
from services.blueprint.service import CONTRACT_PATH
from services.node_config_specs import keys_for_provider
from services.signed_services import has_properties, step_lines

RUNTIME = Path(__file__).resolve().parents[2] / "templates" / "runtime"
MEWS = [{"id": "INT-001", "name": "Mews", "kind": "other", "provider": "mews", "status": "APPROVED",
         "secretRefs": ["MEWS_CLIENT_TOKEN"]}]


def _auth_schema() -> Draft7Validator:
    schema = json.loads(CONTRACT_PATH.read_text("utf-8"))
    step = schema["properties"]["workflows"]["items"]["properties"]["steps"]["items"]
    return Draft7Validator(step["properties"]["config"]["properties"]["auth"])


def test_the_contract_takes_the_provider_and_the_property_a_step_names():
    auth = _auth_schema()
    assert auth.is_valid({"provider": "mews"}), "what the steps prompt tells agents to write"
    assert auth.is_valid({"provider": "mews", "property": "{{booking.propertyId}}"})
    assert auth.is_valid({"secretRef": "XERO_API_KEY", "in": "bearer"}), "a named secret, as before"
    assert not auth.is_valid({"provider": "mews", "token": "at-123"}), "nowhere to write a token"
    assert not auth.is_valid({"in": "bearer"})


def _flow(auth: dict):
    cfg = {"actionType": "http_call", "url": "/api/connector/v1/reservations/getAll/2023-06-06", "auth": auth}
    result = AgentResult(task_id="T", agent="workflow", proposals=[ArtifactProposal(
        section="workflows", natural_key="Pull bookings", body={"name": "Pull bookings", "trigger": {"kind": "manual"},
                                                                "steps": [{"key": "pull", "name": "Pull", "type": "action",
                                                                           "config": cfg}]})])
    return result, {"roles": [], "data": {"entities": []}, "integrations": MEWS}


def test_a_step_may_name_the_property_it_calls():
    check_workflow_triggers(*_flow({"provider": "mews", "property": "{{booking.propertyId}}"}))
    assert has_properties("mews") and has_properties("MEWS") and not has_properties("xero")


def test_the_agents_are_told_how_to_name_a_property():
    lines = step_lines()
    assert "`auth.property`" in lines and "Mews properties page" in lines


def test_the_organisations_access_token_is_optional_once_properties_hold_them():
    keys = {k.key: k for k in keys_for_provider("mews")}
    assert keys["MEWS_CLIENT_TOKEN"].required, "the integration's own token is always needed"
    assert not keys["MEWS_ACCESS_TOKEN"].required
    assert "portfolio" in keys["MEWS_ACCESS_TOKEN"].label


def _scaffold(root: Path) -> Path:
    (root / "src" / "db" / "schema").mkdir(parents=True)
    (root / "src" / "db" / "schema" / "index.ts").write_text('export * from "./app";\n', "utf-8")
    (root / "src" / "app" / "(dashboard)").mkdir(parents=True)
    (root / "package.json").write_text('{"name": "t", "dependencies": {}}', "utf-8")
    return root


def test_every_app_gets_the_table_the_routes_the_page_and_the_library(tmp_path):
    from services.runtime_injector import inject_runtime
    root = _scaffold(tmp_path)
    inject_runtime(str(root))
    for rel in ("src/lib/mews.ts", "src/db/schema/_forge_mews_properties.ts", "src/app/api/mews/guard.ts",
                "src/app/api/mews/properties/route.ts", "src/app/api/mews/properties/[id]/route.ts",
                "src/app/api/mews/properties/[id]/check/route.ts", "src/app/api/mews/stays/route.ts",
                "src/app/api/mews/stays/suggest/route.ts", "src/db/schema/_forge_mews_stays.ts",
                "src/app/(dashboard)/mews-properties/page.tsx",
                "src/app/(dashboard)/mews-properties/MewsPropertiesPanel.tsx"):
        assert (root / rel).is_file(), rel
    barrel = (root / "src" / "db" / "schema" / "index.ts").read_text("utf-8")
    assert barrel.count("forgeMewsProperties") == 1 and barrel.count("forgeMewsStays") == 1
    inject_runtime(str(root))
    assert (root / "src" / "db" / "schema" / "index.ts").read_text("utf-8").count("forgeMewsProperties") == 1, "idempotent"
    manifest = json.loads((root / "contracts" / "runtime-injection-manifest.json").read_text("utf-8"))
    listed = json.dumps(manifest)
    assert "src/app/api/mews/properties/route.ts" in listed, "on the manifest, so the route prune keeps it"


def test_the_table_is_kept_off_the_generic_data_api():
    # Files under src/db/schema starting with "_" are never served by /api/data.
    from services.runtime_injector import _inject_file_storage  # noqa: F401 — the copier that names it
    assert (RUNTIME / "db" / "forge-mews-properties.schema.ts").is_file()
    text = (RUNTIME / "db" / "forge-mews-properties.schema.ts").read_text("utf-8")
    assert '"forge_mews_properties"' in text and "access_token_encrypted" in text and "access_token_mask" in text


def test_an_app_built_before_properties_gets_them_from_smith(tmp_path):
    from services.smith.sync_app import MEWS_FILES, MEWS_LIB, _runtime_modules
    root = tmp_path
    (root / "src" / "lib" / "workflows").mkdir(parents=True)
    (root / "src" / "auth.ts").write_text("export {};", "utf-8")
    (root / "src" / "lib" / "account.ts").write_text("export const ADMIN_ROLE = null;", "utf-8")
    (root / "src" / "lib" / "tenancy.ts").write_text("export const isPlatformRole = () => false;", "utf-8")
    assert _runtime_modules()["lib/mews"] == "mews.ts", "an import of @/lib/mews is filled from the template"
    from services.smith.sync_app import refresh_engine
    changed = refresh_engine(root, None, complete=False)
    for rel in [MEWS_LIB[1]] + [rel for _t, rel in MEWS_FILES]:
        assert (root / rel).is_file() and rel in changed, rel
    again = refresh_engine(root, None, complete=False)
    assert not [r for r in again if "mews" in r], "a current app's Mews files are left alone"


def test_an_app_nobody_signs_in_to_gets_only_the_library_its_workflows_import(tmp_path):
    from services.smith.sync_app import MEWS_LIB, refresh_engine
    (tmp_path / "src" / "lib" / "workflows").mkdir(parents=True)
    refresh_engine(tmp_path, None, complete=False)
    assert (tmp_path / MEWS_LIB[1]).is_file()
    assert not (tmp_path / "src" / "app" / "api" / "mews").exists()


def test_the_workflow_runtime_signs_with_a_propertys_token():
    index = (RUNTIME / "workflows" / "index.ts").read_text("utf-8")
    assert 'await import("../mews")' in index and "credentialsFor(ref)" in index
    assert "process.env.MEWS_ACCESS_TOKEN" not in index, "the property's token, or the organisation's, is mews.ts's to choose"


def test_the_account_menu_offers_the_page_only_to_whom_the_api_lets_in():
    menu = (Path(__file__).resolve().parents[2] / "templates" / "app-foundation" / "src" / "app" / "(dashboard)"
            / "AccountMenu.tsx").read_text("utf-8")
    assert "/api/mews/properties" in menu and "/mews-properties" in menu and "setMews(r.ok)" in menu


def test_the_runtime_suites_for_mews_are_run():
    runner = (RUNTIME / "__tests__" / "run-mews-tests.sh").read_text("utf-8")
    assert "a-mews-call-reaches-the-property-it-names" in runner
    assert "a-step-reaches-mews-the-way-mews-reads-it" in runner


@pytest.mark.skipif(shutil.which("node") is None, reason="node is needed to run the shipped runtime")
@pytest.mark.parametrize("suite", ["a-mews-call-reaches-the-property-it-names", "a-step-reaches-mews-the-way-mews-reads-it"])
def test_the_runtime_suite_passes(suite):
    out = subprocess.run(["node", "--experimental-strip-types", "--no-warnings",
                          str(RUNTIME / "__tests__" / f"{suite}.test.mts")],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stdout[-2000:] + out.stderr[-2000:]
