"""With the owner's DNS account connected, Forge adds an address's records
itself — and never overwrites what is there without asking, nor mail records
even when asked.

The DNS account is a stand-in that keeps records the way a provider does; it
tells the Vercel stand-in when a record makes the address point at Vercel.
The provider clients themselves are checked against recorded HTTP shapes.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from services.deploy import dns_providers as dp
from services.deploy import domains as dm
from services.deploy.dns_providers import Record, plan
from services.deploy.domains import DomainRefused
from tests.services.test_an_app_answers_at_its_own_address import (  # noqa: F401 — the fixture is used
    FakeVercel, _no_real_probe, _project, _service, run)

real_dns_host = dp.dns_host  # the fixture stands it in for everything else


class FakeDns:
    label = "Cloudflare"

    def __init__(self, vercel: FakeVercel | None = None, zones=("acme.com",), rows=()):
        self.vercel = vercel
        self.zones = set(zones)
        self.rows: list[Record] = list(rows)
        self.n = 0
        self.deleted: list[Record] = []

    async def zone_for(self, name):
        return next((c for c in dp._candidates(name) if c in self.zones), None)

    async def records(self, zone, host):
        return [r for r in self.rows if r.host == host]

    async def create(self, zone, rec):
        self.n += 1
        rid = f"rec{self.n}"
        self.rows.append(Record(rec.host, rec.type, rec.value, rid))
        if self.vercel is not None and rec.type in ("A", "CNAME"):
            self.vercel.configured.add(rec.host)
        return rid

    async def delete(self, zone, rec):
        self.rows = [r for r in self.rows if r.id != rec.id]
        self.deleted.append(rec)

    async def close(self):
        return None


# --------------------------------------------------------------------------- #
# The safety rules
# --------------------------------------------------------------------------- #

CNAME = Record("app.acme.com", "CNAME", "cname.vercel-dns.com")
A = Record("acme.com", "A", "76.76.21.21")


def test_what_is_already_there_is_left_alone():
    p = plan([CNAME], [Record("app.acme.com", "CNAME", "cname.vercel-dns.com.", "x")])
    assert p.there == [CNAME] and p.add == [] and not p.conflicts


def test_a_record_in_the_way_stops_everything_until_the_owner_says_replace():
    old = Record("app.acme.com", "A", "1.2.3.4", "x")
    p = plan([CNAME], [old])
    assert p.add == [] and p.conflicts == [(CNAME, old)]
    p = plan([CNAME], [old], replace=True)
    assert p.add == [CNAME] and p.conflicts == [(CNAME, old)]


def test_mail_and_proof_records_are_never_replaced():
    mx = Record("mail.acme.com", "MX", "10 mx.acme.com", "m")
    p = plan([Record("mail.acme.com", "CNAME", "cname.vercel-dns.com")], [mx], replace=True)
    assert p.add == [] and p.blocked == [mx]


def test_a_bare_domain_shares_its_name_with_mail_but_not_with_another_web_record():
    mx = Record("acme.com", "MX", "10 mx.acme.com", "m")
    spf = Record("acme.com", "TXT", "v=spf1 include:mail ~all", "t")
    assert plan([A], [mx, spf]).add == [A]
    for other in (Record("acme.com", "A", "5.6.7.8", "o"), Record("acme.com", "AAAA", "2001:db8::1", "o6")):
        assert plan([A], [mx, other]).conflicts == [(A, other)]
    two = [A, Record("acme.com", "A", "76.76.21.22")]
    assert plan(two, [Record("acme.com", "A", "76.76.21.22", "y")]).add == [A], "wanted records never conflict"


def test_a_proof_sits_beside_other_txt_records():
    proof = Record("_vercel.acme.com", "TXT", "vc-domain-verify=abc")
    assert plan([proof], [Record("_vercel.acme.com", "TXT", "vc-domain-verify=old", "t")]).add == [proof]


# --------------------------------------------------------------------------- #
# Writing them
# --------------------------------------------------------------------------- #

def test_forge_adds_the_record_the_address_goes_live_and_removing_it_takes_the_record_away(tmp_path):
    root = _project(tmp_path)
    fake = FakeVercel()
    dns = FakeDns(fake)
    said: list[str] = []
    svc = _service(root, fake, said=said)
    run(svc.connect("app.acme.com"))
    svc.dns = [dns]
    out = run(svc.write_records("app.acme.com"))
    assert out["written"] and out["provider"] == "Cloudflare" and "CNAME app.acme.com → cname.vercel-dns.com" in out["message"]
    assert [(r.host, r.type, r.value) for r in dns.rows] == [("app.acme.com", "CNAME", "cname.vercel-dns.com")]
    assert svc.view_of("app.acme.com")["status"] == "live" and any("is live" in s for s in said)
    assert dm.read_ledger(root)["domains"]["app.acme.com"]["written"][0]["id"] == "rec1"
    run(svc.remove("app.acme.com"))
    assert dns.rows == [] and [r.id for r in dns.deleted] == ["rec1"], "exactly what Forge wrote, nothing else"


def test_a_bare_domain_and_its_www_are_written_together(tmp_path):
    root = _project(tmp_path)
    fake = FakeVercel()
    dns = FakeDns(fake, rows=[Record("acme.com", "MX", "10 mx.acme.com", "mx1")])
    svc = _service(root, fake)
    run(svc.connect("acme.com"))
    svc.dns = [dns]
    out = run(svc.write_records("acme.com"))
    assert out["written"]
    assert {(r.host, r.type) for r in dns.rows} == {("acme.com", "MX"), ("acme.com", "A"), ("www.acme.com", "CNAME")}
    assert {e["name"]: e["status"] for e in svc.entries()} == {"acme.com": "live", "www.acme.com": "live"}


def test_something_in_the_way_is_named_and_replaced_only_when_asked(tmp_path):
    root = _project(tmp_path)
    fake = FakeVercel()
    old = Record("app.acme.com", "A", "1.2.3.4", "old1")
    dns = FakeDns(fake, rows=[old])
    svc = _service(root, fake)
    run(svc.connect("app.acme.com"))
    svc.dns = [dns]
    out = run(svc.write_records("app.acme.com"))
    assert not out["written"] and out["conflicts"] and out["replaceable"]
    assert "A app.acme.com → 1.2.3.4" in out["message"] and "tell me to replace it" in out["message"]
    assert dns.rows == [old], "nothing changed"
    out = run(svc.write_records("app.acme.com", replace=True))
    assert out["written"] and "Replaced: A app.acme.com → 1.2.3.4" in out["message"]
    assert [(r.type, r.value) for r in dns.rows] == [("CNAME", "cname.vercel-dns.com")]


def test_an_address_holding_mail_is_never_taken_over(tmp_path):
    root = _project(tmp_path)
    fake = FakeVercel()
    mx = Record("mail.acme.com", "MX", "10 mx.acme.com", "mx1")
    dns = FakeDns(fake, rows=[mx])
    svc = _service(root, fake)
    run(svc.connect("mail.acme.com"))
    svc.dns = [dns]
    out = run(svc.write_records("mail.acme.com", replace=True))
    assert not out["written"] and out["conflicts"] and not out["replaceable"]
    assert "Choose another address" in out["message"] and dns.rows == [mx]


def test_records_already_there_are_not_written_twice(tmp_path):
    root = _project(tmp_path)
    fake = FakeVercel()
    dns = FakeDns(fake, rows=[Record("app.acme.com", "CNAME", "cname.vercel-dns.com.", "c1")])
    svc = _service(root, fake)
    run(svc.connect("app.acme.com"))
    svc.dns = [dns]
    out = run(svc.write_records("app.acme.com"))
    assert not out["written"] and "already there" in out["message"] and len(dns.rows) == 1


def test_without_an_account_holding_the_domain_forge_says_where_its_dns_is(tmp_path, monkeypatch):
    root = _project(tmp_path)
    fake = FakeVercel()

    async def at_cloudflare(name, transport=None):
        return "Cloudflare"
    monkeypatch.setattr(dp, "dns_host", at_cloudflare)
    svc = _service(root, fake)
    run(svc.connect("app.acme.com"))
    assert svc.view_of("app.acme.com")["dnsHost"] == "Cloudflare"
    with pytest.raises(DomainRefused) as e:
        run(svc.write_records("app.acme.com"))
    assert "No DNS account is connected" in str(e.value) and "DNS is at Cloudflare" in str(e.value)
    svc.dns = [FakeDns(fake, zones=("other.com",))]
    with pytest.raises(DomainRefused) as e:
        run(svc.write_records("app.acme.com"))
    assert "None of your connected DNS accounts (Cloudflare) holds app.acme.com" in str(e.value)


def test_smith_adds_the_records(tmp_path, monkeypatch):
    from services.deploy import dns_accounts, vercel_client
    from services.smith import domain_change
    root = _project(tmp_path)
    fake = FakeVercel()
    fake.close = lambda: asyncio.sleep(0)
    dns = FakeDns(fake)
    monkeypatch.setenv("VERCEL_TOKEN", "t")
    monkeypatch.setattr(vercel_client, "VercelClient", lambda *a, **k: fake)

    async def accounts(where):
        return [dns]
    monkeypatch.setattr(dns_accounts, "load_for_output_dir", accounts)
    assert domain_change.run(str(root), "connect_domain", change="put it on app.acme.com")["applied"]
    out = domain_change.run(str(root), "add_dns_records", change="add the DNS records for me")
    assert out["applied"], out
    assert "Added at Cloudflare: CNAME app.acme.com" in out["diff_summary"]


# --------------------------------------------------------------------------- #
# The provider clients
# --------------------------------------------------------------------------- #

def test_cloudflare_finds_the_zone_and_writes_an_unproxied_record():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path.endswith("/zones"):
            rows = [{"id": "z1", "name": "acme.com"}] if req.url.params["name"] == "acme.com" else []
            return httpx.Response(200, json={"result": rows})
        if req.method == "GET":
            return httpx.Response(200, json={"result": [{"id": "d1", "name": "app.acme.com", "type": "A", "content": "1.2.3.4"}]})
        if req.method == "POST":
            return httpx.Response(200, json={"result": {"id": "d2"}})
        return httpx.Response(200, json={"result": {"id": "d1"}})

    async def go():
        cf = dp.Cloudflare("cf-test-token", transport=httpx.MockTransport(handler))
        zone = await cf.zone_for("app.acme.com")
        rows = await cf.records(zone, "app.acme.com")
        rid = await cf.create(zone, CNAME)
        await cf.delete(zone, rows[0])
        await cf.close()
        return zone, rows, rid
    zone, rows, rid = asyncio.run(go())
    assert zone == "acme.com" and rows == [Record("app.acme.com", "A", "1.2.3.4", "d1")] and rid == "d2"
    post = next(r for r in seen if r.method == "POST")
    assert post.url.path == "/client/v4/zones/z1/dns_records"
    assert json.loads(post.content) == {"type": "CNAME", "name": "app.acme.com", "content": "cname.vercel-dns.com",
                                        "ttl": 1, "proxied": False}
    assert post.headers["authorization"] == "Bearer cf-test-token"
    assert any(r.method == "DELETE" and r.url.path.endswith("/dns_records/d1") for r in seen)


def test_godaddy_adds_beside_what_is_there_with_names_relative_to_the_domain():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        p = req.url.path
        if p == "/v1/domains/app.acme.com":
            return httpx.Response(404, json={})
        if p == "/v1/domains/acme.com":
            return httpx.Response(200, json={"domain": "acme.com"})
        if p == "/v1/domains/acme.com/records" and req.method == "GET":
            return httpx.Response(200, json=[{"type": "MX", "name": "@", "data": "mx.acme.com"},
                                             {"type": "A", "name": "app", "data": "1.2.3.4"}])
        return httpx.Response(200, json=[])

    async def go():
        gd = dp.GoDaddy("gd-key", "gd-secret", transport=httpx.MockTransport(handler))
        zone = await gd.zone_for("app.acme.com")
        rows = await gd.records(zone, "app.acme.com")
        apex = await gd.records(zone, "acme.com")
        await gd.create(zone, CNAME)
        await gd.close()
        return zone, rows, apex
    zone, rows, apex = asyncio.run(go())
    assert zone == "acme.com"
    assert [(r.type, r.value) for r in rows] == [("A", "1.2.3.4")] and [r.type for r in apex] == ["MX"]
    patch = next(r for r in seen if r.method == "PATCH")
    assert json.loads(patch.content) == [{"type": "CNAME", "name": "app", "data": "cname.vercel-dns.com", "ttl": 600}]
    assert patch.headers["authorization"] == "sso-key gd-key:gd-secret"


class FakeRoute53:
    def __init__(self):
        self.sets = [{"Name": "acme.com.", "Type": "MX", "TTL": 300, "ResourceRecords": [{"Value": "10 mx.acme.com"}]}]
        self.changes: list[dict] = []

    def list_hosted_zones_by_name(self, DNSName, MaxItems):
        return {"HostedZones": [{"Id": "/hostedzone/Z1", "Name": "acme.com.", "Config": {"PrivateZone": False}}]
                if DNSName == "acme.com" else []}

    def list_resource_record_sets(self, HostedZoneId, StartRecordName, MaxItems):
        return {"ResourceRecordSets": [s for s in self.sets if s["Name"].rstrip(".") == StartRecordName]}

    def change_resource_record_sets(self, HostedZoneId, ChangeBatch):
        for c in ChangeBatch["Changes"]:
            self.changes.append(c)
            rs = c["ResourceRecordSet"]
            self.sets = [s for s in self.sets if not (s["Name"].rstrip(".") == rs["Name"].rstrip(".") and s["Type"] == rs["Type"])]
            if c["Action"] != "DELETE":
                self.sets.append(rs)
        return {}


def test_route53_keeps_a_record_set_whole_when_it_adds_or_takes_away_a_value():
    boto = FakeRoute53()

    async def go():
        r53 = dp.Route53("", "", client=boto)
        zone = await r53.zone_for("acme.com")
        rid = await r53.create(zone, A)
        rid2 = await r53.create(zone, Record("acme.com", "A", "76.76.21.22"))
        await r53.delete(zone, Record("acme.com", "A", "76.76.21.21", rid))
        return zone, await r53.records(zone, "acme.com"), rid2
    zone, rows, rid2 = asyncio.run(go())
    assert zone == "acme.com"
    assert sorted((r.type, r.value) for r in rows) == [("A", "76.76.21.22"), ("MX", "10 mx.acme.com")]
    assert all(c["ResourceRecordSet"]["Type"] == "A" for c in boto.changes), "the MX set is never touched"


def test_who_runs_a_domains_dns_is_told_from_its_nameservers():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.params["name"] == "acme.com":
            return httpx.Response(200, json={"Answer": [{"type": 2, "data": "ada.ns.cloudflare.com."}]})
        return httpx.Response(200, json={"Status": 0})
    assert asyncio.run(real_dns_host("app.acme.com", transport=httpx.MockTransport(handler))) == "Cloudflare"


# --------------------------------------------------------------------------- #
# Where the keys come from
# --------------------------------------------------------------------------- #

def test_the_dns_keys_are_platform_only_and_do_not_hide_the_s3_keys():
    from services.node_config_specs import platform_only_keys
    keys = platform_only_keys()
    for k in ("CLOUDFLARE_API_TOKEN", "ROUTE53_ACCESS_KEY_ID", "ROUTE53_SECRET_ACCESS_KEY",
              "GODADDY_API_KEY", "GODADDY_API_SECRET"):
        assert k in keys
    assert "AWS_ACCESS_KEY_ID" not in keys and "AWS_SECRET_ACCESS_KEY" not in keys


def test_an_account_is_used_only_when_all_its_keys_are_there():
    from services.deploy.dns_accounts import providers_from
    got = providers_from({"cloudflare": {"CLOUDFLARE_API_TOKEN": "cf-test-token"},
                          "godaddy": {"GODADDY_API_KEY": "gd-key"}})
    assert [p.label for p in got] == ["Cloudflare"]
    asyncio.run(got[0].close())
