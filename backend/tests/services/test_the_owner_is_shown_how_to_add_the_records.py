"""The owner is told how to add an address's records at their own DNS
provider — the screens, the name to type, the value to paste — and, when
the address does not answer, what exactly is wrong in its live DNS.
"""
from __future__ import annotations

import asyncio

import httpx

from services.deploy import dns_guides as g
from tests.services.test_an_app_answers_at_its_own_address import (  # noqa: F401 — the fixture is used
    FakeVercel, _no_real_probe, _project, _service, run)

real_diagnose = g.diagnose  # the fixture stands it in for everything else

SUB = [{"host": "xyz.abc.com", "type": "CNAME", "value": "cname.vercel-dns.com", "why": ""}]
APEX = [{"host": "abc.com", "type": "A", "value": "76.76.21.21", "why": ""},
        {"host": "_vercel.abc.com", "type": "TXT", "value": "vc-domain-verify=abc.com,1", "why": ""}]


def test_every_guide_names_the_screens_and_the_owners_own_values():
    out = g.guides(SUB, "abc.com", "GoDaddy")
    assert out["provider"] == "GoDaddy" and out["providers"][-1] == "Another provider"
    for provider in out["providers"]:
        text = " ".join(out["steps"][provider])
        assert "cname.vercel-dns.com" in text and " xyz " in f"{text} ", provider
        assert "xyz.abc.com ·" not in text, f"{provider}: the name to type is the short one"
    assert "My Products" in " ".join(out["steps"]["GoDaddy"])
    assert "DNS only (grey cloud)" in " ".join(out["steps"]["Cloudflare"])
    assert "Advanced DNS" in " ".join(out["steps"]["Namecheap"])
    assert g.guides(SUB, "abc.com", "Some Registrar")["provider"] == "Another provider"


def test_the_tips_name_the_mistakes_people_make():
    tips = " ".join(g.guides(SUB, "abc.com")["tips"]["Cloudflare"])
    assert "xyz.abc.com.abc.com" in tips, "the doubled name"
    assert "delete it first" in tips, "a record in the way"
    assert "grey cloud" in tips
    apex = " ".join(g.guides(APEX, "abc.com")["tips"]["GoDaddy"])
    assert "parking page" in apex and "Leave MX and TXT" in apex, "the bare domain keeps its email"
    route53 = " ".join(g.guides(APEX, "abc.com")["steps"]["Route 53"])
    assert "(leave blank)" in route53 and "_vercel" in route53


def _dns(answers: dict[tuple[str, str], list[tuple[int, str]]]):
    def handler(req: httpx.Request) -> httpx.Response:
        key = (req.url.params["name"], req.url.params["type"])
        return httpx.Response(200, json={"Answer": [{"type": t, "data": d} for t, d in answers.get(key, [])]})
    return httpx.MockTransport(handler)


def _diag(name, kind, records, answers):
    return asyncio.run(real_diagnose(name, kind, "abc.com", records, transport=_dns(answers)))


def test_an_old_record_in_the_way_is_named():
    found = _diag("xyz.abc.com", "subdomain", SUB, {("xyz.abc.com", "A"): [(1, "203.0.113.7")]})
    assert found[0]["code"] == "in-the-way" and "203.0.113.7" in found[0]["says"] and "Delete it" in found[0]["says"]
    found = _diag("xyz.abc.com", "subdomain", SUB, {("xyz.abc.com", "CNAME"): [(5, "old.host.net.")]})
    assert found[0]["code"] == "other-cname" and "old.host.net" in found[0]["says"]
    found = _diag("abc.com", "apex", APEX, {("abc.com", "A"): [(1, "198.51.100.4")]})
    assert found[0]["code"] == "in-the-way" and "parking page" in found[0]["says"]


def test_cloudflares_proxy_is_named():
    found = _diag("xyz.abc.com", "subdomain", SUB, {("xyz.abc.com", "A"): [(1, "104.21.5.9"), (1, "172.67.1.2")]})
    assert found[0]["code"] == "proxied" and "grey cloud" in found[0]["says"]


def test_the_doubled_name_is_named():
    found = _diag("xyz.abc.com", "subdomain", SUB,
                  {("xyz.abc.com.abc.com", "CNAME"): [(5, "cname.vercel-dns.com.")]})
    assert found[0]["code"] == "doubled-name" and "type only xyz" in found[0]["says"]


def test_a_caa_record_that_blocks_the_certificate_is_named():
    found = _diag("xyz.abc.com", "subdomain", SUB, {("xyz.abc.com", "CNAME"): [(5, "cname.vercel-dns.com.")],
                                                  ("abc.com", "CAA"): [(257, '0 issue "digicert.com"')]})
    assert [f["code"] for f in found] == ["caa"] and 'letsencrypt.org' in found[0]["says"]
    allowed = _diag("xyz.abc.com", "subdomain", SUB, {("xyz.abc.com", "CNAME"): [(5, "cname.vercel-dns.com.")],
                                                    ("abc.com", "CAA"): [(257, '0 issue "letsencrypt.org"')]})
    assert allowed == []


def test_the_panel_and_smith_carry_the_guide_and_the_fault(tmp_path, monkeypatch):
    from services.deploy import dns_providers
    from services.smith import domain_change

    async def at_godaddy(name, transport=None):
        return "GoDaddy"

    async def in_the_way(name, kind, root, records, transport=None):
        return [{"code": "in-the-way", "says": f"{name} already has an A record (203.0.113.7). Delete it."}]
    monkeypatch.setattr(dns_providers, "dns_host", at_godaddy)
    monkeypatch.setattr(g, "diagnose", in_the_way)
    root = _project(tmp_path)
    svc = _service(root, FakeVercel())
    view = run(svc.connect("xyz.abc.com"))
    assert view["guide"]["provider"] == "GoDaddy" and "My Products" in view["guide"]["steps"]["GoDaddy"][0]
    assert view["problems"][0]["code"] == "in-the-way"
    assert view["detail"].startswith("xyz.abc.com already has an A record"), "the fault, not 'not there yet'"
    said = domain_change._said(view)
    assert "How to add it at GoDaddy" in said and "My Products" in said and "already has an A record" in said


def test_an_old_ipv6_record_left_beside_the_new_a_record_is_named():
    """Cloudflare's Domain Connect apply replaces the bare domain's A records
    and keeps an AAAA: visitors on IPv6 reach the old host (Cloudflare,
    2026-10-17)."""
    found = _diag("abc.com", "apex", APEX, {("abc.com", "A"): [(1, "76.76.21.21")],
                                            ("abc.com", "AAAA"): [(28, "2001:db8::7")]})
    assert [f["code"] for f in found] == ["ipv6-in-the-way"] and "2001:db8::7" in found[0]["says"]
    behind_cname = _diag("xyz.abc.com", "subdomain", SUB,
                         {("xyz.abc.com", "CNAME"): [(5, "cname.vercel-dns.com.")],
                          ("xyz.abc.com", "AAAA"): [(5, "cname.vercel-dns.com."), (28, "2001:db8::9")]})
    assert behind_cname == [], "the AAAA answers behind a CNAME are the target's"
