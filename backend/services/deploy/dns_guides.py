"""How to add an address's records at the owner's DNS provider, in their
words, and what is wrong when the address does not answer.

`guides` writes the steps for each common provider with the owner's own
values filled in (the name to type, the value to paste), plus the mistakes
people make there. `diagnose` looks at the address's live DNS and names a
specific fault — a record already in the way, Cloudflare's proxy switched
on, the record added under the doubled name, a CAA record that blocks the
certificate — so the panel and Smith say the fix, not "not there yet".

Provider menus move; the steps name the screens as the providers call them
today and fall back to the generic steps for anyone else.
"""
from __future__ import annotations

import ipaddress
from typing import Any

import httpx

#: The providers a guide is written for, in the order the picker shows them.
PROVIDERS = ("GoDaddy", "Cloudflare", "Namecheap", "Squarespace", "IONOS", "Route 53")
GENERIC = "Another provider"

#: Vercel's certificates come from Let's Encrypt; a CAA record must allow it.
CERT_AUTHORITY = "letsencrypt.org"

#: Cloudflare's own address ranges: an address answering from one of these
#: is proxied (orange cloud), and Vercel cannot issue its certificate.
_CLOUDFLARE_RANGES = tuple(ipaddress.ip_network(n) for n in (
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22", "141.101.64.0/18",
    "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20", "197.234.240.0/22", "198.41.128.0/17",
    "162.158.0.0/15", "104.16.0.0/13", "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22"))


def relative(host: str, root: str) -> str:
    """`xyz.abc.com` under `abc.com` → `xyz`; the domain itself → `@`."""
    host, root = host.rstrip(".").lower(), root.rstrip(".").lower()
    if host == root:
        return "@"
    return host[: -len(root) - 1] if host.endswith("." + root) else host


def _record_lines(records: list[dict], root: str, *, name_label: str, value_label: str, apex: str = "@",
                  extra: str = "") -> list[str]:
    out = []
    for r in records:
        rel = relative(str(r["host"]), root)
        shown = apex if rel == "@" else rel
        out.append(f"Type {r['type']} · {name_label} {shown} · {value_label} {r['value']}{extra}")
    return out


def _steps(provider: str, records: list[dict], root: str) -> list[str]:
    if provider == "GoDaddy":
        return ["Sign in at godaddy.com and open My Products.",
                f"Next to {root}, choose DNS (or Manage DNS).",
                "Select Add New Record and enter:",
                *_record_lines(records, root, name_label="Name", value_label="Value"),
                "Leave TTL as it is and select Save. Add each record the same way."]
    if provider == "Cloudflare":
        return ["Sign in at dash.cloudflare.com and choose the account, then the domain " + root + ".",
                "Open DNS → Records and select Add record.",
                *_record_lines(records, root, name_label="Name", value_label="Target/Content",
                               extra=" · Proxy status: DNS only (grey cloud)"),
                "Select Save. Add each record the same way."]
    if provider == "Namecheap":
        return ["Sign in at namecheap.com and open Domain List.",
                f"Select Manage next to {root}, then the Advanced DNS tab.",
                "Under Host Records select Add New Record and enter:",
                *_record_lines(records, root, name_label="Host", value_label="Value"),
                "Leave TTL on Automatic and select the tick to save."]
    if provider == "Squarespace":
        return ["Sign in at account.squarespace.com and open Domains.",
                f"Select {root}, then DNS (DNS Settings).",
                "Under Custom records select Add record and enter:",
                *_record_lines(records, root, name_label="Host", value_label="Data"),
                "Select Save."]
    if provider == "IONOS":
        return ["Sign in at ionos.com and open Domains & SSL.",
                f"Select {root}, then the DNS tab, and choose Add record.",
                *_record_lines(records, root, name_label="Host name", value_label="Points to"),
                "Select Save. Add each record the same way."]
    if provider == "Route 53":
        return ["Sign in to the AWS console and open Route 53 → Hosted zones.",
                f"Select {root} and choose Create record.",
                *_record_lines(records, root, name_label="Record name", value_label="Value", apex="(leave blank)"),
                "Leave TTL at 300 and choose Create records."]
    return [f"Sign in where {root}'s DNS is managed: usually where you bought the domain, or ask your IT team.",
            "Find the page called DNS, DNS records, DNS zone or Zone editor, and add a record for each line:",
            *_record_lines(records, root, name_label="Name/Host", value_label="Value/Points to"),
            "Save the records."]


def _tips(provider: str, records: list[dict], root: str) -> list[str]:
    tips: list[str] = []
    rels = [relative(str(r["host"]), root) for r in records if r.get("type") in ("CNAME", "A")]
    sub = next((r for r in rels if r != "@"), "")
    if sub:
        tips.append(f"Type only {sub} as the name: the provider adds .{root} itself. Typing the whole address "
                    f"makes {sub}.{root}.{root}.")
        tips.append(f"If {sub} already has a record (A, AAAA or CNAME), delete it first: nothing else can sit "
                    "beside a CNAME.")
    if "@" in rels:
        tips.append(f"Delete any other A or AAAA record on {root} itself (often a parking page), or visitors "
                    "may reach the old site. Leave MX and TXT records alone; they carry your email.")
    if provider == "Cloudflare":
        tips.append("Proxy status must be DNS only (grey cloud). With the orange cloud on, the certificate "
                    "cannot be issued.")
    tips.append("It usually works within minutes; some providers take up to an hour, and it can take up to "
                "two days. Press Check now any time.")
    return tips


def guides(records: list[dict], root: str, detected: str = "") -> dict[str, Any]:
    """`{provider, providers, steps: {provider: [...]}, tips: {provider: [...]}}`
    for the panel: the detected provider first, every guide ready."""
    names = [*PROVIDERS, GENERIC]
    return {"provider": detected if detected in PROVIDERS else GENERIC,
            "providers": names,
            "steps": {p: _steps(p, records, root) for p in names},
            "tips": {p: _tips(p, records, root) for p in names}}


# ── what is wrong ───────────────────────────────────────────────────────


async def _doh(c: httpx.AsyncClient, name: str, rtype: str) -> list[tuple[int, str]]:
    r = await c.get("https://cloudflare-dns.com/dns-query", params={"name": name, "type": rtype},
                    headers={"accept": "application/dns-json"})
    return [(int(a.get("type") or 0), str(a.get("data") or "").strip('"').rstrip(".").lower())
            for a in (r.json().get("Answer") or [])]


def _cloudflare_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in _CLOUDFLARE_RANGES)


async def diagnose(name: str, kind: str, root: str, records: list[dict],
                   transport: httpx.AsyncBaseTransport | None = None) -> list[dict]:
    """Specific faults in the address's live DNS: `[{code, says}]`, the most
    useful first, or [] when nothing particular is wrong (it may just not
    have spread yet). Never raises."""
    found: list[dict] = []
    wanted_cname = next((str(r["value"]).rstrip(".").lower() for r in records
                         if r.get("type") == "CNAME" and str(r.get("host")) == name), "")
    wanted_a = {str(r["value"]) for r in records if r.get("type") == "A" and str(r.get("host")) == name}
    try:
        async with httpx.AsyncClient(timeout=8.0, transport=transport) as c:
            cname = [d for t, d in await _doh(c, name, "CNAME") if t == 5]
            a = [d for t, d in await _doh(c, name, "A") if t == 1]
            if a and all(_cloudflare_ip(ip) for ip in a) and not (wanted_a & set(a)):
                found.append({"code": "proxied", "says":
                              f"{name} is behind Cloudflare's proxy (orange cloud). In Cloudflare → DNS → Records, "
                              "set its Proxy status to DNS only (grey cloud)."})
            elif kind == "subdomain" and wanted_cname:
                if cname and cname[0] != wanted_cname:
                    found.append({"code": "other-cname", "says":
                                  f"{name} points at {cname[0]}, not {wanted_cname}. Change that CNAME's value to "
                                  f"{wanted_cname}."})
                elif not cname and a:
                    found.append({"code": "in-the-way", "says":
                                  f"{name} already has an A record ({', '.join(a[:2])}). Delete it, then add the "
                                  f"CNAME to {wanted_cname}."})
            elif kind == "apex" and wanted_a and a and not (wanted_a & set(a)):
                found.append({"code": "in-the-way", "says":
                              f"{name} still points at {', '.join(a[:2])}. Delete those A records (often a parking "
                              f"page) and add the A record to {', '.join(sorted(wanted_a))}."})
            # AN OLD IPv6 RECORD stays when only the A record is replaced (a
            # Domain Connect apply at Cloudflare keeps it): visitors on IPv6 still
            # reach the old host, and Vercel may not issue the certificate.
            # Behind a CNAME the AAAA answers are the target's, not in the way.
            if not cname and not any(f["code"] == "proxied" for f in found):
                aaaa = [d for t, d in await _doh(c, name, "AAAA") if t == 28]
                if aaaa:
                    found.append({"code": "ipv6-in-the-way", "says":
                                  f"{name} also has an AAAA (IPv6) record ({', '.join(aaaa[:2])}). Delete it: "
                                  "visitors on IPv6 still reach the old host, and Vercel may not issue the "
                                  "certificate while it is there."})
            if kind == "subdomain" and not cname and not a:
                doubled = f"{name}.{root}"
                if [d for t, d in await _doh(c, doubled, "CNAME") if t == 5]:
                    found.append({"code": "doubled-name", "says":
                                  f"The record was added as {doubled}. Edit it and type only "
                                  f"{relative(name, root)} as the name."})
            caa = [d for t, d in await _doh(c, root, "CAA") if t == 257]
            issuers = [d.split("issue", 1)[1].strip().strip('"').split(";")[0].strip()
                       for d in caa if " issue " in f" {d} "]
            if caa and issuers and not any(i.startswith(CERT_AUTHORITY) for i in issuers):
                found.append({"code": "caa", "says":
                              f"{root} allows certificates only from {', '.join(sorted(set(issuers)))}. Add a CAA "
                              f'record on {root}: 0 issue "{CERT_AUTHORITY}", so Vercel can issue the certificate.'})
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return found
    return found


__all__ = ["GENERIC", "PROVIDERS", "diagnose", "guides", "relative"]
