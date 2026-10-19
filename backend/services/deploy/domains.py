"""The addresses a published application answers at.

Every app is one project in Tentoro's Vercel team and answers at
`<project>.vercel.app`. The owner can add their own domain (`acme.com`) or
subdomain (`app.acme.com`) from the Publish dialog, from App settings, or by
asking Smith; the platform can give every app a Tentoro address
(`<app>.apps.tentoro.ai`, when `FORGE_APPS_DOMAIN` is set).

What happens to an address:

1. **Added.** It is checked (a real domain, not a Vercel or local address),
   attached to the app's Vercel project, and written into the definition's
   `deployment.domains` as `waiting`. An app not yet published keeps it
   waiting and attaches it at its first publish.
2. **Records.** The records to add are read from Vercel each time — a CNAME
   for a subdomain, A records for a bare domain, and a TXT proof when Vercel
   asks for one (the domain is claimed by another account).
3. **Watched.** `refresh` asks Vercel whether the proof and the records are
   there, then whether the address answers over HTTPS with a valid
   certificate. The watch (`watch_due`) checks often at first, then less
   often, and gives up after two days. Each check is kept in the project's
   `.forge/domains.json`; the definition changes only when the status does.
4. **Followed.** When the main address goes live (or stops being main), the
   app follows it: sign-in's address (`NEXTAUTH_URL`) is set to it, the app
   is redeployed so the setting takes effect, and the old `vercel.app`
   address sends people there unless the owner chose to keep it answering.

Where the domain's DNS provider speaks Domain Connect and holds Tentoro's
template, `connect_url` gives the owner a signed link to approve the records
there in one click (`services.deploy.domain_connect`). When the owner has
connected their DNS provider by key, `write_records` adds the records itself (`services.deploy.dns_providers`, with its safety rules), and
removing the address takes away exactly what Forge wrote.

An application of several organisations can give each its own address:
`connect_organisations("clinicapp.com")` attaches `*.clinicapp.com`, whose
nameservers must be Vercel's, and once it answers the app is told
(FORGE_ORG_DOMAIN, FORGE_ORG_SIGN_IN_MODE) and redeployed; the app reads the host
and opens that organisation (`templates/runtime/tenancy.ts`).

A bare domain brings its `www.` companion, which sends people to it. The
Tentoro address stays with the app: it can be renamed, not removed, and it
is the address the app uses while none of the owner's own is live.

Vercel itself refuses an address another project in the team already uses,
so no two Forge apps can hold one.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

#: What Vercel asks for when its configuration call says nothing better.
VERCEL_CNAME = "cname.vercel-dns.com"
VERCEL_A = "76.76.21.21"
#: A wildcard needs Vercel to answer for the whole domain.
VERCEL_NAMESERVERS = ("ns1.vercel-dns.com", "ns2.vercel-dns.com")

#: Addresses that are not the owner's to add.
_NOT_THEIRS = (".vercel.app", ".vercel-dns.com", ".vercel.com", ".now.sh", ".localhost", ".local", ".test",
               ".example", ".invalid")
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_IP = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

#: How long the watch keeps checking an address that is not live, and how
#: often: every check before the first threshold, then the next interval.
WATCH_SCHEDULE: tuple[tuple[timedelta, timedelta], ...] = (
    (timedelta(minutes=10), timedelta(seconds=30)),
    (timedelta(hours=1), timedelta(minutes=2)),
    (timedelta(hours=48), timedelta(minutes=15)),
)
GIVE_UP_AFTER = timedelta(hours=48)
#: A live address is looked at again once a day, in case its records changed.
RECHECK_LIVE = timedelta(hours=24)

LEDGER = "domains.json"

#: Names a Tentoro address may not take: the platform's own, and the ones
#: people would mistake for it.
RESERVED_LABELS = frozenset({
    "www", "api", "app", "apps", "admin", "administrator", "auth", "login", "signin", "sso", "account",
    "mail", "email", "smtp", "imap", "pop", "mx", "ftp", "ns", "ns1", "ns2", "dns", "cdn", "static",
    "assets", "files", "status", "help", "support", "docs", "blog", "forge", "tentoro", "dev",
    "staging", "test", "preview", "billing", "security", "root", "system",
})


class DomainRefused(ValueError):
    """The address cannot be added; the message says why, in the owner's words."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def normalise(raw: str) -> str:
    """`https://App.Acme.com/login` → `app.acme.com`, or DomainRefused."""
    name = str(raw or "").strip().lower()
    name = re.sub(r"^[a-z][a-z0-9+.-]*://", "", name)
    name = name.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    name = name.rsplit("@", 1)[-1]
    name = re.sub(r":\d+$", "", name).strip(".")
    if not name:
        raise DomainRefused("Give the address, for example app.your-company.com.")
    try:
        name = name.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise DomainRefused(f"{raw!r} is not a domain name I can use: {exc}.") from exc
    if _IP.match(name):
        raise DomainRefused("An IP address cannot be an app's address; give a domain name, such as app.your-company.com.")
    labels = name.split(".")
    if len(labels) < 2 or len(name) > 253 or not all(_LABEL.match(lb) for lb in labels):
        raise DomainRefused(f"{name!r} is not a full domain name. Give one such as app.your-company.com.")
    if not re.match(r"^(xn--[a-z0-9-]+|[a-z]{2,63})$", labels[-1]):
        raise DomainRefused(f"{name!r} does not end in a real domain ending such as .com or .co.uk.")
    if name in ("localhost",) or any(name.endswith(s) or name == s.lstrip(".") for s in _NOT_THEIRS):
        raise DomainRefused(f"{name} is not an address you can bring: use a domain you own, such as app.your-company.com.")
    return name


def apps_domain() -> str:
    """The domain Tentoro gives every app an address under, or ""."""
    return str(os.environ.get("FORGE_APPS_DOMAIN") or "").strip().lower().strip(".")


def tentoro_slug(app_name: str, fallback: str) -> str:
    """`AquaTrack` → `aquatrack`; a name that leaves nothing usable (empty,
    under three letters, or reserved) falls back to the project's name."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(app_name or "").lower()).strip("-")[:40].strip("-")
    if len(slug) >= 3 and slug not in RESERVED_LABELS:
        return slug
    return re.sub(r"[^a-z0-9-]+", "", fallback.lower())[:40].strip("-") or "app"


def tentoro_label(raw: str, base: str) -> str:
    """The name before `.<base>` the owner asked for: `Aqua` or
    `aqua.apps.tentoro.ai` → `aqua`, or DomainRefused."""
    name = str(raw or "").strip().lower().strip(".")
    name = re.sub(r"^[a-z][a-z0-9+.-]*://", "", name).split("/", 1)[0]
    if base and name.endswith("." + base):
        name = name[: -len(base) - 1]
    if "." in name:
        raise DomainRefused(f"Give just the name before .{base}, such as aqua.")
    label = re.sub(r"[^a-z0-9]+", "-", name).strip("-")
    if len(label) < 3 or len(label) > 40:
        raise DomainRefused("The name must be 3 to 40 letters, digits or dashes.")
    if label in RESERVED_LABELS:
        raise DomainRefused(f"{label}.{base} is kept for the platform; choose another name.")
    return label


def _first_value(rows: Any) -> list[str]:
    """Vercel's recommended values, rank 1 first: `[{rank, value}]` where
    value is one string or a list of them."""
    out: list[str] = []
    for row in sorted([r for r in rows or [] if isinstance(r, dict)], key=lambda r: r.get("rank", 99)):
        v = row.get("value")
        vals = v if isinstance(v, list) else [v]
        out += [str(x).rstrip(".") for x in vals if x]
        if out:
            break
    return out


def _canon(raw: str) -> str:
    """An address as kept: `normalise`, and `*.<domain>` for the organisations' wildcard."""
    text = str(raw or "").strip().lower()
    if text.startswith("*."):
        return "*." + normalise(text[2:])
    return normalise(text)


def records_for(name: str, kind: str, project_domain: dict | None, config: dict | None) -> list[dict]:
    """The records the owner adds: what points the address at Vercel, and the
    TXT proof when Vercel asks for one."""
    config = config or {}
    out: list[dict] = []
    if kind == "organisations":
        base = name.removeprefix("*.")
        for ns in VERCEL_NAMESERVERS:
            out.append({"host": base, "type": "NS", "value": ns,
                        "why": f"set where {base} is registered: Vercel answers for every address under it"})
    elif kind == "apex":
        ips = _first_value(config.get("recommendedIPv4")) or [str(v) for v in config.get("aValues") or []] or [VERCEL_A]
        for ip in ips:
            out.append({"host": name, "type": "A", "value": ip,
                        "why": f"points {name} at Vercel"})
    elif kind != "tentoro":
        cname = (_first_value(config.get("recommendedCNAME")) or [str(v).rstrip(".") for v in config.get("cnames") or []]
                 or [VERCEL_CNAME])[0]
        out.append({"host": name, "type": "CNAME", "value": cname, "why": f"points {name} at Vercel"})
    for v in (project_domain or {}).get("verification") or []:
        if isinstance(v, dict) and v.get("value"):
            out.append({"host": str(v.get("domain") or f"_vercel.{name}"), "type": str(v.get("type") or "TXT"),
                        "value": str(v["value"]),
                        "why": "proves the domain is yours (it is claimed by another Vercel account)"})
    return out


def state_of(name: str, project_domain: dict | None, config: dict | None) -> tuple[str, str]:
    """`(state, reason)` from what Vercel says: `proof`, `records`, or `dns-ok`."""
    if project_domain is None:
        return "records", f"{name} is not attached to the app on Vercel yet."
    if project_domain.get("verified") is False:
        return "proof", f"Vercel needs the TXT record that proves {project_domain.get('apexName') or name} is yours."
    if (config or {}).get("misconfigured", True):
        if name.startswith("*."):
            return "records", (f"{name[2:]}'s nameservers are not Vercel's yet. Change them where the domain is "
                               "registered; it can take up to two days to spread.")
        return "records", f"The record that points {name} at Vercel is not there yet. It can take up to two days to spread."
    return "dns-ok", ""


# --------------------------------------------------------------------------- #
# The project's ledger of checks
# --------------------------------------------------------------------------- #


def _ledger_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / ".forge" / LEDGER


def read_ledger(output_dir: str | Path) -> dict:
    try:
        data = json.loads(_ledger_path(output_dir).read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_ledger(output_dir: str | Path, data: dict) -> None:
    p = _ledger_path(output_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), "utf-8")
    tmp.replace(p)


def next_check(entry: dict, seen: dict, now: datetime | None = None) -> datetime | None:
    """When the watch looks at this address again, or None when it stopped."""
    now = now or _now()
    last = _parse(seen.get("checkedAt"))
    if entry.get("status") == "live":
        # LIVE BUT NOT WORKING YET is looked at again soon, for an hour: the
        # redeploy that moves sign-in to the address takes a minute or two.
        live_at = _parse(entry.get("liveAt")) or now
        if seen.get("works") is False and now - live_at < timedelta(hours=1):
            return (last or now) + timedelta(minutes=2)
        return (last or now) + RECHECK_LIVE
    if entry.get("status") == "failed" and seen.get("gaveUp"):
        return None
    added = _parse(entry.get("addedAt")) or now
    age = now - added
    for until, every in WATCH_SCHEDULE:
        if age < until:
            return (last + every) if last else now
    return now if not seen.get("gaveUp") else None


# --------------------------------------------------------------------------- #
# The service
# --------------------------------------------------------------------------- #


Probe = Callable[[str], Awaitable[tuple[bool, str]]]


async def https_probe(name: str) -> tuple[bool, str]:
    """Whether `https://name/` answers with a certificate the world accepts."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as c:
            r = await c.get(f"https://{name}/")
        if r.status_code >= 500:
            return False, f"https://{name}/ answers {r.status_code}."
        return True, ""
    except httpx.ConnectError as exc:
        text = str(exc)
        if "CERTIFICATE" in text.upper() or "SSL" in text.upper():
            return False, f"Vercel is still issuing the certificate for {name}."
        return False, f"{name} does not answer yet."
    except Exception as exc:  # noqa: BLE001 — not answering yet is a state, not a fault
        return False, f"{name} does not answer yet ({type(exc).__name__})."


def vercel_project_name(short_id: str) -> str:
    from services.deploy.vercel_provider import _slugify
    return _slugify(short_id)


@dataclass
class DomainService:
    """One app's addresses. `client` is a VercelClient (or a stand-in in tests);
    `project_name` the Vercel project, `<project>.vercel.app`."""

    output_dir: str
    client: Any
    project_name: str
    #: Whether the address answers over HTTPS; None is the real check, found
    #: when it is used (so a test can stand it in).
    probe: Probe | None = None
    say: Callable[[str], None] | None = None
    now: Callable[[], datetime] = _now
    #: `(works, why)` for a live address; None skips it (tests of the rest).
    address_check: Callable[[str], Awaitable[tuple[bool, str]]] | None = None
    #: The organisation's connected DNS accounts (`dns_accounts.load`).
    dns: list[Any] = field(default_factory=list)
    #: Their names, for what is shown (`dns_accounts.connected_labels`).
    dns_labels: list[str] = field(default_factory=list)
    _project_id: str | None = field(default=None, init=False)

    # ── the definition ──────────────────────────────────────────────

    def _svc(self):
        from services.blueprint.service import BlueprintService
        return BlueprintService.load(output_dir=self.output_dir)

    def entries(self) -> list[dict]:
        try:
            dep = (self._svc().doc.get("deployment") or {})
        except FileNotFoundError:
            return []
        return [dict(e) for e in dep.get("domains") or [] if isinstance(e, dict)]

    def old_address(self) -> str:
        try:
            return str((self._svc().doc.get("deployment") or {}).get("oldAddress") or "redirect")
        except FileNotFoundError:
            return "redirect"

    def _write(self, change: Callable[[dict], None], why: str) -> None:
        svc = self._svc()
        before = svc.snapshot()
        dep = svc.doc.setdefault("deployment", {})
        dep.setdefault("domains", [])
        change(dep)
        svc.commit(user_request=why, smith_interpretation=why, before=before)

    def _set_entry(self, name: str, **fields: Any) -> None:
        def change(dep: dict) -> None:
            for e in dep["domains"]:
                if e.get("name") == name:
                    e.update({k: v for k, v in fields.items() if v is not None})
                    for k, v in fields.items():
                        if v is None:
                            e.pop(k, None)
        self._write(change, f"Address {name}: {fields.get('status') or 'updated'}")

    # ── Vercel ──────────────────────────────────────────────────────

    async def project_id(self) -> str | None:
        """The app's Vercel project, or None before its first publish."""
        if self._project_id is None:
            project = await self.client.get_project(self.project_name)
            self._project_id = str(project.get("id")) if project else None
        return self._project_id

    # ── what the owner does ─────────────────────────────────────────

    async def connect(self, raw: str, *, kind: str | None = None, main: bool | None = None) -> dict:
        """Add an address. Returns its view (`view_of`)."""
        name = normalise(raw)
        known = {e["name"]: e for e in self.entries()}
        if name in known:
            return await self.refresh(name)
        base = apps_domain()
        if base and kind != "tentoro" and (name == base or name.endswith("." + base)):
            # Its own Tentoro address is renamed, never added beside it.
            return await self.rename_tentoro(name)
        entries = list(known.values())
        # THE FIRST OWN ADDRESS BECOMES MAIN; a later one does not take over
        # quietly. The Tentoro address is main only while there is nothing else.
        own_main = any(e.get("main") and e.get("kind") != "tentoro" for e in entries)
        any_main = any(e.get("main") for e in entries)
        is_main = bool(main) if main is not None else (not any_main if kind == "tentoro" else not own_main)
        pid = await self.project_id()
        found: dict | None = None
        if pid:
            try:
                found = await self.client.add_project_domain(pid, name)
            except RuntimeError as exc:
                text = str(exc)
                if "409" in text or "already" in text.lower() or "in use" in text.lower():
                    raise DomainRefused(f"{name} is already used by another app or Vercel project. Remove it there, "
                                        "or choose another address.") from exc
                if "status=403" in text:
                    raise DomainRefused(f"Vercel would not attach {name}: {text[-200:]}") from exc
                raise
        apex = str((found or {}).get("apexName") or "")
        kind = kind or ("apex" if apex and apex == name else "subdomain")
        now = _iso(self.now())

        def change(dep: dict) -> None:
            if is_main:
                for e in dep["domains"]:
                    e["main"] = False
            dep["domains"].append({"name": name, "kind": kind, "main": is_main, "status": "waiting",
                                   "addedAt": now,
                                   "reason": ("Publish the app; the address is attached at its first publish."
                                              if not pid else "Checking the records.")})
        self._write(change, f"Add the address {name}")
        if not pid:
            return self.view_of(name)
        view = await self.refresh(name)
        if kind == "apex":
            await self._companion(name)
        return view

    async def _companion(self, apex: str) -> None:
        """A bare domain brings `www.<apex>`, which sends people to it."""
        www = f"www.{apex}"
        if any(e["name"] == www for e in self.entries()):
            return
        pid = await self.project_id()
        if not pid:
            return
        try:
            await self.client.add_project_domain(pid, www)
            await self.client.redirect_project_domain(pid, www, apex)
        except RuntimeError:
            # Used by another project, or refused: the bare domain works without it.
            logger.warning("[domains] %s: could not add %s beside %s", self.project_name, www, apex, exc_info=True)
            return
        now = _iso(self.now())
        self._write(lambda dep: dep["domains"].append(
            {"name": www, "kind": "subdomain", "main": False, "status": "waiting", "redirectTo": apex,
             "addedAt": now, "reason": "Checking the records."}), f"Add {www}, which sends people to {apex}")
        await self.refresh(www)

    async def remove(self, raw: str) -> None:
        name = _canon(raw)
        entry = next((e for e in self.entries() if e["name"] == name), None)
        if entry is None:
            raise DomainRefused(f"{name} is not one of this app's addresses.")
        if entry.get("kind") == "tentoro":
            raise DomainRefused(f"{name} stays with the app: rename it, or make your own address the main one.")
        before = (self.main_address(), self.organisations_domain())
        gone = {name} | {e["name"] for e in self.entries() if e.get("redirectTo") == name}
        pid = await self.project_id()
        if pid:
            try:
                await detach(self.client, pid, gone)
            except RuntimeError as exc:
                m = re.search(r"'message':\s*'([^']+)'", str(exc))
                raise DomainRefused(f"{name} could not be removed, so nothing was changed"
                                    + (f": {m.group(1)}" if m else ".")) from exc
        await self._unwrite(gone)

        def change(dep: dict) -> None:
            dep["domains"] = [e for e in dep["domains"] if e.get("name") not in gone]
            if entry.get("main"):
                # The Tentoro address is main again while nothing else is.
                for e in dep["domains"]:
                    if e.get("kind") == "tentoro":
                        e["main"] = True
        self._write(change, f"Remove the address {name}")
        led = read_ledger(self.output_dir)
        for n in gone:
            led.get("domains", {}).pop(n, None)
        _write_ledger(self.output_dir, led)
        if (self.main_address(), self.organisations_domain()) != before:
            await self.follow()

    async def make_main(self, raw: str) -> dict:
        name = _canon(raw)
        entry = next((e for e in self.entries() if e["name"] == name), None)
        if entry is None:
            raise DomainRefused(f"{name} is not one of this app's addresses; add it first.")
        if entry.get("redirectTo"):
            raise DomainRefused(f"{name} sends people to {entry['redirectTo']}; make {entry['redirectTo']} the main address.")
        if entry.get("kind") == "organisations":
            raise DomainRefused(f"{name} holds the organisations' own addresses; the main address is one address.")

        def change(dep: dict) -> None:
            for e in dep["domains"]:
                e["main"] = e.get("name") == name
        self._write(change, f"Make {name} the main address")
        await self.follow()
        return self.view_of(name)

    async def write_records(self, raw: str, *, replace: bool = False) -> dict:
        """Add the address's records at the owner's DNS provider (and its
        `www.` companion's with it). `{written, conflicts, message, provider}`.
        Nothing is written when anything is in the way, unless `replace`; mail
        and proof records are never replaced."""
        from services.deploy.dns_providers import DnsRefused, Record, plan, said_conflicts
        name = _canon(raw)
        entry = next((e for e in self.entries() if e["name"] == name), None)
        if entry is None:
            raise DomainRefused(f"{name} is not one of this app's addresses.")
        if entry.get("kind") == "tentoro":
            return {"written": False, "conflicts": False, "provider": "",
                    "message": f"{name} needs no records; Tentoro's DNS already points at the app."}
        if entry.get("kind") == "organisations":
            return {"written": False, "conflicts": False, "provider": "",
                    "message": (f"{name[2:]}'s nameservers change where the domain is registered, not in its DNS "
                                f"records: set them to {' and '.join(VERCEL_NAMESERVERS)} there.")}
        if not self.dns:
            where = (read_ledger(self.output_dir).get("domains") or {}).get(name, {}).get("dnsHost") or ""
            raise DomainRefused(
                "No DNS account is connected. " + (f"{name}'s DNS is at {where}: " if where else "")
                + "connect it under Settings → Integrations and I can add the records, or add them yourself.")
        if not await self.project_id():
            raise DomainRefused("Publish the app first; Vercel says which records to add once it is attached.")
        names = [name] + [e["name"] for e in self.entries() if e.get("redirectTo") == name]
        wanted: dict[str, list[Record]] = {}
        for n in names:
            view = await self.refresh(n)
            wanted[n] = [Record(host=r["host"], type=r["type"], value=r["value"]) for r in view.get("records") or []]
        if not any(wanted.values()):
            return {"written": False, "conflicts": False, "provider": "",
                    "message": f"{name} needs no records now: " + _said_state(self.view_of(name))}
        provider = zone = None
        for p in self.dns:
            try:
                zone = await p.zone_for(name)
            except RuntimeError:
                logger.warning("[domains] %s could not look for %s", getattr(p, "label", p), name, exc_info=True)
                zone = None
            if zone:
                provider = p
                break
        if provider is None or not zone:
            raise DomainRefused(f"None of your connected DNS accounts ({', '.join(p.label for p in self.dns)}) "
                                f"holds {name}. Connect the account that does, or add the records yourself.")
        plans = {}
        for n, rows in wanted.items():
            existing: list[Record] = []
            for host in sorted({r.host for r in rows}):
                existing += await provider.records(zone, host)
            plans[n] = plan(rows, existing, replace=replace)
        stuck = [pl for pl in plans.values() if pl.blocked or (pl.conflicts and not replace)]
        if stuck:
            return {"written": False, "conflicts": True, "provider": provider.label,
                    "replaceable": not any(pl.blocked for pl in stuck),
                    "message": " ".join(said_conflicts(pl, provider.label) for pl in stuck)}
        added: list[str] = []
        replaced: list[str] = []
        try:
            for n, pl in plans.items():
                for _, old in pl.conflicts:
                    await provider.delete(zone, old)
                    replaced.append(f"{old.type} {old.host} → {old.value}")
                written = []
                for rec in pl.add:
                    rid = await provider.create(zone, rec)
                    written.append({"provider": provider.label, "zone": zone, "host": rec.host, "type": rec.type,
                                    "value": rec.value, "id": rid})
                    added.append(f"{rec.type} {rec.host} → {rec.value}")
                if written:
                    led = read_ledger(self.output_dir)
                    seen = led.setdefault("domains", {}).setdefault(n, {})
                    seen["written"] = [*(seen.get("written") or []), *written]
                    _write_ledger(self.output_dir, led)
        except (RuntimeError, DnsRefused) as exc:
            raise DomainRefused(f"{provider.label} refused a change: {str(exc)[-240:]}"
                                + (f" Already added: {'; '.join(added)}." if added else "")) from exc
        for n in names:
            await self.refresh(n)
        if not added:
            return {"written": False, "conflicts": False, "provider": provider.label,
                    "message": f"The records are already there at {provider.label}; {name} answers once they spread."}
        return {"written": True, "conflicts": False, "provider": provider.label,
                "message": (f"Added at {provider.label}: {'; '.join(added)}."
                            + (f" Replaced: {'; '.join(replaced)}." if replaced else "")
                            + f" {name} usually answers within minutes; I will say here when it is live.")}

    async def _discover_connect(self, name: str, kind: str, project_domain: dict | None, seen: dict,
                                now: datetime) -> None:
        """Whether the domain's provider takes Tentoro's Domain Connect template
        — asked once a day while the address waits."""
        from services.deploy import domain_connect as dc
        service = dc.service_for(kind)
        if not service or not dc.provider_id():
            return
        last = _parse(seen.get("connectAt"))
        if last and now - last < timedelta(hours=24) and (seen.get("connect") or {}).get("service") == service:
            return
        root = str((project_domain or {}).get("apexName") or ".".join(name.split(".")[-2:]))
        try:
            found = await dc.discover(root, service)
        except Exception:  # noqa: BLE001 — an offer, never a failure
            found = {}
        seen["connect"] = {**found, "root": root, "service": service} if found else {}
        seen["connectAt"] = _iso(now)

    async def connect_url(self, raw: str, redirect_uri: str) -> dict:
        """The signed link that takes the owner to their DNS provider to
        approve this address's records (and its www's, and the proof):
        `{url, provider}`."""
        import secrets

        from services.deploy import domain_connect as dc
        name = _canon(raw)
        entry = next((e for e in self.entries() if e["name"] == name), None)
        if entry is None:
            raise DomainRefused(f"{name} is not one of this app's addresses.")
        if not dc.ready():
            raise DomainRefused("One-click approval is not set up on this platform; add the records instead.")
        led = read_ledger(self.output_dir)
        seen = (led.get("domains") or {}).get(name) or {}
        found = seen.get("connect") or {}
        if not found.get("supported"):
            raise DomainRefused(f"{name}'s DNS provider does not offer one-click approval for Forge yet; "
                                "add the records instead.")
        root = str(found.get("root") or "")
        planned = self._connect_plan(name, led)
        if planned is None:
            raise DomainRefused(f"{name} needs records the one-click approval does not cover; add them instead.")
        service, host, values, groups = planned
        state = secrets.token_urlsafe(16)
        seen["connectState"] = state
        led.setdefault("domains", {})[name] = seen
        _write_ledger(self.output_dir, led)
        url = dc.apply_url(found, service, root, host, values, groups, redirect_uri=redirect_uri, state=state)
        return {"url": url, "provider": found.get("providerName") or "your DNS provider"}

    def _connect_plan(self, name: str, led: dict | None = None):
        """What the provider would be asked to apply for this address, or None
        when its records are not what a template writes."""
        from services.deploy import domain_connect as dc
        led = led if led is not None else read_ledger(self.output_dir)
        seen = (led.get("domains") or {}).get(name) or {}
        found = seen.get("connect") or {}
        entry = next((e for e in self.entries() if e["name"] == name), None)
        if not entry or not found.get("supported"):
            return None
        companion = next((e for e in self.entries() if e.get("redirectTo") == name), None)
        comp_records = ((led.get("domains") or {}).get(companion["name"]) or {}).get("records") if companion else []
        return dc.plan_apply(entry.get("kind") or "subdomain", name, str(found.get("root") or ""),
                             seen.get("records") or [], comp_records)

    async def _unwrite(self, names: set[str]) -> None:
        """Take away the records Forge itself wrote for these addresses."""
        led = read_ledger(self.output_dir)
        by_label = {getattr(p, "label", ""): p for p in self.dns}
        from services.deploy.dns_providers import Record
        for n in names:
            for w in (led.get("domains") or {}).get(n, {}).get("written") or []:
                p = by_label.get(w.get("provider"))
                if p is None:
                    continue
                try:
                    await p.delete(w["zone"], Record(host=w["host"], type=w["type"], value=w["value"], id=w.get("id") or ""))
                except Exception:  # noqa: BLE001 — the address is gone either way
                    logger.warning("[domains] could not take away %s %s at %s", w.get("type"), w.get("host"),
                                   w.get("provider"), exc_info=True)

    def tenancy(self) -> dict:
        try:
            return dict(((self._svc().doc.get("security") or {}).get("tenancy")) or {})
        except FileNotFoundError:
            return {}

    async def connect_organisations(self, raw: str) -> dict:
        """Each organisation answers at its own address under this domain:
        `clinicapp.com` → `*.clinicapp.com` on the app, `acme.clinicapp.com`
        for the organisation whose address is `acme`."""
        if self.tenancy().get("kind") != "organisation":
            raise DomainRefused("This app serves one organisation, so there is no address per organisation to give.")
        base = normalise(str(raw or "").strip().lower().removeprefix("*."))
        name = f"*.{base}"
        current = next((e for e in self.entries() if e.get("kind") == "organisations"), None)
        if current and current["name"] == name:
            return await self.refresh(name)
        if current:
            raise DomainRefused(f"Organisations already answer under {current['name'][2:]}; remove that first.")
        pid = await self.project_id()
        if pid:
            try:
                await self.client.add_project_domain(pid, name)
            except RuntimeError as exc:
                text = str(exc)
                if "409" in text or "already" in text.lower() or "in use" in text.lower():
                    raise DomainRefused(f"{name} is already used by another app or Vercel project.") from exc
                raise
        now = _iso(self.now())
        self._write(lambda dep: dep["domains"].append(
            {"name": name, "kind": "organisations", "main": False, "status": "waiting", "addedAt": now,
             "reason": ("Checking the nameservers." if pid else
                        "Publish the app; the address is attached at its first publish.")}),
            f"Give each organisation an address under {base}")
        return await self.refresh(name) if pid else self.view_of(name)

    async def set_organisation_sign_in(self, mode: str) -> None:
        """One sign-in across the organisations' addresses, or one at each."""
        if mode not in ("shared", "per_organisation"):
            raise DomainRefused("Sign-in is either shared across the organisations' addresses or kept per organisation.")
        svc = self._svc()
        before = svc.snapshot()
        svc.doc.setdefault("security", {}).setdefault("tenancy", {})["addressSignIn"] = mode
        why = f"Sign-in across the organisations' addresses: {mode}"
        svc.commit(user_request=why, smith_interpretation=why, before=before)
        await self.follow()

    def organisations_domain(self) -> str:
        """The domain the organisations' addresses sit under, once it answers."""
        e = next((x for x in self.entries() if x.get("kind") == "organisations" and x.get("status") == "live"), None)
        return e["name"][2:] if e else ""

    async def set_old_address(self, mode: str) -> None:
        if mode not in ("redirect", "keep"):
            raise DomainRefused("The old address either sends people to the main address or keeps answering.")
        self._write(lambda dep: dep.__setitem__("oldAddress", mode), f"The old address: {mode}")
        await self.follow()

    async def rename_tentoro(self, raw: str) -> dict:
        """Give the app's Tentoro address another name (`aqua` →
        `aqua.apps.tentoro.ai`). The new name is attached before the old one
        is let go, so a name that is taken changes nothing."""
        base = apps_domain()
        if not base:
            raise DomainRefused("This platform gives apps no Tentoro address; add your own domain instead.")
        new = f"{tentoro_label(raw, base)}.{base}"
        entries = self.entries()
        old = next((e for e in entries if e.get("kind") == "tentoro"), None)
        if old and old["name"] == new:
            return self.view_of(new)
        if any(e["name"] == new for e in entries):
            raise DomainRefused(f"{new} is already one of this app's addresses.")
        before = self.main_address()
        pid = await self.project_id()
        if pid:
            # A RETRY FINDS ITS OWN NAME. When an earlier attempt attached the
            # new name and then stopped, Vercel answers "in use" for it — in use
            # by this very app, which is not "taken by another" (Mark 8,
            # 2026-10-18).
            mine = await self.client.get_project_domain(pid, new) is not None
            if not mine:
                try:
                    await self.client.add_project_domain(pid, new)
                except RuntimeError as exc:
                    text = str(exc)
                    if "409" in text or "already" in text.lower() or "in use" in text.lower():
                        raise DomainRefused(f"{new} is taken by another app; choose another name.") from exc
                    raise
            if old:
                await self._let_go(pid, old["name"], new, added=not mine)
        now = _iso(self.now())

        def change(dep: dict) -> None:
            if old:
                dep["domains"] = [e for e in dep["domains"] if e.get("name") != old["name"]]
            dep["domains"].append({"name": new, "kind": "tentoro",
                                   "main": bool(old.get("main")) if old else not any(e.get("main") for e in dep["domains"]),
                                   "status": "waiting", "addedAt": now,
                                   "reason": ("Checking the address." if pid else
                                              "Publish the app; the address is attached at its first publish.")})
        self._write(change, f"Rename the Tentoro address to {new}" if old else f"Add the Tentoro address {new}")
        if old:
            led = read_ledger(self.output_dir)
            led.get("domains", {}).pop(old["name"], None)
            _write_ledger(self.output_dir, led)
        if not pid:
            return self.view_of(new)
        view = await self.refresh(new)
        if self.main_address() != before:
            await self.follow()
        return view

    async def _let_go(self, pid: str, old: str, new: str, *, added: bool) -> None:
        """Detach the old Tentoro name once the new one is attached; whatever
        redirected to it now redirects to the new name (`detach`). If it still
        cannot be let go, a name this attempt attached is detached again, so
        nothing has changed and the person is told why — not a 500 with the
        app answering at both names (Mark 8, 2026-10-18)."""
        try:
            await detach(self.client, pid, [old], repoint_to=new)
        except RuntimeError as exc:
            if added:
                try:
                    await self.client.remove_project_domain(pid, new)
                except RuntimeError:
                    pass
            m = re.search(r"'message':\s*'([^']+)'", str(exc))
            raise DomainRefused(f"{old} could not be let go, so nothing was renamed"
                                + (f": {m.group(1)}" if m else ".")) from exc

    # ── checking ────────────────────────────────────────────────────

    async def refresh(self, raw: str) -> dict:
        """Ask Vercel and the address itself where things stand; record it."""
        name = _canon(raw)
        entry = next((e for e in self.entries() if e["name"] == name), None)
        if entry is None:
            raise DomainRefused(f"{name} is not one of this app's addresses.")
        address_before = (self.main_address(), self.organisations_domain())
        led = read_ledger(self.output_dir)
        seen = led.setdefault("domains", {}).setdefault(name, {})
        now = self.now()
        pid = await self.project_id()
        if not pid:
            seen.update({"checkedAt": _iso(now), "state": "unpublished"})
            _write_ledger(self.output_dir, led)
            return self.view_of(name)
        project_domain = await self.client.get_project_domain(pid, name)
        if project_domain is None and entry.get("kind") != "tentoro":
            # Added before the first publish, or detached in Vercel: attach it.
            try:
                project_domain = await self.client.add_project_domain(pid, name)
            except RuntimeError as exc:
                seen.update({"checkedAt": _iso(now), "state": "refused", "reason": str(exc)[-300:]})
                _write_ledger(self.output_dir, led)
                self._set_entry(name, status="failed", reason=f"Vercel would not attach {name}.")
                return self.view_of(name)
        elif project_domain is None:
            project_domain = await self.client.add_project_domain(pid, name)
        if entry.get("redirectTo") and (project_domain or {}).get("redirect") != entry["redirectTo"]:
            try:
                await self.client.redirect_project_domain(pid, name, entry["redirectTo"])
            except RuntimeError:
                logger.warning("[domains] %s: could not send %s to %s", self.project_name, name,
                               entry["redirectTo"], exc_info=True)
        if project_domain and project_domain.get("verified") is False:
            project_domain = await self.client.verify_project_domain(pid, name) or project_domain
        try:
            config = await self.client.get_domain_config(name)
        except RuntimeError:
            config = {}
        apex = str((project_domain or {}).get("apexName") or "")
        if entry.get("kind") == "subdomain" and apex == name:
            # Added before the first publish, when Vercel could not yet say it
            # is a bare domain: its records are A records, not a CNAME.
            self._set_entry(name, kind="apex")
            entry["kind"] = "apex"
            became_apex = True
        else:
            became_apex = False
        state, reason = state_of(name, project_domain, config)
        if state not in ("dns-ok",) and entry.get("kind") != "tentoro" and "dnsHost" not in seen:
            from services.deploy import dns_providers
            try:
                seen["dnsHost"] = await dns_providers.dns_host(name)
            except Exception:  # noqa: BLE001 — a hint, never a failure
                seen["dnsHost"] = ""
        if state != "dns-ok" and not entry.get("redirectTo"):
            await self._discover_connect(name, entry.get("kind") or "subdomain", project_domain, seen, now)
        if state == "dns-ok" and entry.get("kind") == "organisations":
            # Vercel issues each organisation's certificate when it is first opened.
            state, reason = "live", ""
        elif state == "dns-ok":
            ok, why = await (self.probe or https_probe)(name)
            state, reason = ("live", "") if ok else ("certificate", why)
        if state == "live" and self.address_check is not None and entry.get("kind") != "organisations":
            # IT ANSWERS; DOES IT WORK THERE? Sign-in must finish on this
            # address too. On the scorecard either way; status stays live.
            works, why = await self.address_check(name)
            seen["works"], seen["worksWhy"] = works, why
            seen["onCard"] = self.record(name, works, why, seen.get("onCard"))
        seen.update({"checkedAt": _iso(now), "state": state, "reason": reason,
                     "records": records_for(name, entry.get("kind") or "subdomain", project_domain, config),
                     "apexName": (project_domain or {}).get("apexName")})
        # WHAT IS WRONG, SPECIFICALLY: a record in the way, the proxy on, the
        # doubled name, a CAA record — said instead of "not there yet".
        seen["problems"] = []
        if state in ("records", "certificate") and entry.get("kind") in ("subdomain", "apex"):
            from services.deploy import dns_guides
            root = str((project_domain or {}).get("apexName") or ".".join(name.split(".")[-2:]))
            try:
                seen["problems"] = await dns_guides.diagnose(name, entry.get("kind"), root, seen["records"])
            except Exception:  # noqa: BLE001 — a hint, never a failure
                seen["problems"] = []
            if seen["problems"]:
                reason = seen["problems"][0]["says"]
                seen["reason"] = reason
        status = "live" if state == "live" else entry.get("status")
        gave_up = False
        if state != "live":
            added = _parse(entry.get("addedAt")) or now
            if entry.get("status") == "live":
                status, reason = "failed", reason or f"{name} stopped answering."
            elif now - added > GIVE_UP_AFTER:
                status, gave_up = "failed", True
                reason = (f"After two days the records for {name} are still not right: {reason} "
                          "Check them, then press Check now.")
            else:
                status = "waiting"
        seen["gaveUp"] = gave_up
        _write_ledger(self.output_dir, led)
        if status != entry.get("status") or (reason or None) != (entry.get("reason") or None):
            became_live = status == "live" and entry.get("status") != "live"
            self._set_entry(name, status=status, reason=reason or None,
                            liveAt=_iso(now) if became_live else None if status != "live" else entry.get("liveAt"))
            if became_live and entry.get("redirectTo"):
                self._tell(f"{name} is live and sends people to {entry['redirectTo']}.")
            elif became_live:
                self._tell(f"{name} is live: the app answers there with a valid certificate."
                           + (" It is the main address now; sign-in and links use it."
                              if self.main_address() == f"https://{name}" else ""))
            elif status == "failed" and entry.get("status") != "failed":
                self._tell(f"{name} is not working: {reason}")
        if (self.main_address(), self.organisations_domain()) != address_before:
            await self.follow()
        if became_apex:
            await self._companion(name)
        return self.view_of(name)

    async def watch_due(self) -> int:
        """Check every address whose time has come; the number checked."""
        led = read_ledger(self.output_dir)
        now = self.now()
        done = 0
        for e in self.entries():
            due = next_check(e, (led.get("domains") or {}).get(e["name"], {}), now)
            if due is not None and due <= now:
                try:
                    await self.refresh(e["name"])
                    done += 1
                except Exception:  # noqa: BLE001 — one address never stops the others
                    logger.warning("[domains] %s: check of %s failed", self.project_name, e["name"], exc_info=True)
        return done

    def record(self, name: str, works: bool, why: str, before: str | None) -> str | None:
        from services.deploy.domain_check import record_on_card
        try:
            return record_on_card(self.output_dir, name, works, why, before)
        except Exception:  # noqa: BLE001 — the card never stops a check
            logger.warning("[domains] could not put %s on the scorecard", name, exc_info=True)
            return before

    # ── the app follows its main address ────────────────────────────

    def main_address(self) -> str:
        """`https://<main>` when the main address is live; else the Tentoro
        address when it is live (the owner's own is still on its way); else ""."""
        live = [e for e in self.entries() if e.get("status") == "live"]
        main = next((e for e in live if e.get("main")), None) or next(
            (e for e in live if e.get("kind") == "tentoro"), None)
        return f"https://{main['name']}" if main else ""

    async def follow(self) -> dict:
        """Point sign-in at the main address, redeploy so it takes effect, and
        set what the old `vercel.app` address does. `{pinned, redeployed, redirect}`."""
        pid = await self.project_id()
        if not pid:
            return {"pinned": "", "redeployed": False, "redirect": None}
        from services.deploy.sign_in_address import sso_declared, production_alias
        main = self.main_address()
        wanted = main or (production_alias(self.project_name) if sso_declared(self.output_dir) else "")
        org_base = self.organisations_domain()
        # THE LIVE APP'S SETTINGS ONLY: the test version has its own rows of the
        # same names (its own NEXTAUTH_URL), which a domain change never touches.
        env = {e.get("key"): e for e in await self.client.list_env(pid)
               if "production" in (e.get("target") or ["production"])}
        changed = False
        for key, value in (("NEXTAUTH_URL", wanted), ("FORGE_ORG_DOMAIN", org_base),
                           ("FORGE_ORG_SIGN_IN_MODE", (self.tenancy().get("addressSignIn") or "shared") if org_base else "")):
            current = env.get(key)
            if value and (not current or current.get("value") != value):
                if current and current.get("id"):
                    await self.client.update_env(pid, current["id"], value, ["production"])
                else:
                    await self.client.set_env(pid, key, value, ["production"])
                changed = True
            elif not value and current and current.get("id"):
                await self.client.delete_env(pid, current["id"])
                changed = True
        redeployed = False
        if changed:
            latest = await self.client.latest_production_deployment(pid)
            if latest and (latest.get("uid") or latest.get("id")):
                await self.client.redeploy(self.project_name, str(latest.get("uid") or latest.get("id")))
                redeployed = True
        old = f"{self.project_name}.vercel.app"
        redirect = main.removeprefix("https://") if main and self.old_address() == "redirect" else None
        try:
            await self.client.redirect_project_domain(pid, old, redirect)
        except RuntimeError:
            logger.warning("[domains] %s: could not set what %s does", self.project_name, old, exc_info=True)
            redirect = None
        return {"pinned": wanted, "redeployed": redeployed, "redirect": redirect}

    # ── what is shown ───────────────────────────────────────────────

    def view_of(self, name: str) -> dict:
        e = next((x for x in self.entries() if x["name"] == name), {"name": name})
        seen = (read_ledger(self.output_dir).get("domains") or {}).get(name, {})
        return {**e, "records": seen.get("records") or [], "checkedAt": seen.get("checkedAt"),
                "state": seen.get("state"), "detail": seen.get("reason") or e.get("reason") or "",
                "works": seen.get("works"), "worksDetail": seen.get("worksWhy") or "",
                "dnsHost": seen.get("dnsHost") or "", "written": bool(seen.get("written")),
                "problems": seen.get("problems") or [],
                "guide": self._guide(name, e, seen),
                "connect": ((seen.get("connect") or {}).get("providerName") or "your DNS provider")
                if e.get("status") != "live" and self._connect_plan(name) is not None else ""}

    def _guide(self, name: str, entry: dict, seen: dict) -> dict | None:
        """Step-by-step instructions for adding this address's records at each
        common DNS provider, the detected one first (`dns_guides`)."""
        records = seen.get("records") or []
        if not records or entry.get("status") == "live" or entry.get("kind") in ("tentoro", "organisations"):
            return None
        from services.deploy import dns_guides
        root = str(seen.get("apexName") or ".".join(name.split(".")[-2:]))
        return dns_guides.guides(records, root, seen.get("dnsHost") or "")

    def view(self) -> dict:
        """Everything the Domains section and Smith show."""
        from services.deploy.sign_in_address import callback_addresses
        entries = [self.view_of(e["name"]) for e in self.entries()]
        main = self.main_address() or f"https://{self.project_name}.vercel.app"
        try:
            doc = self._svc().doc
        except FileNotFoundError:
            doc = {}
        from services.blueprint.projection import sign_in_policy
        sso = [str(s.get("id")) for s in (sign_in_policy(doc).get("sso") or []) if isinstance(s, dict) and s.get("id")]
        hooks = [str(i.get("id") or i.get("name")) for i in doc.get("integrations") or []
                 if isinstance(i, dict) and i.get("inbound")]
        elsewhere = [{"what": f"Company sign-in callback ({s})", "address": a}
                     for s, a in zip(sso, callback_addresses(main, sso))]
        elsewhere += [{"what": f"Incoming webhook ({h})", "address": f"{main}/api/webhooks/{h}"} for h in hooks]
        return {"domains": entries, "oldAddress": self.old_address(),
                "vercelAddress": f"https://{self.project_name}.vercel.app",
                "mainAddress": main, "elsewhere": elsewhere,
                "appsDomain": apps_domain(), "dnsAccounts": list(self.dns_labels),
                "organisations": {"available": self.tenancy().get("kind") == "organisation",
                                  "signIn": self.tenancy().get("addressSignIn") or "shared"}}

    def _tell(self, text: str) -> None:
        if self.say is not None:
            try:
                self.say(text)
            except Exception:  # noqa: BLE001 — telling is best-effort
                logger.warning("[domains] could not tell the owner: %s", text, exc_info=True)


def _said_state(view: dict) -> str:
    return "it is live." if view.get("status") == "live" else (view.get("detail") or "it is being checked.")


def project_root(path: str | Path) -> Path:
    """The project folder (the one holding `.forge`) from it or its `app/`."""
    p = Path(path)
    if (p / ".forge").is_dir() or not (p.parent / ".forge").is_dir():
        return p
    return p.parent


def live_address(output_dir: str | Path | None, short_id: str) -> str:
    """The address people should open the live app at: its main address once
    live (the owner's own, else its Tentoro address), or "" while only
    `<project>.vercel.app` answers."""
    if not output_dir:
        return ""
    try:
        return DomainService(output_dir=str(project_root(output_dir)), client=None,
                             project_name=vercel_project_name(short_id)).main_address()
    except Exception:  # noqa: BLE001 — what is shown falls back to the Vercel address
        logger.warning("[domains] could not read the main address of %s", short_id, exc_info=True)
        return ""


async def attach_after_publish(path: str | Path, client: Any, project_name: str,
                               say: Callable[[str], None] | None = None) -> list[dict]:
    """After a publish: give the app its Tentoro address (when the platform
    has one) and attach the addresses added before the first publish. The
    views of every address, for the publish's last event."""
    root = project_root(path)
    if not (root / ".forge" / "blueprint" / "current.json").is_file():
        return []
    from services.deploy.domain_check import check_address
    svc = DomainService(output_dir=str(root), client=client, project_name=project_name, say=say,
                        address_check=check_address)
    entries = svc.entries()
    base = apps_domain()
    if base and not any(e.get("kind") == "tentoro" for e in entries):
        try:
            doc = svc._svc().doc
            name = (doc.get("application") or {}).get("name") or (doc.get("product") or {}).get("name") or ""
        except FileNotFoundError:
            name = ""
        candidate = f"{tentoro_slug(name, project_name)}.{base}"
        try:
            await svc.connect(candidate, kind="tentoro")
        except DomainRefused:
            # Taken by another app: the project's own id is unique.
            await svc.connect(f"{tentoro_slug('', project_name)}.{base}", kind="tentoro")
    led = read_ledger(root).get("domains") or {}
    for e in svc.entries():
        if e.get("status") == "waiting" and (led.get(e["name"]) or {}).get("state") in (None, "unpublished"):
            try:
                await svc.refresh(e["name"])
            except Exception:  # noqa: BLE001 — the publish stays done; the watch carries on
                logger.warning("[domains] %s: could not attach %s after publish", project_name, e["name"], exc_info=True)
    return svc.view()["domains"]


def _redirect_target(d: dict) -> str:
    return str(d.get("redirect") or "").split("//")[-1].strip("/").lower()


async def detach(client: Any, pid: str, names: set[str] | list[str], *, repoint_to: str | None = None) -> list[str]:
    """Detach `names` from the Vercel project, and nothing else.

    VERCEL WILL NOT DETACH A NAME ANOTHER ADDRESS REDIRECTS TO (409
    `domain_is_redirect`). The app's other addresses point at its main one, a
    `www` companion at its bare domain, the old `vercel.app` address at the
    main address — so a rename, a remove or an app deletion died half-way
    (Mark 8's rename, 2026-10-18). Addresses that stay and redirect to one
    being detached are pointed at `repoint_to` (None: they stop redirecting;
    the caller's `follow` sets them again), and among those going, the ones
    that redirect are detached before what they redirect to.

    Raises RuntimeError from Vercel after putting the repointed redirects
    back; returns the names detached."""
    going = {n.lower() for n in names}
    domains = await client.list_project_domains(pid)
    moved: list[tuple[str, str]] = []
    try:
        for d in domains:
            name = str(d.get("name") or "").lower()
            if name and name not in going and _redirect_target(d) in going:
                await client.redirect_project_domain(pid, name, repoint_to)
                moved.append((name, _redirect_target(d)))
        order = sorted(going, key=lambda n: (0 if any(str(d.get("name") or "").lower() == n and _redirect_target(d) in going
                                                       for d in domains) else 1, n))
        done: list[str] = []
        for n in order:
            await client.remove_project_domain(pid, n)
            done.append(n)
        return done
    except RuntimeError:
        for name, was in moved:
            try:
                await client.redirect_project_domain(pid, name, was)
            except RuntimeError:
                pass
        raise


async def detach_all(path: str | Path, client: Any, project_name: str) -> list[str]:
    """When an app is deleted: let go of every address it holds in Vercel, so
    the owner (or another app) can use them again. The names let go."""
    svc = DomainService(output_dir=str(project_root(path)), client=client, project_name=project_name)
    names = [e["name"] for e in svc.entries()]
    pid = await svc.project_id() if names else None
    if not pid:
        return []
    try:
        return await detach(client, pid, names)
    except RuntimeError:
        logger.warning("[domains] %s: could not let go of every address at once", project_name, exc_info=True)
    done: list[str] = []
    for n in names:
        try:
            done += await detach(client, pid, [n])
        except RuntimeError:
            logger.warning("[domains] %s: could not let go of %s", project_name, n, exc_info=True)
    return done


def run_sync(coro: Awaitable[Any]) -> Any:
    """Run a coroutine from synchronous code (a Smith seam, off the event loop)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)  # type: ignore[arg-type]
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


__all__ = ["DomainRefused", "DomainService", "GIVE_UP_AFTER", "VERCEL_A", "VERCEL_CNAME", "apps_domain", "attach_after_publish", "detach_all", "project_root",
           "https_probe", "next_check", "normalise", "read_ledger", "records_for", "run_sync", "state_of",
           "tentoro_label", "tentoro_slug", "vercel_project_name"]
