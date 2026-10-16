"""Forge writes an address's DNS records itself, at the owner's DNS provider.

The owner connects their DNS provider once, in Settings → Integrations, the
way email or payments connect: the key stays in the platform store and never
enters an app's definition. Then "Add the records for me" (App settings →
Domains, or asking Smith) finds which connected account holds the domain,
compares what is there with what Vercel asks for, and writes only what is
missing.

The safety rules (`plan`):

* A record that is already there is left alone.
* Nothing is ever overwritten silently. A record in the way — an A or AAAA
  record at the address pointing somewhere else, or any record where a CNAME
  must go — is a conflict: nothing is written for that address, and the
  owner is told what is there. They may then ask to replace it.
* Even when asked, mail and proof records (MX, TXT, SRV, CAA, NS, SOA) are
  never replaced; the owner is told to choose another address instead.
* A TXT proof sits beside other TXT records; it never conflicts.
* Records are never proxied (Cloudflare's orange cloud would stop Vercel
  issuing the certificate).

What Forge wrote is kept in `.forge/domains.json` (`written`), so removing
the address takes away exactly those records and nothing else.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)

#: Record types a request to replace never touches.
NEVER_REPLACED = frozenset({"MX", "TXT", "SRV", "CAA", "NS", "SOA"})
#: Types that decide where an address's web traffic goes.
_WEB = frozenset({"A", "AAAA", "CNAME", "ALIAS", "ANAME"})


class DnsRefused(ValueError):
    """Records cannot be written; the message says why, in the owner's words."""


@dataclass(frozen=True)
class Record:
    host: str           # fully qualified, no trailing dot: app.acme.com
    type: str           # A, CNAME, TXT, ...
    value: str
    id: str = ""        # the provider's id, when it has one


@dataclass
class Plan:
    """What writing an address's records would do."""
    add: list[Record] = field(default_factory=list)
    there: list[Record] = field(default_factory=list)
    conflicts: list[tuple[Record, Record]] = field(default_factory=list)  # (wanted, in the way)
    #: In the way and never replaced, even when asked.
    blocked: list[Record] = field(default_factory=list)


def _norm(v: str) -> str:
    return str(v or "").strip().strip('"').rstrip(".").lower()


def plan(wanted: list[Record], existing: list[Record], *, replace: bool = False) -> Plan:
    """Compare the records Vercel asks for with what the zone holds."""
    out = Plan()

    def same(a: Record, b: Record) -> bool:
        return _norm(a.host) == _norm(b.host) and a.type == b.type and _norm(a.value) == _norm(b.value)

    for w in wanted:
        at = [e for e in existing if _norm(e.host) == _norm(w.host)]
        if any(same(e, w) for e in at):
            out.there.append(w)
            continue
        out.add.append(w)
        if w.type == "TXT":
            continue  # a proof sits beside other TXT records
        # A CNAME stands alone at its name: anything there is in the way. An
        # A record shares its name with mail and proofs, not with other web
        # records — except the A records that are themselves wanted.
        in_way = [e for e in at if (w.type == "CNAME" or e.type in _WEB)
                  and not any(same(e, x) for x in wanted)]
        for e in in_way:
            if e.type in NEVER_REPLACED:
                if e not in out.blocked:
                    out.blocked.append(e)
            elif not any(c[1] == e for c in out.conflicts):
                out.conflicts.append((w, e))
    if out.blocked or (out.conflicts and not replace):
        out.add = []
    return out


def said_conflicts(p: Plan, provider: str) -> str:
    if p.blocked:
        rows = "; ".join(f"{e.type} {e.host} → {e.value}" for e in p.blocked)
        return (f"I did not change anything: {rows} is there, and it carries mail or proof records I never "
                "replace. Choose another address, such as app.<your domain>.")
    rows = "; ".join(f"{e.type} {e.host} → {e.value}" for _, e in p.conflicts)
    return (f"I did not change anything: {rows} is already there at {provider} and points elsewhere. "
            "Remove it there, or tell me to replace it.")


class DnsProvider(Protocol):
    label: str

    async def zone_for(self, name: str) -> str | None: ...
    async def records(self, zone: str, host: str) -> list[Record]: ...
    async def create(self, zone: str, rec: Record) -> str: ...
    async def delete(self, zone: str, rec: Record) -> None: ...
    async def close(self) -> None: ...


def _candidates(name: str) -> list[str]:
    """`app.acme.co.uk` → [app.acme.co.uk, acme.co.uk, co.uk]: the zone is the
    longest suffix the account holds."""
    labels = name.split(".")
    return [".".join(labels[i:]) for i in range(len(labels) - 1)]


def _raise(r: httpx.Response, what: str) -> None:
    if r.status_code >= 400:
        # Never the request (it carries the key); the provider's own words.
        raise RuntimeError(f"{what} failed: status={r.status_code} body={r.text[:300]}")


# ── Cloudflare ──────────────────────────────────────────────────────────


class Cloudflare:
    label = "Cloudflare"
    BASE = "https://api.cloudflare.com/client/v4"

    def __init__(self, token: str, transport: httpx.AsyncBaseTransport | None = None):
        self._c = httpx.AsyncClient(base_url=self.BASE, timeout=20.0, transport=transport,
                                    headers={"Authorization": f"Bearer {token}"})
        self._zones: dict[str, str] = {}

    async def zone_for(self, name: str) -> str | None:
        for cand in _candidates(name):
            r = await self._c.get("/zones", params={"name": cand})
            _raise(r, "Cloudflare zones")
            rows = r.json().get("result") or []
            if rows:
                self._zones[cand] = str(rows[0]["id"])
                return cand
        return None

    async def _zid(self, zone: str) -> str:
        if zone not in self._zones and await self.zone_for(zone) != zone:
            raise DnsRefused(f"Cloudflare does not hold {zone}.")
        return self._zones[zone]

    async def records(self, zone: str, host: str) -> list[Record]:
        r = await self._c.get(f"/zones/{await self._zid(zone)}/dns_records", params={"name": host, "per_page": 100})
        _raise(r, "Cloudflare records")
        return [Record(host=_norm(x["name"]), type=str(x["type"]).upper(), value=str(x["content"]), id=str(x["id"]))
                for x in r.json().get("result") or []]

    async def create(self, zone: str, rec: Record) -> str:
        body: dict[str, Any] = {"type": rec.type, "name": rec.host, "content": rec.value, "ttl": 1}
        if rec.type in ("A", "AAAA", "CNAME"):
            body["proxied"] = False
        r = await self._c.post(f"/zones/{await self._zid(zone)}/dns_records", json=body)
        _raise(r, f"Cloudflare create {rec.type} {rec.host}")
        return str(r.json()["result"]["id"])

    async def delete(self, zone: str, rec: Record) -> None:
        r = await self._c.delete(f"/zones/{await self._zid(zone)}/dns_records/{rec.id}")
        if r.status_code != 404:
            _raise(r, f"Cloudflare delete {rec.type} {rec.host}")

    async def close(self) -> None:
        await self._c.aclose()


# ── GoDaddy ─────────────────────────────────────────────────────────────


class GoDaddy:
    label = "GoDaddy"
    BASE = "https://api.godaddy.com/v1"

    def __init__(self, key: str, secret: str, transport: httpx.AsyncBaseTransport | None = None):
        self._c = httpx.AsyncClient(base_url=self.BASE, timeout=20.0, transport=transport,
                                    headers={"Authorization": f"sso-key {key}:{secret}"})

    async def zone_for(self, name: str) -> str | None:
        for cand in _candidates(name):
            r = await self._c.get(f"/domains/{cand}")
            if r.status_code in (403, 404, 422):
                continue
            _raise(r, "GoDaddy domain")
            return cand
        return None

    @staticmethod
    def _rel(zone: str, host: str) -> str:
        return "@" if host == zone else host[: -len(zone) - 1]

    async def records(self, zone: str, host: str) -> list[Record]:
        rel = self._rel(zone, host)
        r = await self._c.get(f"/domains/{zone}/records")
        _raise(r, "GoDaddy records")
        return [Record(host=host, type=str(x["type"]).upper(), value=str(x.get("data") or ""),
                       id=f"{x['type']}|{rel}|{x.get('data')}")
                for x in r.json() or [] if str(x.get("name")) == rel]

    async def create(self, zone: str, rec: Record) -> str:
        rel = self._rel(zone, rec.host)
        r = await self._c.patch(f"/domains/{zone}/records",
                                json=[{"type": rec.type, "name": rel, "data": rec.value, "ttl": 600}])
        _raise(r, f"GoDaddy add {rec.type} {rec.host}")
        return f"{rec.type}|{rel}|{rec.value}"

    async def delete(self, zone: str, rec: Record) -> None:
        rtype, rel, value = (rec.id.split("|", 2) + ["", "", ""])[:3] if rec.id else (rec.type, self._rel(zone, rec.host), rec.value)
        r = await self._c.get(f"/domains/{zone}/records/{rtype}/{rel}")
        _raise(r, "GoDaddy records")
        keep = [x for x in r.json() or [] if _norm(x.get("data")) != _norm(value)]
        if keep:
            r = await self._c.put(f"/domains/{zone}/records/{rtype}/{rel}", json=keep)
        else:
            r = await self._c.delete(f"/domains/{zone}/records/{rtype}/{rel}")
        if r.status_code != 404:
            _raise(r, f"GoDaddy delete {rtype} {rec.host}")

    async def close(self) -> None:
        await self._c.aclose()


# ── Route 53 ────────────────────────────────────────────────────────────


class Route53:
    """boto3, run off the event loop. Route 53 keeps one record set per name
    and type, so adding a value to an existing set is a change of that set."""
    label = "Route 53"

    def __init__(self, access_key: str, secret_key: str, client: Any = None):
        if client is None:
            import boto3
            client = boto3.client("route53", aws_access_key_id=access_key, aws_secret_access_key=secret_key)
        self._c = client
        self._zones: dict[str, str] = {}

    async def _call(self, fn: str, **kw: Any) -> dict:
        return await asyncio.to_thread(getattr(self._c, fn), **kw)

    async def zone_for(self, name: str) -> str | None:
        for cand in _candidates(name):
            out = await self._call("list_hosted_zones_by_name", DNSName=cand, MaxItems="1")
            for z in out.get("HostedZones") or []:
                if _norm(z["Name"]) == cand and not (z.get("Config") or {}).get("PrivateZone"):
                    self._zones[cand] = str(z["Id"]).split("/")[-1]
                    return cand
        return None

    async def _zid(self, zone: str) -> str:
        if zone not in self._zones and await self.zone_for(zone) != zone:
            raise DnsRefused(f"Route 53 does not hold {zone}.")
        return self._zones[zone]

    async def _sets(self, zone: str, host: str) -> list[dict]:
        out = await self._call("list_resource_record_sets", HostedZoneId=await self._zid(zone),
                               StartRecordName=host, MaxItems="20")
        return [s for s in out.get("ResourceRecordSets") or [] if _norm(s["Name"]) == host]

    async def records(self, zone: str, host: str) -> list[Record]:
        rows: list[Record] = []
        for s in await self._sets(zone, host):
            if s.get("AliasTarget"):
                rows.append(Record(host=host, type="ALIAS", value=_norm(s["AliasTarget"].get("DNSName")),
                                   id=f"{s['Type']}|alias"))
            for v in s.get("ResourceRecords") or []:
                rows.append(Record(host=host, type=str(s["Type"]), value=str(v["Value"]), id=str(s["Type"])))
        return rows

    async def _put(self, zone: str, host: str, rtype: str, values: list[str]) -> None:
        action = "UPSERT" if values else "DELETE"
        if not values:
            current = next((s for s in await self._sets(zone, host) if s["Type"] == rtype), None)
            if current is None:
                return
            change = {"Action": "DELETE", "ResourceRecordSet": current}
        else:
            change = {"Action": action, "ResourceRecordSet": {
                "Name": host, "Type": rtype, "TTL": 300, "ResourceRecords": [{"Value": v} for v in values]}}
        await self._call("change_resource_record_sets", HostedZoneId=await self._zid(zone),
                         ChangeBatch={"Comment": "Forge", "Changes": [change]})

    async def create(self, zone: str, rec: Record) -> str:
        have = [r.value for r in await self.records(zone, rec.host) if r.type == rec.type]
        value = f'"{rec.value}"' if rec.type == "TXT" and not rec.value.startswith('"') else rec.value
        await self._put(zone, rec.host, rec.type, [*have, value])
        return f"{rec.type}|{value}"

    async def delete(self, zone: str, rec: Record) -> None:
        rtype, _, value = (rec.id or f"{rec.type}|{rec.value}").partition("|")
        if value == "alias":
            current = next((s for s in await self._sets(zone, rec.host) if s["Type"] == rtype), None)
            if current is not None:
                await self._call("change_resource_record_sets", HostedZoneId=await self._zid(zone),
                                 ChangeBatch={"Changes": [{"Action": "DELETE", "ResourceRecordSet": current}]})
            return
        value = value or rec.value
        have = [r.value for r in await self.records(zone, rec.host) if r.type == rtype]
        await self._put(zone, rec.host, rtype, [v for v in have if _norm(v) != _norm(value)])

    async def close(self) -> None:
        return None


# ── where an address's DNS is ───────────────────────────────────────────

_NAMESERVERS = (("ns.cloudflare.com", "Cloudflare"), ("awsdns", "Route 53"), ("domaincontrol.com", "GoDaddy"),
                ("vercel-dns.com", "Vercel"), ("googledomains.com", "Squarespace"), ("squarespacedns", "Squarespace"),
                ("registrar-servers.com", "Namecheap"), ("ui-dns.", "IONOS"), ("azure-dns", "Azure DNS"))


async def dns_host(name: str, transport: httpx.AsyncBaseTransport | None = None) -> str:
    """Who runs `name`'s DNS, from its nameservers (over DNS-over-HTTPS):
    "Cloudflare", "Route 53", "GoDaddy", …, or "" when it cannot be told."""
    async with httpx.AsyncClient(timeout=8.0, transport=transport) as c:
        for cand in _candidates(name):
            try:
                r = await c.get("https://cloudflare-dns.com/dns-query", params={"name": cand, "type": "NS"},
                                headers={"accept": "application/dns-json"})
                answers = [str(a.get("data") or "").lower() for a in (r.json().get("Answer") or []) if a.get("type") == 2]
            except (httpx.HTTPError, ValueError):
                return ""
            if answers:
                for needle, label in _NAMESERVERS:
                    if any(needle in a for a in answers):
                        return label
                return ""
    return ""


__all__ = ["Cloudflare", "DnsProvider", "DnsRefused", "GoDaddy", "NEVER_REPLACED", "Plan", "Record", "Route53",
           "dns_host", "plan", "said_conflicts"]
