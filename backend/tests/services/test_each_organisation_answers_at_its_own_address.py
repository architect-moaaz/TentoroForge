"""An app of several organisations gives each its own address.

The platform attaches `*.clinicapp.com`, says which nameservers to set, and
once it answers tells the app (FORGE_ORG_DOMAIN, FORGE_ORG_SIGN_IN_MODE) and
redeploys. The app reads the host and opens that organisation; its admin
sees and renames the address. The runtime half runs the shipped tenancy.ts.
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from services.deploy import domains as dm
from services.deploy.domains import DomainRefused
from tests.services.test_an_app_answers_at_its_own_address import (  # noqa: F401 — the fixture is used
    FakeVercel, _no_real_probe, _service, run)

BACKEND = Path(__file__).resolve().parents[2]
TEMPLATES = BACKEND / "templates"


def _project(tmp_path, tenancy: bool = True):
    from services.blueprint.service import BlueprintService
    svc = BlueprintService.create(output_dir=tmp_path, app_id="clinic", name="ClinicApp", domain="health")
    if tenancy:
        svc.doc.setdefault("security", {})["tenancy"] = {"kind": "organisation", "memberRoles": [], "platformRoles": []}
    svc.save()
    return tmp_path


def test_each_organisation_gets_an_address_once_the_nameservers_are_vercels(tmp_path):
    root = _project(tmp_path)
    fake = FakeVercel()
    svc = _service(root, fake)
    view = run(svc.connect_organisations("ClinicApp.com"))
    assert view["name"] == "*.clinicapp.com" and view["kind"] == "organisations" and view["status"] == "waiting"
    assert [(r["host"], r["type"], r["value"]) for r in view["records"]] == [
        ("clinicapp.com", "NS", "ns1.vercel-dns.com"), ("clinicapp.com", "NS", "ns2.vercel-dns.com")]
    assert "nameservers are not Vercel's yet" in view["detail"]
    assert "*.clinicapp.com" in fake.domains and "FORGE_ORG_DOMAIN" not in fake.env
    fake.configured.add("*.clinicapp.com")
    view = run(svc.refresh("*.clinicapp.com"))
    assert view["status"] == "live"
    assert fake.env["FORGE_ORG_DOMAIN"]["value"] == "clinicapp.com"
    assert fake.env["FORGE_ORG_SIGN_IN_MODE"]["value"] == "shared", "one sign-in across them, unless the definition says"
    assert fake.redeploys, "redeployed so the app reads it"
    assert svc.view()["organisations"] == {"available": True, "signIn": "shared"}
    assert svc.main_address() == "", "the wildcard is never the main address"


def test_sign_in_can_be_kept_per_organisation(tmp_path):
    root = _project(tmp_path)
    fake = FakeVercel()
    fake.configured.add("*.clinicapp.com")
    svc = _service(root, fake)
    run(svc.connect_organisations("clinicapp.com"))
    run(svc.set_organisation_sign_in("per_organisation"))
    assert fake.env["FORGE_ORG_SIGN_IN_MODE"]["value"] == "per_organisation"
    from services.blueprint.service import BlueprintService
    assert BlueprintService.load(output_dir=root).doc["security"]["tenancy"]["addressSignIn"] == "per_organisation"
    with pytest.raises(DomainRefused):
        run(svc.set_organisation_sign_in("sometimes"))


def test_removing_the_wildcard_takes_the_addresses_away_from_the_app(tmp_path):
    root = _project(tmp_path)
    fake = FakeVercel()
    fake.configured.add("*.clinicapp.com")
    svc = _service(root, fake)
    run(svc.connect_organisations("clinicapp.com"))
    run(svc.remove("*.clinicapp.com"))
    assert "*.clinicapp.com" not in fake.domains
    assert "FORGE_ORG_DOMAIN" not in fake.env and "FORGE_ORG_SIGN_IN_MODE" not in fake.env


def test_only_an_app_of_several_organisations_and_only_one_domain(tmp_path):
    root = _project(tmp_path / "one", tenancy=False)
    with pytest.raises(DomainRefused) as e:
        run(_service(root, FakeVercel()).connect_organisations("clinicapp.com"))
    assert "serves one organisation" in str(e.value)
    root = _project(tmp_path / "many")
    svc = _service(root, FakeVercel())
    run(svc.connect_organisations("clinicapp.com"))
    with pytest.raises(DomainRefused) as e:
        run(svc.connect_organisations("other.com"))
    assert "already answer under clinicapp.com" in str(e.value)
    with pytest.raises(DomainRefused):
        run(svc.make_main("*.clinicapp.com"))
    out = run(svc.write_records("*.clinicapp.com"))
    assert not out["written"] and "where the domain is registered" in out["message"]


def test_smith_gives_each_organisation_an_address(tmp_path, monkeypatch):
    from services.deploy import vercel_client
    from services.smith import domain_change
    root = _project(tmp_path)
    fake = FakeVercel()
    fake.close = lambda: asyncio.sleep(0)
    monkeypatch.setenv("VERCEL_TOKEN", "t")
    monkeypatch.setattr(vercel_client, "VercelClient", lambda *a, **k: fake)
    out = domain_change.run(str(root), "give_organisations_addresses",
                            change="give each clinic its own address under clinicapp.com, with separate sign-in per organisation")
    assert out["applied"], out
    assert "under clinicapp.com" in out["diff_summary"] and "own sign-in" in out["diff_summary"]
    assert "NS clinicapp.com → ns1.vercel-dns.com" in out["diff_summary"]


# --------------------------------------------------------------------------- #
# The app
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_shipped_tenancy_opens_the_organisation_the_address_names():
    test = TEMPLATES / "runtime" / "__tests__" / "an-organisation-answers-at-its-own-address.test.mts"
    out = subprocess.run(["node", str(test)], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stdout[-2000:] + out.stderr[-2000:]
    assert "All organisation address tests passed." in out.stdout


def test_every_page_and_route_reads_the_organisation_from_the_address():
    auth = (TEMPLATES / "app-foundation/src/auth.ts").read_text()
    assert "tenancy.atAddress(" in auth and 'h.get("x-forwarded-host") || h.get("host")' in auth
    assert "async redirect({ url, baseUrl })" in auth, "signing in at an organisation's address stays there"
    layout = (TEMPLATES / "app-foundation/src/app/(dashboard)/layout.tsx").read_text()
    assert "<OutsideOrganisation" in layout, "someone who does not belong sees nothing of it"
    cookie = (TEMPLATES / "app-foundation/src/lib/session-cookie.ts").read_text()
    assert 'process.env.FORGE_ORG_SIGN_IN_MODE === "per_organisation"' in cookie and "domain" in cookie
    switcher = (TEMPLATES / "app-foundation/src/app/(dashboard)/OrgSwitcher.tsx").read_text()
    assert "window.location.href = address" in switcher, "switching is going to the other address"
    page = (TEMPLATES / "app-foundation/src/app/(dashboard)/organisation/page.tsx").read_text()
    assert "<AddressPanel" in page and '"/api/org/address"' in page


def test_the_runtime_ships_the_address_table_and_route(tmp_path):
    from services.runtime_injector import inject_runtime
    (tmp_path / "src/db/schema").mkdir(parents=True)
    (tmp_path / "src/db/schema/index.ts").write_text('export * from "./user";\n')
    (tmp_path / "package.json").write_text('{"name": "x", "dependencies": {}}')
    inject_runtime(str(tmp_path))
    assert (tmp_path / "src/db/schema/_forge_org_addresses.ts").is_file()
    assert "forgeOrgAddresses" in (tmp_path / "src/db/schema/index.ts").read_text()
    assert (tmp_path / "src/app/api/org/address/route.ts").is_file()


def test_the_registration_is_complete():
    from services.smith.capabilities import unaccounted
    from services.smith.verbs import REQUIRED_BY_VERB, VERB_EXAMPLES, VERB_HELP
    from services.smith4.verbs import PERFORM
    v = "give_organisations_addresses"
    assert v in REQUIRED_BY_VERB and v in VERB_HELP and v in VERB_EXAMPLES and v in PERFORM and v not in unaccounted()
