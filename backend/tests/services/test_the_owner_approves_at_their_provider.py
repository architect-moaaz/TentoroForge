"""Domain Connect: the owner approves the address's records at their own DNS
provider in one click, with no key and no copying.

Forge finds whether the provider holds Tentoro's template, builds a signed
link carrying exactly the values Vercel asked for, and the provider checks
the signature against the public key Tentoro publishes. The key pair is made
here, at test time; nothing key-shaped lives in the repo.
"""
from __future__ import annotations

import asyncio
import base64
from urllib.parse import parse_qsl, unquote, urlsplit

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from services.deploy import domain_connect as dc
from services.deploy import domains as dm
from services.deploy.domains import DomainRefused
from tests.services.test_an_app_answers_at_its_own_address import (  # noqa: F401 — the fixture is used
    FakeVercel, _no_real_probe, _project, _service, run)

real_discover = dc.discover  # the fixture stands it in for everything else


@pytest.fixture
def key_pem():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()


@pytest.fixture
def platform(monkeypatch, key_pem):
    monkeypatch.setenv("FORGE_DOMAIN_CONNECT_DOMAIN", "tentoro.ai")
    monkeypatch.setenv("FORGE_DOMAIN_CONNECT_KEY", key_pem)
    return key_pem


GODADDY = {"providerId": "godaddy.com", "providerName": "GoDaddy",
           "urlSyncUX": "https://dcc.godaddy.com/manage", "supported": True}


def _offer(monkeypatch, found=GODADDY):
    async def discover(root, service, transport=None):
        return dict(found)
    monkeypatch.setattr(dc, "discover", discover)


def _verify(url: str, key_pem: str) -> dict[str, str]:
    """What the provider does: the signed string is the query before key/sig."""
    query = urlsplit(url).query
    signed = query.split("&key=")[0]
    params = dict(parse_qsl(query))
    public = serialization.load_pem_private_key(key_pem.encode(), password=None).public_key()
    public.verify(base64.b64decode(unquote(query.split("&sig=")[1])), signed.encode(), padding.PKCS1v15(), hashes.SHA256())
    return params


# --------------------------------------------------------------------------- #
# The templates, the key, the link
# --------------------------------------------------------------------------- #

def test_the_templates_write_what_vercel_asks_and_carry_the_proof_as_its_own_group():
    sub, apex = dc.templates("tentoro.ai", ["forge.tentoro.ai"])
    assert sub["serviceId"] == "forge-subdomain" and sub["hostRequired"] is True
    assert sub["syncPubKeyDomain"] == "tentoro.ai" and sub["syncRedirectDomain"] == "forge.tentoro.ai"
    assert {(r["groupId"], r["type"], r["host"]) for r in sub["records"]} == {
        ("main", "CNAME", "@"), ("proof", "TXT", "_vercel.%domain%.")}
    assert {(r["groupId"], r["type"], r["host"]) for r in apex["records"]} == {
        ("main", "A", "@"), ("www", "CNAME", "www"), ("proof", "TXT", "_vercel.%domain%.")}
    assert all(r.get("txtConflictMatchingMode") == "None" for r in sub["records"] if r["type"] == "TXT"), \
        "the proof sits beside other TXT records"


def test_only_the_public_key_is_published(key_pem):
    rows = dc.public_key_records(key_pem)
    assert rows[0].startswith("p=1,a=RS256,d=") and all(len(r) < 255 for r in rows)
    der = base64.b64decode("".join(r.split(",d=", 1)[1] for r in rows))
    public = serialization.load_der_public_key(der)
    expected = serialization.load_pem_private_key(key_pem.encode(), password=None).public_key()
    assert public.public_numbers() == expected.public_numbers()
    assert all("PRIVATE" not in r for r in rows)


def test_the_values_come_from_vercels_records_and_anything_else_is_left_to_the_owner():
    sub = [{"host": "xyz.abc.com", "type": "CNAME", "value": "cname.vercel-dns.com"},
           {"host": "_vercel.abc.com", "type": "TXT", "value": "vc-domain-verify=xyz.abc.com,1"}]
    assert dc.plan_apply("subdomain", "xyz.abc.com", "abc.com", sub) == (
        "forge-subdomain", "xyz", {"target": "cname.vercel-dns.com", "proof": "vc-domain-verify=xyz.abc.com,1"},
        ["main", "proof"])
    apex = [{"host": "abc.com", "type": "A", "value": "76.76.21.21"}]
    www = [{"host": "www.abc.com", "type": "CNAME", "value": "cname.vercel-dns.com"}]
    assert dc.plan_apply("apex", "abc.com", "abc.com", apex, www) == (
        "forge-apex", "", {"ip": "76.76.21.21", "target": "cname.vercel-dns.com"}, ["main", "www"])
    odd = sub + [{"host": "other.abc.com", "type": "TXT", "value": "x"}]
    assert dc.plan_apply("subdomain", "xyz.abc.com", "abc.com", odd) is None
    assert dc.plan_apply("tentoro", "a.apps.tentoro.ai", "tentoro.ai", []) is None


def test_the_link_is_signed_over_exactly_what_the_provider_reads(platform):
    url = dc.apply_url(GODADDY, "forge-subdomain", "abc.com", "xyz", {"target": "cname.vercel-dns.com"}, ["main"],
                       redirect_uri="https://forge.tentoro.ai/org/o/projects/p?settings=domains&dc=xyz.abc.com",
                       state="s1")
    assert url.startswith("https://dcc.godaddy.com/manage/v2/domainTemplates/providers/tentoro.ai/services/forge-subdomain/apply?")
    params = _verify(url, platform)
    assert params["domain"] == "abc.com" and params["host"] == "xyz" and params["target"] == "cname.vercel-dns.com"
    assert params["groupId"] == "main" and params["state"] == "s1" and params["key"] == "_dck1"
    assert params["redirect_uri"].endswith("dc=xyz.abc.com")


def test_discovery_asks_the_domains_own_provider_and_its_template():
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        if req.url.host == "cloudflare-dns.com":
            return httpx.Response(200, json={"Answer": [{"type": 16, "data": '"api.domainconnect.godaddy.com"'}]})
        if req.url.path == "/v2/abc.com/settings":
            return httpx.Response(200, json={"providerId": "godaddy.com", "providerName": "GoDaddy",
                                             "urlSyncUX": "https://dcc.godaddy.com/manage",
                                             "urlAPI": "https://api.domainconnect.godaddy.com"})
        if req.url.path.endswith("/providers/tentoro.ai/services/forge-subdomain"):
            return httpx.Response(200, json={"version": 1})
        return httpx.Response(404)

    async def go(pid, service):
        import os
        os.environ["FORGE_DOMAIN_CONNECT_DOMAIN"] = pid
        try:
            return await real_discover("abc.com", service, transport=httpx.MockTransport(handler))
        finally:
            del os.environ["FORGE_DOMAIN_CONNECT_DOMAIN"]
    found = asyncio.run(go("tentoro.ai", "forge-subdomain"))
    assert found == {"providerId": "godaddy.com", "providerName": "GoDaddy",
                     "urlSyncUX": "https://dcc.godaddy.com/manage", "supported": True}
    assert any("name=_domainconnect.abc.com" in u for u in seen)
    assert asyncio.run(go("tentoro.ai", "forge-apex"))["supported"] is False, "a template not onboarded is no offer"


def test_a_provider_without_domain_connect_offers_nothing():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"Status": 3})

    async def go():
        import os
        os.environ["FORGE_DOMAIN_CONNECT_DOMAIN"] = "tentoro.ai"
        try:
            return await real_discover("abc.com", "forge-subdomain", transport=httpx.MockTransport(handler))
        finally:
            del os.environ["FORGE_DOMAIN_CONNECT_DOMAIN"]
    assert asyncio.run(go()) == {}


# --------------------------------------------------------------------------- #
# In the domain service
# --------------------------------------------------------------------------- #

def test_a_waiting_address_offers_its_provider_and_the_link_applies_exactly_its_records(tmp_path, monkeypatch, platform):
    _offer(monkeypatch)
    root = _project(tmp_path)
    fake = FakeVercel()
    fake.claimed_elsewhere.add("xyz.abc.com")
    svc = _service(root, fake)
    view = run(svc.connect("xyz.abc.com"))
    assert view["connect"] == "GoDaddy"
    out = run(svc.connect_url("xyz.abc.com", "https://forge.tentoro.ai/org/o/projects/p?settings=domains&dc=xyz.abc.com"))
    assert out["provider"] == "GoDaddy"
    params = _verify(out["url"], platform)
    assert params["host"] == "xyz" and params["target"] == "cname.vercel-dns.com"
    assert params["proof"] == "vc-domain-verify=abc" and params["groupId"] == "main,proof", "one approval covers the proof"
    assert params["state"] == dm.read_ledger(root)["domains"]["xyz.abc.com"]["connectState"]
    fake.configured.add("xyz.abc.com")
    fake.claimed_elsewhere.discard("xyz.abc.com")
    assert run(svc.refresh("xyz.abc.com"))["connect"] == "", "a live address offers nothing"


def test_a_bare_domain_is_approved_with_its_www(tmp_path, monkeypatch, platform):
    _offer(monkeypatch)
    root = _project(tmp_path)
    svc = _service(root, FakeVercel())
    run(svc.connect("abc.com"))
    params = _verify(run(svc.connect_url("abc.com", "https://forge.tentoro.ai/x"))["url"], platform)
    assert "host" not in params and params["ip"] == "76.76.21.21" and params["target"] == "cname.vercel-dns.com"
    assert params["groupId"] == "main,www"


def test_no_link_without_the_platform_set_up_or_a_provider_that_holds_the_template(tmp_path, monkeypatch, platform):
    _offer(monkeypatch, {**GODADDY, "supported": False})
    root = _project(tmp_path)
    svc = _service(root, FakeVercel())
    view = run(svc.connect("xyz.abc.com"))
    assert view["connect"] == ""
    with pytest.raises(DomainRefused) as e:
        run(svc.connect_url("xyz.abc.com", "https://forge.tentoro.ai/x"))
    assert "does not offer one-click approval" in str(e.value)
    monkeypatch.delenv("FORGE_DOMAIN_CONNECT_KEY")
    with pytest.raises(DomainRefused) as e:
        run(svc.connect_url("xyz.abc.com", "https://forge.tentoro.ai/x"))
    assert "not set up on this platform" in str(e.value)


def test_smith_answers_with_the_approval_link_when_no_account_is_connected(tmp_path, monkeypatch, platform):
    from services.deploy import dns_accounts, vercel_client
    from services.smith import domain_change
    _offer(monkeypatch)
    root = _project(tmp_path)
    fake = FakeVercel()
    fake.close = lambda: asyncio.sleep(0)
    monkeypatch.setenv("VERCEL_TOKEN", "t")
    monkeypatch.setattr(vercel_client, "VercelClient", lambda *a, **k: fake)

    async def no_accounts(where):
        return []
    monkeypatch.setattr(dns_accounts, "load_for_output_dir", no_accounts)

    async def back(output_dir, project_root, name):
        return f"https://forge.tentoro.ai/org/o/projects/p?settings=domains&dc={name}"
    monkeypatch.setattr(domain_change, "_return_to", back)
    assert domain_change.run(str(root), "connect_domain", change="put it on xyz.abc.com")["applied"]
    out = domain_change.run(str(root), "add_dns_records", change="add the DNS records for me")
    assert out["applied"], out
    assert "Approve xyz.abc.com's records at GoDaddy: https://dcc.godaddy.com/manage/v2/" in out["diff_summary"]


def test_the_submitted_templates_are_the_ones_the_code_applies():
    import json
    from pathlib import Path
    docs = Path(__file__).resolve().parents[3] / "docs" / "domain-connect"
    for t in dc.templates("tentoro.ai"):
        assert json.loads((docs / f"tentoro.ai.{t['serviceId']}.json").read_text()) == t
