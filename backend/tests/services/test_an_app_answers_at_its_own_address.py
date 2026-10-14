"""A published app answers at the owner's own domain or subdomain.

Forge attaches the address to the app's Vercel project, says which records to
add (read from Vercel), watches until the address answers with a valid
certificate, and makes the app follow its main address: sign-in's address,
a redeploy so it takes effect, and the old vercel.app address sent there.
The Vercel API is a stand-in here that keeps state the way the real one does.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from services.deploy import domains as dm
from services.deploy.domain_check import check_address as real_check_address
from services.deploy.domains import DomainRefused, DomainService, normalise, records_for


class FakeVercel:
    """Projects, domains, DNS config and env the way Vercel answers them."""

    def __init__(self, published: bool = True):
        self.project = {"id": "prj_1", "name": "aqua"} if published else None
        self.domains: dict[str, dict] = {"aqua.vercel.app": {"name": "aqua.vercel.app", "verified": True,
                                                               "apexName": "vercel.app"}}
        self.configured: set[str] = set()
        self.claimed_elsewhere: set[str] = set()
        self.in_use: set[str] = set()
        self.env: dict[str, dict] = {}
        self.redeploys: list[str] = []
        self.redirects: dict[str, str | None] = {}

    async def get_project(self, name):
        return self.project

    async def add_project_domain(self, pid, name):
        if name in self.in_use:
            raise RuntimeError("Vercel add_project_domain failed: status=409 body={'error': 'domain already in use'}")
        apex = ".".join(name.split(".")[-2:])
        d = {"name": name, "apexName": apex, "verified": name not in self.claimed_elsewhere,
             "verification": ([{"type": "TXT", "domain": f"_vercel.{apex}", "value": "vc-domain-verify=abc",
                                "reason": "pending_domain_verification"}] if name in self.claimed_elsewhere else [])}
        self.domains[name] = d
        return dict(d)

    async def get_project_domain(self, pid, name):
        d = self.domains.get(name)
        return dict(d) if d else None

    async def verify_project_domain(self, pid, name):
        d = self.domains.get(name)
        if d and name not in self.claimed_elsewhere:
            d["verified"] = True
            return dict(d)
        return None

    async def get_domain_config(self, name):
        if name in self.configured:
            return {"misconfigured": False, "configuredBy": "CNAME"}
        return {"misconfigured": True, "recommendedCNAME": [{"rank": 1, "value": "cname.vercel-dns.com."}],
                "recommendedIPv4": [{"rank": 1, "value": ["76.76.21.21"]}]}

    async def remove_project_domain(self, pid, name):
        self.domains.pop(name, None)

    async def redirect_project_domain(self, pid, name, to):
        self.redirects[name] = to
        if name in self.domains:
            self.domains[name]["redirect"] = to
        return {}

    async def list_env(self, pid):
        return [{"id": k, "key": k, "value": v["value"]} for k, v in self.env.items()]

    async def set_env(self, pid, key, value, targets):
        self.env[key] = {"value": value}

    async def update_env(self, pid, env_id, value, targets):
        self.env[env_id] = {"value": value}

    async def delete_env(self, pid, env_id):
        self.env.pop(env_id, None)

    async def latest_production_deployment(self, pid):
        return {"uid": "dpl_9"}

    async def redeploy(self, project_name, deployment_id):
        self.redeploys.append(deployment_id)
        return {}


class Clock:
    def __init__(self):
        self.t = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.t


def _project(tmp_path, sso: bool = False):
    from services.blueprint.service import BlueprintService
    svc = BlueprintService.create(output_dir=tmp_path, app_id="aqua", name="AquaTrack", domain="health")
    if sso:
        svc.doc.setdefault("security", {})["signIn"] = {"password": True, "sso": [
            {"id": "entra", "name": "Microsoft", "kind": "oidc", "provider": "entra", "integration": "INT-001"}]}
    svc.save()
    return tmp_path


def _service(tmp_path, fake, *, ok=True, said=None, clock=None):
    async def probe(name):
        return (ok, "" if ok else f"Vercel is still issuing the certificate for {name}.")
    return DomainService(output_dir=str(tmp_path), client=fake, project_name="aqua", probe=probe,
                         say=(said.append if said is not None else None), now=clock or Clock())


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _no_real_probe(monkeypatch):
    """Nothing here reaches the network: a service built without a probe
    (as attach_after_publish builds it) answers as a live certificate."""
    async def answers(name, fetch=None):
        return True, ""
    monkeypatch.setattr(dm, "https_probe", answers)
    monkeypatch.setattr("services.deploy.domain_check.check_address", answers)

    async def nobody(name, transport=None):
        return ""
    monkeypatch.setattr("services.deploy.dns_providers.dns_host", nobody)

    async def no_offer(root, service, transport=None):
        return {}
    monkeypatch.setattr("services.deploy.domain_connect.discover", no_offer)


# --------------------------------------------------------------------------- #

def test_an_address_is_cleaned_and_only_a_real_domain_of_theirs_is_taken():
    assert normalise("https://App.Acme.com/login?x=1") == "app.acme.com"
    assert normalise("acme.co.uk.") == "acme.co.uk"
    for bad in ("", "localhost", "acme", "10.0.0.1", "aqua.vercel.app", "-bad.acme.com", "app.acme.c0m"):
        with pytest.raises(DomainRefused):
            normalise(bad)


def test_the_records_say_what_vercel_asks_for():
    cfg = {"misconfigured": True, "recommendedCNAME": [{"rank": 2, "value": "x."}, {"rank": 1, "value": "cname.vercel-dns.com."}],
           "recommendedIPv4": [{"rank": 1, "value": ["76.76.21.21", "76.76.21.22"]}]}
    sub = records_for("app.acme.com", "subdomain", {"verification": []}, cfg)
    assert sub == [{"host": "app.acme.com", "type": "CNAME", "value": "cname.vercel-dns.com", "why": "points app.acme.com at Vercel"}]
    apex = records_for("acme.com", "apex", None, cfg)
    assert [r["value"] for r in apex] == ["76.76.21.21", "76.76.21.22"] and all(r["type"] == "A" for r in apex)
    proof = records_for("app.acme.com", "subdomain",
                        {"verification": [{"type": "TXT", "domain": "_vercel.acme.com", "value": "vc=1"}]}, cfg)
    assert proof[-1]["type"] == "TXT" and proof[-1]["host"] == "_vercel.acme.com"


def test_an_address_waits_for_its_records_then_goes_live_and_the_app_follows(tmp_path):
    root = _project(tmp_path)
    fake, said, clock = FakeVercel(), [], Clock()
    svc = _service(root, fake, said=said, clock=clock)
    view = run(svc.connect("app.acme.com"))
    assert view["status"] == "waiting" and view["main"] is True and view["kind"] == "subdomain"
    assert view["records"][0]["type"] == "CNAME" and "not there yet" in view["detail"]
    assert "app.acme.com" in fake.domains
    clock.t += timedelta(minutes=5)
    fake.configured.add("app.acme.com")
    view = run(svc.refresh("app.acme.com"))
    assert view["status"] == "live" and view.get("liveAt")
    assert any("app.acme.com is live" in s for s in said)
    assert fake.env["NEXTAUTH_URL"]["value"] == "https://app.acme.com", "sign-in knows its new address"
    assert fake.redeploys == ["dpl_9"], "redeployed so the setting takes effect"
    assert fake.redirects["aqua.vercel.app"] == "app.acme.com", "the old address sends people on"
    from services.deploy.sign_in_address import published_address
    assert published_address(str(root / "app"), "aqua") == "https://app.acme.com", "every later publish pins it"


def test_the_definition_changes_only_when_the_status_does(tmp_path):
    root = _project(tmp_path)
    fake, clock = FakeVercel(), Clock()
    svc = _service(root, fake, clock=clock)
    run(svc.connect("app.acme.com"))
    from services.blueprint.service import BlueprintService
    v1 = BlueprintService.load(output_dir=root).doc.get("version")
    for _ in range(3):
        clock.t += timedelta(minutes=1)
        run(svc.refresh("app.acme.com"))
    assert BlueprintService.load(output_dir=root).doc.get("version") == v1
    led = json.loads((root / ".forge" / "domains.json").read_text())
    assert led["domains"]["app.acme.com"]["checkedAt"].startswith("2026-10-14T09:03")


def test_a_domain_claimed_elsewhere_asks_for_its_proof(tmp_path):
    root = _project(tmp_path)
    fake = FakeVercel()
    fake.claimed_elsewhere.add("app.acme.com")
    view = run(_service(root, fake).connect("app.acme.com"))
    assert view["status"] == "waiting" and "proves" in view["detail"]
    assert any(r["type"] == "TXT" and r["host"] == "_vercel.acme.com" for r in view["records"])


def test_a_bare_domain_gets_a_records_and_a_live_certificate_is_awaited(tmp_path):
    root = _project(tmp_path)
    fake = FakeVercel()
    view = run(_service(root, fake, ok=False).connect("acme.com"))
    assert view["kind"] == "apex" and view["records"][0]["type"] == "A"
    fake.configured.add("acme.com")
    view = run(_service(root, fake, ok=False).refresh("acme.com"))
    assert view["status"] == "waiting" and "certificate" in view["detail"]


def test_an_address_added_before_the_first_publish_is_attached_by_it(tmp_path):
    root = _project(tmp_path)
    fake = FakeVercel(published=False)
    view = run(_service(root, fake).connect("acme.com"))
    assert view["status"] == "waiting" and "first publish" in view["detail"] and "acme.com" not in fake.domains
    fake.project = {"id": "prj_1", "name": "aqua"}
    views = run(dm.attach_after_publish(str(root / "app"), fake, "aqua"))
    assert "acme.com" in fake.domains
    assert views[0]["kind"] == "apex", "a bare domain is known once Vercel says so"


def test_an_address_another_app_uses_is_refused(tmp_path):
    root = _project(tmp_path)
    fake = FakeVercel()
    fake.in_use.add("app.acme.com")
    with pytest.raises(DomainRefused) as e:
        run(_service(root, fake).connect("app.acme.com"))
    assert "already used" in str(e.value)


def test_the_watch_gives_up_after_two_days_and_says_so(tmp_path):
    root = _project(tmp_path)
    fake, said, clock = FakeVercel(), [], Clock()
    svc = _service(root, fake, said=said, clock=clock)
    run(svc.connect("app.acme.com"))
    clock.t += timedelta(hours=49)
    view = run(svc.refresh("app.acme.com"))
    assert view["status"] == "failed" and "two days" in view["detail"]
    assert any("not working" in s for s in said)
    seen = dm.read_ledger(root)["domains"]["app.acme.com"]
    assert dm.next_check(svc.entries()[0], seen, clock.t) is None, "the watch stops; Check now still works"


def test_the_watch_checks_often_at_first_then_less(tmp_path):
    entry = {"status": "waiting", "addedAt": "2026-10-14T09:00:00Z"}
    t0 = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)
    seen = {"checkedAt": "2026-10-14T09:05:00Z"}
    assert dm.next_check(entry, seen, t0 + timedelta(minutes=5)) == t0 + timedelta(minutes=5, seconds=30)
    seen = {"checkedAt": "2026-10-14T09:30:00Z"}
    assert dm.next_check(entry, seen, t0 + timedelta(minutes=30)) == t0 + timedelta(minutes=32)
    live = {"status": "live", "addedAt": "2026-10-14T09:00:00Z"}
    assert dm.next_check(live, seen, t0 + timedelta(minutes=30)) == t0 + timedelta(minutes=30, hours=24)


def test_switching_and_removing_the_main_address_moves_the_app_with_it(tmp_path):
    root = _project(tmp_path)
    fake = FakeVercel()
    fake.configured.update({"app.acme.com", "portal.acme.com"})
    svc = _service(root, fake)
    run(svc.connect("app.acme.com"))
    run(svc.connect("portal.acme.com"))
    assert [e["name"] for e in svc.entries() if e["main"]] == ["app.acme.com"], "a second address does not take over"
    run(svc.make_main("portal.acme.com"))
    assert fake.env["NEXTAUTH_URL"]["value"] == "https://portal.acme.com"
    run(svc.make_main("app.acme.com"))
    assert fake.env["NEXTAUTH_URL"]["value"] == "https://app.acme.com"
    run(svc.remove("app.acme.com"))
    assert "app.acme.com" not in fake.domains
    assert "NEXTAUTH_URL" not in fake.env and fake.redirects["aqua.vercel.app"] is None, \
        "no live main address left: sign-in reads Vercel's host again and the old address answers"


def test_the_old_address_can_keep_answering(tmp_path):
    root = _project(tmp_path)
    fake = FakeVercel()
    fake.configured.add("app.acme.com")
    svc = _service(root, fake)
    run(svc.connect("app.acme.com"))
    assert fake.redirects["aqua.vercel.app"] == "app.acme.com"
    run(svc.set_old_address("keep"))
    assert fake.redirects["aqua.vercel.app"] is None and svc.view()["oldAddress"] == "keep"


def test_what_to_register_elsewhere_follows_the_main_address(tmp_path):
    root = _project(tmp_path, sso=True)
    fake = FakeVercel()
    fake.configured.add("app.acme.com")
    svc = _service(root, fake)
    assert svc.view()["elsewhere"][0]["address"] == "https://aqua.vercel.app/api/auth/callback/entra"
    run(svc.connect("app.acme.com"))
    assert svc.view()["elsewhere"][0]["address"] == "https://app.acme.com/api/auth/callback/entra"
    assert svc.view()["mainAddress"] == "https://app.acme.com"


def test_a_live_address_must_also_finish_sign_in_there_and_it_shows_on_the_scorecard(tmp_path):
    from services.blueprint import scorecard as sc
    from services.blueprint.service import BlueprintService
    root = _project(tmp_path)
    svc0 = BlueprintService.load(output_dir=root)
    sc._save(svc0, sc.empty(svc0.doc))
    providers = {"credentials": {"callbackUrl": "https://aqua-abc123.vercel.app/api/auth/callback/credentials"}}

    async def fetch(url):
        return (200, providers) if url.endswith("/api/auth/providers") else (200, "<html>")

    fake = FakeVercel()
    fake.configured.add("app.acme.com")
    svc = _service(root, fake)
    svc.address_check = lambda name: real_check_address(name, fetch)
    view = run(svc.connect("app.acme.com"))
    assert view["status"] == "live" and view["works"] is False and "still finishes at aqua-abc123.vercel.app" in view["worksDetail"]
    routes = sc.read(BlueprintService.load(output_dir=root).doc)["criteria"]["routes"]
    assert any(r["id"] == "domain:app.acme.com" for r in routes["red"])
    seen = dm.read_ledger(root)["domains"]["app.acme.com"]
    entry = svc.entries()[0]
    assert dm.next_check(entry, seen, svc.now()) <= svc.now() + timedelta(minutes=2), "looked at again soon"
    providers["credentials"]["callbackUrl"] = "https://app.acme.com/api/auth/callback/credentials"
    total_before = routes["total"]
    view = run(svc.refresh("app.acme.com"))
    assert view["works"] is True
    routes = sc.read(BlueprintService.load(output_dir=root).doc)["criteria"]["routes"]
    assert not any(r["id"] == "domain:app.acme.com" for r in routes["red"])
    assert routes["total"] == total_before and routes["green"] >= 1, "the same line turns green, not a second one"


# --------------------------------------------------------------------------- #
# Smith
# --------------------------------------------------------------------------- #

def test_smith_puts_the_app_on_its_own_address_and_says_which_record(tmp_path, monkeypatch):
    from services.smith import domain_change
    from services.deploy import vercel_client
    root = _project(tmp_path)
    fake = FakeVercel()
    fake.close = lambda: asyncio.sleep(0)
    monkeypatch.setenv("VERCEL_TOKEN", "t")
    monkeypatch.setattr(vercel_client, "VercelClient", lambda *a, **k: fake)
    async def no_check(name, fetch=None):
        return True, ""
    monkeypatch.setattr("services.deploy.domain_check.check_address", no_check)
    monkeypatch.setattr(dm, "https_probe", no_check)
    out = domain_change.run(str(root), "connect_domain", domain="", change="please put it on App.Acme.com")
    assert out["applied"], out
    assert "app.acme.com is waiting" in out["diff_summary"] and "CNAME app.acme.com → cname.vercel-dns.com" in out["diff_summary"]
    fake.configured.add("app.acme.com")
    out = domain_change.run(str(root), "domain_status", change="is my domain working?")
    assert out["applied"] and "app.acme.com is live, and it is the main address" in out["diff_summary"]
    out = domain_change.run(str(root), "remove_domain", domain="app.acme.com")
    assert out["applied"] and "removed" in out["diff_summary"] and "app.acme.com" not in fake.domains


def test_smith_asks_which_address_and_never_without_publishing_set_up(tmp_path, monkeypatch):
    from services.smith import domain_change
    root = _project(tmp_path)
    monkeypatch.delenv("VERCEL_TOKEN", raising=False)
    out = domain_change.run(str(root), "connect_domain", change="put it on our domain")
    assert not out["applied"] and "Publishing is not set up" in out["reason"]
    out = domain_change.run(str(root), "domain_status", change="is my domain working?")
    assert out["applied"] and "answers at https://" in out["diff_summary"]
    assert domain_change.name_in("open src/app/page.tsx and use app.acme.com") == "app.acme.com"


def test_the_domain_actions_are_registered_everywhere_smith_looks():
    from services.smith.capabilities import unaccounted
    from services.smith.verbs import REQUIRED_BY_VERB, VERB_EXAMPLES, VERB_HELP
    from services.smith4.verbs import PERFORM as VERBS
    verbs = {"connect_domain", "remove_domain", "domain_status", "rename_app_address", "add_dns_records"}
    for v in verbs:
        assert v in REQUIRED_BY_VERB and v in VERB_HELP and v in VERB_EXAMPLES and v in VERBS
    assert not verbs & unaccounted()


# --------------------------------------------------------------------------- #
# A bare domain and its www companion; letting go when the app is deleted
# --------------------------------------------------------------------------- #

def test_a_bare_domain_brings_its_www_companion_which_sends_people_to_it(tmp_path):
    root = _project(tmp_path)
    fake, said = FakeVercel(), []
    fake.configured.update({"acme.com", "www.acme.com"})
    svc = _service(root, fake, said=said)
    run(svc.connect("acme.com"))
    www = next(e for e in svc.entries() if e["name"] == "www.acme.com")
    assert www["redirectTo"] == "acme.com" and www["main"] is False and www["status"] == "live"
    assert fake.redirects["www.acme.com"] == "acme.com"
    assert any("www.acme.com is live and sends people to acme.com" in s for s in said)
    assert fake.env["NEXTAUTH_URL"]["value"] == "https://acme.com", "the companion never becomes the main address"
    with pytest.raises(DomainRefused) as e:
        run(svc.make_main("www.acme.com"))
    assert "make acme.com the main address" in str(e.value)
    run(svc.remove("acme.com"))
    assert svc.entries() == [] and "www.acme.com" not in fake.domains, "the companion goes with its domain"


def test_a_companion_detached_in_vercel_is_attached_and_redirected_again(tmp_path):
    root = _project(tmp_path)
    fake = FakeVercel()
    svc = _service(root, fake)
    run(svc.connect("acme.com"))
    fake.domains.pop("www.acme.com")
    fake.redirects.clear()
    run(svc.refresh("www.acme.com"))
    assert fake.domains["www.acme.com"]["redirect"] == "acme.com"


def test_a_bare_domain_added_before_the_first_publish_brings_its_companion_at_it(tmp_path):
    root = _project(tmp_path)
    fake = FakeVercel(published=False)
    run(_service(root, fake).connect("acme.com"))
    fake.project = {"id": "prj_1", "name": "aqua"}
    views = run(dm.attach_after_publish(str(root / "app"), fake, "aqua"))
    assert [v["name"] for v in views] == ["acme.com", "www.acme.com"]
    assert fake.redirects["www.acme.com"] == "acme.com"


def test_deleting_an_app_lets_go_of_its_addresses(tmp_path):
    root = _project(tmp_path)
    fake = FakeVercel()
    svc = _service(root, fake)
    run(svc.connect("app.acme.com"))
    run(svc.connect("acme.com"))
    gone = run(dm.detach_all(str(root / "app"), fake, "aqua"))
    assert sorted(gone) == ["acme.com", "app.acme.com", "www.acme.com"]
    assert set(fake.domains) == {"aqua.vercel.app"}


# --------------------------------------------------------------------------- #
# The free Tentoro address
# --------------------------------------------------------------------------- #

def test_the_tentoro_name_comes_from_the_app_and_avoids_reserved_words():
    assert dm.tentoro_slug("AquaTrack", "k3j2") == "aquatrack"
    assert dm.tentoro_slug("API", "k3j2") == "k3j2" and dm.tentoro_slug("Go", "k3j2") == "k3j2"
    assert dm.tentoro_label("Clinic Hub", "apps.tentoro.ai") == "clinic-hub"
    assert dm.tentoro_label("aqua.apps.tentoro.ai", "apps.tentoro.ai") == "aqua"
    for bad in ("admin", "ab", "aqua.example.com", "x" * 41):
        with pytest.raises(DomainRefused):
            dm.tentoro_label(bad, "apps.tentoro.ai")


def test_every_publish_gives_a_tentoro_address_used_until_the_owners_own_is_live(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_APPS_DOMAIN", "apps.tentoro.ai")
    root = _project(tmp_path)
    fake = FakeVercel()
    fake.configured.add("aquatrack.apps.tentoro.ai")
    views = run(dm.attach_after_publish(str(root / "app"), fake, "aqua"))
    assert [(v["name"], v["kind"], v["main"], v["status"]) for v in views] == \
        [("aquatrack.apps.tentoro.ai", "tentoro", True, "live")]
    assert views[0]["records"] == [], "no DNS work for anyone"
    assert fake.env["NEXTAUTH_URL"]["value"] == "https://aquatrack.apps.tentoro.ai"
    assert fake.redirects["aqua.vercel.app"] == "aquatrack.apps.tentoro.ai"
    run(dm.attach_after_publish(str(root / "app"), fake, "aqua"))
    svc = _service(root, fake)
    assert len(svc.entries()) == 1, "a later publish keeps the one it has"

    run(svc.connect("app.acme.com"))
    assert [e["name"] for e in svc.entries() if e["main"]] == ["app.acme.com"]
    assert fake.env["NEXTAUTH_URL"]["value"] == "https://aquatrack.apps.tentoro.ai", \
        "the owner's own address is main once live; until then the Tentoro address serves"
    fake.configured.add("app.acme.com")
    run(svc.refresh("app.acme.com"))
    assert fake.env["NEXTAUTH_URL"]["value"] == "https://app.acme.com"
    assert fake.redirects["aqua.vercel.app"] == "app.acme.com"

    run(svc.remove("app.acme.com"))
    assert [e["name"] for e in svc.entries() if e["main"]] == ["aquatrack.apps.tentoro.ai"]
    assert fake.env["NEXTAUTH_URL"]["value"] == "https://aquatrack.apps.tentoro.ai"
    with pytest.raises(DomainRefused) as e:
        run(svc.remove("aquatrack.apps.tentoro.ai"))
    assert "rename it" in str(e.value)


def test_a_taken_tentoro_name_falls_back_to_the_projects_own(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_APPS_DOMAIN", "apps.tentoro.ai")
    root = _project(tmp_path)
    fake = FakeVercel()
    fake.in_use.add("aquatrack.apps.tentoro.ai")
    views = run(dm.attach_after_publish(str(root / "app"), fake, "aqua"))
    assert views[0]["name"] == "aqua.apps.tentoro.ai"


def test_the_tentoro_address_is_renamed_and_a_taken_or_reserved_name_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_APPS_DOMAIN", "apps.tentoro.ai")
    root = _project(tmp_path)
    fake = FakeVercel()
    fake.configured.update({"aquatrack.apps.tentoro.ai", "aqua.apps.tentoro.ai", "clinic.apps.tentoro.ai"})
    run(dm.attach_after_publish(str(root / "app"), fake, "aqua"))
    svc = _service(root, fake)
    view = run(svc.rename_tentoro("Aqua"))
    assert view["name"] == "aqua.apps.tentoro.ai" and view["status"] == "live" and view["main"] is True
    assert "aquatrack.apps.tentoro.ai" not in fake.domains
    assert fake.env["NEXTAUTH_URL"]["value"] == "https://aqua.apps.tentoro.ai", "sign-in follows the new name"
    assert "aquatrack.apps.tentoro.ai" not in dm.read_ledger(root)["domains"]
    fake.in_use.add("taken.apps.tentoro.ai")
    for bad, why in (("admin", "kept for the platform"), ("taken", "taken by another app")):
        with pytest.raises(DomainRefused) as e:
            run(svc.rename_tentoro(bad))
        assert why in str(e.value)
    assert [e["name"] for e in svc.entries()] == ["aqua.apps.tentoro.ai"] and "aqua.apps.tentoro.ai" in fake.domains
    run(svc.connect("clinic.apps.tentoro.ai"))
    assert [(e["name"], e["kind"]) for e in svc.entries()] == [("clinic.apps.tentoro.ai", "tentoro")], \
        "a name under the Tentoro domain renames the app's own, never adds a second"


def test_without_a_tentoro_domain_there_is_nothing_to_rename(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGE_APPS_DOMAIN", raising=False)
    root = _project(tmp_path)
    assert run(dm.attach_after_publish(str(root / "app"), FakeVercel(), "aqua")) == []
    with pytest.raises(DomainRefused):
        run(_service(root, FakeVercel()).rename_tentoro("aqua"))


def test_smith_renames_the_tentoro_address(tmp_path, monkeypatch):
    from services.smith import domain_change
    from services.deploy import vercel_client
    monkeypatch.setenv("FORGE_APPS_DOMAIN", "apps.tentoro.ai")
    root = _project(tmp_path)
    fake = FakeVercel()
    fake.close = lambda: asyncio.sleep(0)
    fake.configured.update({"aquatrack.apps.tentoro.ai", "aqua.apps.tentoro.ai"})
    run(dm.attach_after_publish(str(root / "app"), fake, "aqua"))
    monkeypatch.setenv("VERCEL_TOKEN", "t")
    monkeypatch.setattr(vercel_client, "VercelClient", lambda *a, **k: fake)

    async def ok(name, fetch=None):
        return True, ""
    monkeypatch.setattr("services.deploy.domain_check.check_address", ok)
    monkeypatch.setattr(dm, "https_probe", ok)
    out = domain_change.run(str(root), "rename_app_address", domain="aqua", change="call our address aqua")
    assert out["applied"], out
    assert "aqua.apps.tentoro.ai now" in out["diff_summary"]
    out = domain_change.run(str(root), "rename_app_address", domain="", change="rename our address")
    assert not out["applied"] and "What should the address be called" in out["reason"]
