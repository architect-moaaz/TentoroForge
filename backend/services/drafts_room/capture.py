"""The deep study of a web product: the platform's browser walks its public
screens and records what the product DOES — the calls behind each screen
(record shapes, actions), the structure of each page (forms, controls,
routes) — as evidence with standings, never its prose or its scripts.

Polite by construction: robots.txt is honoured, a small page budget and a
slow pace per host, one site and its subdomains, and the whole study stops
on a 401, 403 or 429. Nothing is ever submitted; links that sign in or
out, delete, pay or unsubscribe are never followed. The browser is the
guarded one every Smith look uses (public hosts only, no sockets).

A recording the person made of their own session (`har.py`) is a deep
study too — the same calls, the same analysis — with `source: har`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from services.drafts_room import calls as callrec
from services.drafts_room import evidence as ev
from services.drafts_room import store
from services.smith.secrets_scrub import scrub

logger = logging.getLogger(__name__)

#: The budget of one web capture.
PAGES = 25
PACE_S = 1.5
HOSTS = 3
MINUTES = 8
#: How long a deep study waits for the surface study's screens before it
#: starts from the reference's own address.
WAIT_FOR_SURFACE_S = 180
STOP_STATUSES = (401, 403, 429)
#: Links never followed, by their text or their path.
_NEVER = re.compile(r"sign[ -]?in|sign[ -]?out|log[ -]?in|log[ -]?out|logout|register|delete|remove|pay|checkout|"
                    r"purchase|unsubscribe|cancel|download|\.(pdf|zip|dmg|exe|apk)$", re.I)
_CENSUS_JS = """
() => {
  const text = (el) => ((el && (el.innerText || el.textContent)) || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
  const forms = [...document.querySelectorAll('form')].slice(0, 12).map((f) => ({
    action: (f.getAttribute('action') || '').slice(0, 200), method: (f.getAttribute('method') || 'get').toLowerCase(),
    fields: [...f.querySelectorAll('input,select,textarea')].slice(0, 30)
      .filter((i) => !['hidden', 'submit', 'button'].includes((i.getAttribute('type') || '').toLowerCase()))
      .map((i) => ({ name: (i.getAttribute('name') || i.id || '').slice(0, 60), type: (i.tagName === 'SELECT' ? 'select' : i.tagName === 'TEXTAREA' ? 'textarea' : (i.getAttribute('type') || 'text')).toLowerCase(),
                     required: i.hasAttribute('required'), label: text(i.labels && i.labels[0]) || (i.getAttribute('placeholder') || '').slice(0, 60) })),
  }));
  const buttons = [...document.querySelectorAll('button,[role=button],input[type=submit]')].slice(0, 40)
    .map((b) => text(b) || (b.getAttribute('aria-label') || '').slice(0, 80)).filter(Boolean);
  const links = [...document.querySelectorAll('a[href]')].slice(0, 200)
    .map((a) => ({ text: text(a), href: a.href })).filter((l) => l.href);
  const headings = [...document.querySelectorAll('h1,h2,h3')].slice(0, 20).map((h) => text(h)).filter(Boolean);
  return { title: (document.title || '').slice(0, 120), route: location.pathname, headings, forms, buttons: [...new Set(buttons)], links };
}
"""

_ROBOTS: dict[str, RobotFileParser | None] = {}
_ROBOTS_LOCK = threading.Lock()


def robots_allows(url: str, agent: str) -> bool:
    """Whether robots.txt lets this agent open `url`. An unreadable
    robots.txt allows: that is its own convention."""
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    with _ROBOTS_LOCK:
        if origin not in _ROBOTS:
            rp = RobotFileParser()
            rp.set_url(origin + "/robots.txt")
            try:
                rp.read()
                _ROBOTS[origin] = rp
            except Exception:  # noqa: BLE001 — no robots.txt is no rule
                _ROBOTS[origin] = None
        rp = _ROBOTS[origin]
    if rp is None:
        return True
    try:
        return rp.can_fetch(agent, url)
    except Exception:  # noqa: BLE001
        return True


def same_site(host: str, site: str) -> bool:
    host, site = str(host or "").lower(), str(site or "").lower()
    parts = site.split(".")
    root = ".".join(parts[-2:]) if len(parts) >= 2 else site
    return bool(host) and (host == site or host == root or host.endswith("." + root))


def followable(link: dict, site: str) -> bool:
    href = str(link.get("href") or "")
    parsed = urlparse(href)
    if parsed.scheme not in ("http", "https") or not same_site(parsed.hostname or "", site):
        return False
    if _NEVER.search(str(link.get("text") or "")) or _NEVER.search(parsed.path or ""):
        return False
    return True


# --------------------------------------------------------------------------- #
# The walk
# --------------------------------------------------------------------------- #

class Walk:
    """One capture in progress: the budget, what was seen, what is left."""

    def __init__(self, job: dict, site: str, device: str):
        self.job = job
        self.site = site
        self.device = device
        self.pages: list[dict] = []
        self.calls: list[dict] = []
        self.queue: list[str] = []
        self.seen: set[str] = set()
        self.hosts: Counter = Counter()
        self.started = time.time()
        self.stopped_on: str | None = None
        self.gaps: list[str] = []

    def out_of_budget(self) -> str | None:
        if len(self.pages) >= PAGES:
            return f"page budget of {PAGES} reached"
        if time.time() - self.started > MINUTES * 60:
            return f"time budget of {MINUTES} minutes reached"
        return None

    def enqueue(self, url: str) -> None:
        key = url.split("#", 1)[0]
        host = urlparse(key).hostname or ""
        if key in self.seen or key in self.queue:
            return
        if not same_site(host, self.site):
            return
        if host not in self.hosts and len(self.hosts) >= HOSTS:
            return
        self.queue.append(key)


def _agent(device: str) -> str:
    from services.brand_discovery.site import USER_AGENT
    from services.smith.web import PHONE_AGENT
    return PHONE_AGENT if device == "phone" else USER_AGENT


async def _visit(context: Any, walk: Walk, url: str, step) -> None:
    from services.smith.web import TIMEOUT_S
    page = await context.new_page()
    kept: list[dict] = []
    loop = asyncio.get_running_loop()

    async def on_response(response: Any) -> None:
        try:
            req = response.request
            host = urlparse(response.url).hostname or ""
            if not same_site(host, walk.site):
                return
            mime = str(response.headers.get("content-type") or "")
            if not any(mime.lower().startswith(m) for m in callrec.MIME_KEPT):
                return
            body = None
            if mime.lower().startswith("application/json"):
                raw = await response.body()
                if len(raw) <= callrec.MAX_BODY:
                    try:
                        body = json.loads(raw.decode("utf-8", errors="replace"))
                    except ValueError:
                        body = None
            request_body = None
            try:
                request_body = req.post_data_json
            except Exception:  # noqa: BLE001 — not JSON, or none
                request_body = None
            row = callrec.record(req.method, response.url, response.status, mime, request_body=request_body,
                                 response_body=body, page=url, source="web", at=loop.time())
            if row is not None:
                kept.append(row)
        except Exception:  # noqa: BLE001 — a response that cannot be read is not kept
            logger.debug("capture: response not kept", exc_info=True)

    page.on("response", lambda r: asyncio.ensure_future(on_response(r)))
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_S * 1000 // 2)
        status = resp.status if resp else None
        if status in STOP_STATUSES:
            walk.stopped_on = f"{status} at {url}"
            return
        await page.wait_for_timeout(2500)
        census = await page.evaluate(_CENSUS_JS)
        shot = await page.screenshot(type="png", full_page=False)
        meta = store.add_job_file(walk.job, shot, name=f"{census.get('title') or url}"[:120],
                                  media_type="image/png", caption=str(census.get("title") or "")[:120], source=url)
        record = {"url": scrub(page.url), "route": scrub(str(census.get("route") or "")),
                  "title": scrub(str(census.get("title") or ""))[:120],
                  "headings": [scrub(h)[:80] for h in census.get("headings") or []][:20],
                  "forms": [{"action": scrub(str(f.get("action") or ""))[:200], "method": f.get("method"),
                             "fields": [{k: (scrub(str(v)) if isinstance(v, str) else v) for k, v in fld.items()}
                                        for fld in f.get("fields") or []]} for f in census.get("forms") or []],
                  "buttons": [scrub(b)[:80] for b in census.get("buttons") or []][:40],
                  "status": status, "shot": meta["id"], "at": time.time()}
        walk.pages.append(record)
        walk.hosts[urlparse(page.url).hostname or ""] += 1
        walk.calls.extend(kept)
        step(f"Read {record['title'] or record['route']} — {len(kept)} calls")
        for link in census.get("links") or []:
            if followable(link, walk.site) and robots_allows(str(link["href"]), _agent(walk.device)):
                walk.enqueue(str(link["href"]))
    finally:
        await page.close()


async def _walk(walk: Walk, step) -> None:
    from playwright.async_api import async_playwright

    from services.smith.web import _guarded_context
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await _guarded_context(browser, walk.device)
            stop_file = store.job_dir(walk.job["session_id"], walk.job["id"]) / "stop"
            while walk.queue and not walk.stopped_on:
                if stop_file.exists():
                    walk.stopped_on = "stopped by the person"
                    break
                why = walk.out_of_budget()
                if why:
                    walk.stopped_on = why
                    break
                url = walk.queue.pop(0)
                walk.seen.add(url)
                if not robots_allows(url, _agent(walk.device)):
                    walk.gaps.append(f"{url} is closed to robots; not opened")
                    continue
                try:
                    await _visit(context, walk, url, step)
                except Exception as exc:  # noqa: BLE001 — one page failing is a gap
                    walk.gaps.append(f"{url} could not be read: {type(exc).__name__}")
                await asyncio.sleep(PACE_S)
        finally:
            await browser.close()


# --------------------------------------------------------------------------- #
# From calls and pages to evidence
# --------------------------------------------------------------------------- #

def _record_name(path: str) -> str:
    parts = [p for p in path.split("/") if p and p != "{id}" and not (p.startswith("v") and p[1:].isdigit())]
    parts = [p for p in parts if p not in ("api", "graphql", "rest")]
    return (parts[-1] if parts else "record").replace("-", " ").replace("_", " ")


def _fields(shape_: Any) -> list[dict]:
    if isinstance(shape_, dict) and "list" in shape_ and "of" in shape_:
        shape_ = shape_["of"]
    if not isinstance(shape_, dict):
        return []
    out = []
    for name, kind in shape_.items():
        if isinstance(kind, dict):
            kind = "list" if "list" in kind else "object"
        out.append({"name": str(name), "type": str(kind)})
    return out[:60]


def analyse(reference_id: str, calls: list[dict], pages: list[dict], *, source: str) -> list[dict]:
    """Calls and pages as evidence. A JSON answer to a GET is a record seen
    (its fields seen); a short-string field with two values seen is an enum
    seen, with one value an enum guessed; a write is an action seen; a page
    is a screen seen with its forms and controls; the order pages were
    walked is a flow derived."""
    src_type = "har" if source == "har" else "response"
    items: list[dict] = []
    reads: dict[tuple[str, str], list[dict]] = {}
    for c in calls:
        if c.get("method") == "GET" and c.get("response_shape") is not None:
            reads.setdefault((c["host"], c["path"]), []).append(c)
    enum_values: dict[tuple[str, str], set] = {}
    for (host, path), rows in reads.items():
        name = _record_name(path)
        fields = _fields(rows[0].get("response_shape"))
        src = {"type": src_type, "ref": f"GET {path}", "url": rows[0].get("url", "")}
        items.append(ev.item(reference_id, "record", name, standing="observed", source=src,
                             data={"fields": fields, "path": path, "seen": len(rows)}))
        for f in fields:
            items.append(ev.item(reference_id, "field", f"{name}.{f['name']}", standing="observed", source=src,
                                 data={"type": f["type"], "record": name}))
        for c in rows:
            for fpath, values in (c.get("enums") or {}).items():
                enum_values.setdefault((name, fpath), set()).update(values)
    for (name, fpath), values in enum_values.items():
        if len(values) < 1:
            continue
        standing = "observed" if len(values) >= 2 else "inferred"
        items.append(ev.item(reference_id, "enum", f"{name}.{fpath} takes " + ", ".join(sorted(values)[:12]),
                             standing=standing, source={"type": src_type, "ref": name},
                             data={"record": name, "field": fpath, "values": sorted(values)[:12]}))
    for c in calls:
        if c.get("method") in ("POST", "PUT", "PATCH", "DELETE"):
            items.append(ev.item(reference_id, "action", f"{c['method']} {c['path']}", standing="observed",
                                 source={"type": "request" if source != "har" else "har", "ref": c["path"],
                                         "url": c.get("url", "")},
                                 data={"sends": c.get("request_keys") or [], "from": c.get("page") or "",
                                       "status": c.get("status")}))
    titles: list[str] = []
    for p in pages:
        name = p.get("title") or p.get("route") or p.get("url") or "page"
        titles.append(name)
        items.append(ev.item(reference_id, "screen", name, standing="observed",
                             source={"type": "page", "ref": p.get("shot") or "", "url": p.get("url", "")},
                             data={"route": p.get("route"), "headings": p.get("headings") or [],
                                   "forms": p.get("forms") or [], "controls": p.get("buttons") or []}))
    if len(titles) >= 2:
        items.append(ev.item(reference_id, "flow", "Walk: " + " → ".join(titles[:8]), standing="derived",
                             source={"type": "page", "ref": "walk"}, data={"screens": titles[:8]}))
    merged, _ = ev.merge([], items)
    return merged


# --------------------------------------------------------------------------- #
# The study
# --------------------------------------------------------------------------- #

def _step(job: dict, text: str) -> None:
    job["steps"].append({"at": time.time(), "text": text[:300]})
    job["heartbeat"] = time.time()
    store.save_job(job)


def _write_record(job: dict, pages: list[dict], calls: list[dict]) -> None:
    folder = store.job_dir(job["session_id"], job["id"]) / "capture"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pages.jsonl").write_text("\n".join(json.dumps(p, default=str) for p in pages))
    (folder / "calls.jsonl").write_text("\n".join(json.dumps(c, default=str) for c in calls))


def _surface_urls(session_id: str, reference_id: str, site: str) -> list[str]:
    for job in store.jobs(session_id):
        if job.get("kind", "surface") == "surface" and job.get("reference_id") == reference_id:
            urls = [s.get("url") for s in (job.get("dossier") or {}).get("screens") or [] if s.get("url")]
            return [u for u in urls if same_site(urlparse(u).hostname or "", site)]
    return []


def run(session_id: str, job_id: str, reference: dict) -> None:
    """The whole capture, start to finish, on the calling thread."""
    job = store.load_job(session_id, job_id)
    site = urlparse(reference["url"]).hostname or ""
    try:
        session = store.load(session_id)
        from services.drafts_room.drawer import viewport_for
        device = viewport_for((session.get("board") or {}).get("product") or {})
        walk = Walk(job, site, device)
        job["stage"] = "waiting"
        _step(job, "Waiting for the surface study's screens")
        deadline = time.time() + WAIT_FOR_SURFACE_S
        urls: list[str] = []
        while time.time() < deadline:
            urls = _surface_urls(session_id, reference["id"], site)
            if urls:
                break
            time.sleep(5)
        for u in [reference["url"], *urls]:
            walk.enqueue(u)
        job["stage"] = "capturing"
        _step(job, f"Walking {site} from {len(walk.queue)} screens, {PAGES} pages at most")
        asyncio.run(_walk(walk, lambda text: _step(job, text)))
        job["stage"] = "analysing"
        _write_record(job, walk.pages, walk.calls)
        items = analyse(reference["id"], walk.calls, walk.pages, source="web")
        for g in walk.gaps:
            items.append(ev.item(reference["id"], "gap", g, standing="unknown", source={"type": "page", "ref": "walk"}))
        job["evidence"] = items
        job["capture"] = {"pages": len(walk.pages), "calls": len(walk.calls), "hosts": sorted(walk.hosts),
                          "stopped_on": walk.stopped_on}
        got = ev.counts(items)
        job.update(status="done", stage="done", finished=time.time(),
                   summary=(f"Read {len(walk.pages)} pages and kept {len(walk.calls)} calls on {site}; "
                            + ", ".join(f"{v} {k}" for k, v in got.items() if v)
                            + (f". Stopped: {walk.stopped_on}" if walk.stopped_on else ".")))
        _step(job, "Capture finished")
        _cards_after(session_id, reference["id"])
    except Exception as exc:  # noqa: BLE001 — a failed study says why
        logger.exception("capture %s", job_id)
        job.update(status="failed", error=f"{type(exc).__name__}: {str(exc)[:300]}", finished=time.time())
        store.save_job(job)


def _cards_after(session_id: str, reference_id: str) -> None:
    """The card writer runs by code when a deep study ends: cards are what
    the drafting side reads, and nobody should have to remember to ask."""
    try:
        from services.drafts_room import cards
        cards.write(session_id, reference_id)
    except Exception:  # noqa: BLE001 — cards can be asked for again
        logger.exception("capture: the cards of %s were not written", reference_id)


def start(session: dict, reference: dict, focus: str = "") -> dict:
    """A deep study of a public web product, started on its own thread."""
    job = store.new_job(session["id"], reference["name"], focus, kind="deep", source="web",
                        reference_id=reference["id"])
    threading.Thread(target=run, args=(session["id"], job["id"], dict(reference)), daemon=True,
                     name=f"capture-{job['id']}").start()
    return job


def from_recording(session: dict, reference: dict, calls: list[dict]) -> dict:
    """The person's own recording as a finished deep study."""
    job = store.new_job(session["id"], reference["name"], "", kind="deep", source="har",
                        reference_id=reference["id"])
    job["stage"] = "analysing"
    _write_record(job, [], calls)
    items = analyse(reference["id"], calls, [], source="har")
    job["evidence"] = items
    job["capture"] = {"pages": 0, "calls": len(calls), "hosts": sorted({c.get("host") for c in calls if c.get("host")}),
                      "stopped_on": None}
    got = ev.counts(items)
    job.update(status="done", stage="done", finished=time.time(),
               summary=f"The person's recording: {len(calls)} calls kept; "
                       + ", ".join(f"{v} {k}" for k, v in got.items() if v) + ".")
    _step(job, "Recording analysed")
    threading.Thread(target=_cards_after, args=(session["id"], reference["id"]), daemon=True,
                     name=f"cards-{job['id']}").start()
    return job


__all__ = ["PAGES", "PACE_S", "HOSTS", "MINUTES", "STOP_STATUSES", "robots_allows", "same_site", "followable",
           "Walk", "analyse", "run", "start", "from_recording"]
