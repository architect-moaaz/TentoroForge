"""One-click approval of an address's DNS records, by Domain Connect.

Domain Connect (domainconnect.org) lets the owner approve records at their
own DNS provider instead of copying them or handing Forge a key: Forge sends
them to the provider with a signed link naming Tentoro's template and the
values Vercel asked for; they sign in there, see the records, approve, and
come back. The provider writes the records; Forge's watch sees them land.

What it takes, once, before any provider shows the button:

* `FORGE_DOMAIN_CONNECT_DOMAIN` — Tentoro's provider id, a domain it holds
  (`tentoro.ai`). The public key is published under it.
* `FORGE_DOMAIN_CONNECT_KEY` — the private key that signs each link (PEM),
  kept like any other platform secret. Its public half is published as TXT
  records at `<key host>.<provider id>` (`python -m services.deploy.domain_connect
  key-records <pem>` prints them; never the private key).
* The templates below (`python -m services.deploy.domain_connect templates`)
  submitted to the Domain Connect template repository and onboarded by each
  provider. Until a provider holds them, `discover` reports it unsupported
  and the owner adds the records another way.

The spec: https://github.com/Domain-Connect/spec
"""
from __future__ import annotations

import base64
import os
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

PROVIDER_ENV = "FORGE_DOMAIN_CONNECT_DOMAIN"
KEY_ENV = "FORGE_DOMAIN_CONNECT_KEY"
KEY_HOST_ENV = "FORGE_DOMAIN_CONNECT_KEY_HOST"
DEFAULT_KEY_HOST = "_dck1"

SUBDOMAIN = "forge-subdomain"
APEX = "forge-apex"
#: Where owners come back to after approving (the template's
#: `syncRedirectDomain`). A new platform address means a new template version.
REDIRECT_DOMAINS = ("forge-v3.tentoro.ai",)
#: Vercel's ownership token always starts so; the template keeps the prefix fixed.
PROOF_PREFIX = "vc-domain-verify="
#: The logo providers show beside "Tentoro wants to change your DNS".
LOGO_URL = "https://tentoro.ai/wp-content/uploads/2025/04/Tentoro-Fav-Icon-300x300.png"


def provider_id() -> str:
    """Tentoro's provider id, or "" when Domain Connect is not set up here."""
    return str(os.environ.get(PROVIDER_ENV) or "").strip().lower().strip(".")


def key_host() -> str:
    return str(os.environ.get(KEY_HOST_ENV) or DEFAULT_KEY_HOST).strip() or DEFAULT_KEY_HOST


def private_pem() -> str:
    """The signing key from the environment. An environment file holds one
    line per setting, so the PEM may arrive with its line breaks as `\\n`."""
    pem = str(os.environ.get(KEY_ENV) or "").strip().strip('"')
    return pem.replace("\\n", "\n") if "\\n" in pem and "\n" not in pem else pem


_env_pem = private_pem  # `apply_url`'s own parameter shadows the name


def ready() -> bool:
    """Set up to sign links: a provider id and a key."""
    return bool(provider_id() and private_pem())


def service_for(kind: str) -> str | None:
    return {"subdomain": SUBDOMAIN, "apex": APEX}.get(kind)


# ── the templates ───────────────────────────────────────────────────────


def templates(provider: str, redirect_domains: list[str] | tuple[str, ...] | None = REDIRECT_DOMAINS) -> list[dict]:
    """The two templates Tentoro submits: a subdomain pointed at Vercel, and
    a bare domain with its `www`. The bare domain carries Vercel's `_vercel`
    proof as its own group, applied only when Vercel asks for it, so the
    owner approves once. (A subdomain's proof sits at the bare domain, which
    a template may not reach from a subdomain; that rare case is added by hand.)"""
    common = {
        "providerId": provider, "providerName": "Tentoro", "version": 1,
        "syncPubKeyDomain": provider, "logoUrl": LOGO_URL,
    }
    if redirect_domains:
        common["syncRedirectDomain"] = ",".join(redirect_domains)
    proof = {"groupId": "proof", "type": "TXT", "host": "_vercel", "data": f"{PROOF_PREFIX}%proof%", "ttl": 3600,
             # Beside other Vercel tokens: another account's claim is not ours to replace.
             "txtConflictMatchingMode": "None"}
    return [
        {**common, "serviceId": SUBDOMAIN, "serviceName": "Forge app on a subdomain", "hostRequired": True,
         "description": "Points a subdomain at an application built with Forge and hosted on Vercel.",
         "variableDescription": "target: the address Vercel serves the application from",
         "records": [{"type": "CNAME", "host": "@", "pointsTo": "%target%", "ttl": 3600}]},
        {**common, "serviceId": APEX, "serviceName": "Forge app on a domain",
         "description": "Points a domain, and its www, at an application built with Forge and hosted on Vercel.",
         "variableDescription": "ip: Vercel's address; target: the address Vercel serves www from; proof: Vercel's ownership token",
         "records": [{"groupId": "main", "type": "A", "host": "@", "pointsTo": "%ip%", "ttl": 3600},
                     {"groupId": "www", "type": "CNAME", "host": "www", "pointsTo": "%target%", "ttl": 3600},
                     proof]},
    ]


def plan_apply(kind: str, name: str, root: str, records: list[dict],
               companion: list[dict] | None = None) -> tuple[str, str, dict[str, str], list[str]] | None:
    """`(service, host, values, groups)` that apply exactly these records, or
    None when they are not what a template writes (the owner adds them)."""
    service = service_for(kind)
    if not service or not (name == root or name.endswith(f".{root}")):
        return None
    values: dict[str, str] = {}
    groups: list[str] = []
    for r in records:
        host, rtype, value = str(r.get("host")), str(r.get("type")), str(r.get("value") or "").rstrip(".")
        if (kind == "apex" and rtype == "TXT" and host == f"_vercel.{root}" and value.startswith(PROOF_PREFIX)
                and "proof" not in values):
            values["proof"] = value[len(PROOF_PREFIX):]
        elif kind == "subdomain" and rtype == "CNAME" and host == name and "target" not in values:
            values["target"] = value
        elif kind == "apex" and rtype == "A" and host == name:
            values.setdefault("ip", value)  # Vercel's anycast address; one is enough
        else:
            return None
    if kind == "subdomain" and "target" not in values:
        return None
    if kind == "apex" and "ip" in values:
        groups.append("main")
        for r in companion or []:
            if r.get("type") == "CNAME" and r.get("host") == f"www.{root}":
                values["target"] = str(r.get("value") or "").rstrip(".")
                groups.append("www")
                break
    if "proof" in values:
        groups.append("proof")
    if kind == "apex" and not groups:
        return None
    host = "" if name == root else name[: -len(root) - 1]
    return service, host, values, groups


# ── signing ─────────────────────────────────────────────────────────────


def _private_key(pem: str):
    from cryptography.hazmat.primitives import serialization
    return serialization.load_pem_private_key(pem.encode(), password=None)


def sign(query: str, private_pem: str) -> str:
    """RS256 over the query string, base64 — what the provider checks against
    the public key published at `<key host>.<provider id>`."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    sig = _private_key(private_pem).sign(query.encode(), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(sig).decode()


def public_key_records(pem: str, chunk: int = 200) -> list[str]:
    """The TXT records that publish the public key (`p=1,a=RS256,d=…`), from
    a public or a private PEM. Only the public half is ever returned."""
    from cryptography.hazmat.primitives import serialization
    text = pem.strip()
    if "PRIVATE KEY" in text:
        public = _private_key(text).public_key()
    else:
        public = serialization.load_pem_public_key(text.encode())
    der = public.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    data = base64.b64encode(der).decode()
    parts = [data[i:i + chunk] for i in range(0, len(data), chunk)]
    return [f"p={i},a=RS256,d={part}" for i, part in enumerate(parts, start=1)]


def apply_url(settings: dict, service: str, root: str, host: str, values: dict[str, str], groups: list[str], *,
              redirect_uri: str, state: str, private_pem: str | None = None) -> str:
    """The signed link that takes the owner to their provider to approve."""
    provider = provider_id()
    pairs: list[tuple[str, str]] = [("domain", root)]
    if host:
        pairs.append(("host", host))
    pairs += sorted(values.items())
    if groups:  # a template of one group takes none
        pairs.append(("groupId", ",".join(groups)))
    pairs += [("redirect_uri", redirect_uri), ("state", state)]
    query = "&".join(f"{k}={quote(v, safe='')}" for k, v in pairs)
    pem = private_pem if private_pem is not None else _env_pem()
    sig = sign(query, pem)
    base = str(settings["urlSyncUX"]).rstrip("/")
    return (f"{base}/v2/domainTemplates/providers/{quote(provider, safe='')}/services/{quote(service, safe='')}/apply"
            f"?{query}&key={quote(key_host(), safe='')}&sig={quote(sig, safe='')}")


# ── discovery ───────────────────────────────────────────────────────────


async def discover(root: str, service: str, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """Whether the provider running `root`'s DNS takes Tentoro's `service`:
    `{providerId, providerName, urlSyncUX, supported}`, or {} when it does not
    speak Domain Connect. Never raises: it is an offer, not a requirement."""
    provider = provider_id()
    if not provider:
        return {}
    try:
        async with httpx.AsyncClient(timeout=8.0, transport=transport) as c:
            r = await c.get("https://cloudflare-dns.com/dns-query", params={"name": f"_domainconnect.{root}", "type": "TXT"},
                            headers={"accept": "application/dns-json"})
            answers = [str(a.get("data") or "").strip().strip('"') for a in (r.json().get("Answer") or [])
                       if a.get("type") == 16]
            # A URL prefix such as `api.domainconnect.godaddy.com` (it may carry a path).
            api_host = next((a for a in answers if a), "").split("://")[-1].strip("/")
            if not api_host or any(ch.isspace() for ch in api_host):
                return {}
            r = await c.get(f"https://{api_host}/v2/{root}/settings")
            if r.status_code != 200:
                return {}
            s = r.json()
            if not s.get("urlSyncUX") or not s.get("urlAPI") or urlsplit(str(s["urlSyncUX"])).scheme != "https":
                return {}
            r = await c.get(f"{str(s['urlAPI']).rstrip('/')}/v2/domainTemplates/providers/{provider}/services/{service}")
            return {"providerId": str(s.get("providerId") or ""),
                    "providerName": str(s.get("providerDisplayName") or s.get("providerName") or ""),
                    "urlSyncUX": str(s["urlSyncUX"]), "supported": 200 <= r.status_code < 300}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return {}


__all__ = ["APEX", "SUBDOMAIN", "apply_url", "discover", "plan_apply", "provider_id", "public_key_records", "ready",
           "service_for", "sign", "templates"]


if __name__ == "__main__":  # pragma: no cover — run by hand when registering
    import json
    import sys
    if len(sys.argv) >= 2 and sys.argv[1] == "templates":
        pid = provider_id() or (sys.argv[2] if len(sys.argv) > 2 else "tentoro.ai")
        print(json.dumps(templates(pid), indent=2))
    elif len(sys.argv) == 3 and sys.argv[1] == "key-records":
        with open(sys.argv[2], encoding="utf-8") as fh:
            rows = public_key_records(fh.read())
        print(f"Publish these TXT records at {key_host()}.{provider_id() or '<provider id>'}:")
        for row in rows:
            print(f'  "{row}"')
    else:
        print("usage: python -m services.deploy.domain_connect templates | key-records <pem file>")
