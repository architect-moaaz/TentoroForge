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
    """`AquaTrack` → `aquatrack`; a name that leaves nothing falls back."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(app_name or "").lower()).strip("-")[:40].strip("-")
    return slug or re.sub(r"[^a-z0-9-]+", "", fallback.lower())[:40] or "app"


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


def records_for(name: str, kind: str, project_domain: dict | None, config: dict | None) -> list[dict]:
    """The records the owner adds: what points the address at Vercel, and the
    TXT proof when Vercel asks for one."""
    config = config or {}
    out: list[dict] = []
    if kind == "apex":
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
        return await self.refresh(name)

    async def remove(self, raw: str) -> None:
        name = normalise(raw)
        entry = next((e for e in self.entries() if e["name"] == name), None)
        if entry is None:
            raise DomainRefused(f"{name} is not one of this app's addresses.")
        pid = await self.project_id()
        if pid:
            await self.client.remove_project_domain(pid, name)
        self._write(lambda dep: dep.__setitem__("domains", [e for e in dep["domains"] if e.get("name") != name]),
                    f"Remove the address {name}")
        led = read_ledger(self.output_dir)
        led.get("domains", {}).pop(name, None)
        _write_ledger(self.output_dir, led)
        if entry.get("main") and entry.get("status") == "live":
            await self.follow()

    async def make_main(self, raw: str) -> dict:
        name = normalise(raw)
        if not any(e["name"] == name for e in self.entries()):
            raise DomainRefused(f"{name} is not one of this app's addresses; add it first.")

        def change(dep: dict) -> None:
            for e in dep["domains"]:
                e["main"] = e.get("name") == name
        self._write(change, f"Make {name} the main address")
        await self.follow()
        return self.view_of(name)

    async def set_old_address(self, mode: str) -> None:
        if mode not in ("redirect", "keep"):
            raise DomainRefused("The old address either sends people to the main address or keeps answering.")
        self._write(lambda dep: dep.__setitem__("oldAddress", mode), f"The old address: {mode}")
        await self.follow()

    # ── checking ────────────────────────────────────────────────────

    async def refresh(self, raw: str) -> dict:
        """Ask Vercel and the address itself where things stand; record it."""
        name = normalise(raw)
        entry = next((e for e in self.entries() if e["name"] == name), None)
        if entry is None:
            raise DomainRefused(f"{name} is not one of this app's addresses.")
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
        state, reason = state_of(name, project_domain, config)
        if state == "dns-ok":
            ok, why = await (self.probe or https_probe)(name)
            state, reason = ("live", "") if ok else ("certificate", why)
        if state == "live" and self.address_check is not None:
            # IT ANSWERS; DOES IT WORK THERE? Sign-in must finish on this
            # address too. On the scorecard either way; status stays live.
            works, why = await self.address_check(name)
            seen["works"], seen["worksWhy"] = works, why
            seen["onCard"] = self.record(name, works, why, seen.get("onCard"))
        seen.update({"checkedAt": _iso(now), "state": state, "reason": reason,
                     "records": records_for(name, entry.get("kind") or "subdomain", project_domain, config),
                     "apexName": (project_domain or {}).get("apexName")})
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
            if became_live:
                self._tell(f"{name} is live: the app answers there with a valid certificate."
                           + (" It is the main address now; sign-in and links use it." if entry.get("main") else ""))
            elif status == "failed" and entry.get("status") != "failed":
                self._tell(f"{name} is not working: {reason}")
            if entry.get("main") and (became_live or entry.get("status") == "live"):
                await self.follow()
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
        """`https://<main>` when the main address is live, else ""."""
        main = next((e for e in self.entries() if e.get("main") and e.get("status") == "live"), None)
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
        env = {e.get("key"): e for e in await self.client.list_env(pid)}
        current = env.get("NEXTAUTH_URL")
        changed = False
        if wanted and (not current or current.get("value") != wanted):
            if current and current.get("id"):
                await self.client.update_env(pid, current["id"], wanted, ["production"])
            else:
                await self.client.set_env(pid, "NEXTAUTH_URL", wanted, ["production"])
            changed = True
        elif not wanted and current and current.get("id"):
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
                "works": seen.get("works"), "worksDetail": seen.get("worksWhy") or ""}

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
                "appsDomain": apps_domain()}

    def _tell(self, text: str) -> None:
        if self.say is not None:
            try:
                self.say(text)
            except Exception:  # noqa: BLE001 — telling is best-effort
                logger.warning("[domains] could not tell the owner: %s", text, exc_info=True)


def project_root(path: str | Path) -> Path:
    """The project folder (the one holding `.forge`) from it or its `app/`."""
    p = Path(path)
    if (p / ".forge").is_dir() or not (p.parent / ".forge").is_dir():
        return p
    return p.parent


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
            name = (svc._svc().doc.get("product") or {}).get("name") or ""
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


def run_sync(coro: Awaitable[Any]) -> Any:
    """Run a coroutine from synchronous code (a Smith seam, off the event loop)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)  # type: ignore[arg-type]
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


__all__ = ["DomainRefused", "DomainService", "GIVE_UP_AFTER", "VERCEL_A", "VERCEL_CNAME", "apps_domain", "attach_after_publish", "project_root",
           "https_probe", "next_check", "normalise", "read_ledger", "records_for", "run_sync", "state_of",
           "tentoro_slug", "vercel_project_name"]
