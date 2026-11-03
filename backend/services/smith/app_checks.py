"""Whole-application checks Smith runs in one step (`run_checks`, 2026-10-31).

What DITANS needed in its last two days was done by hand, a screen or a
process at a time, because no check asked the whole question:

* `workflows` — every process a person starts, run on a copy of the data with
  inputs chosen from its real records (312 of them, by a hand-written loop);
* `drawing` — every drawn screen shown by a page, and every page showing a
  drawing (pages that drew nothing were retired by hand);
* `words` — every word the drawn screens show, in every language the app is
  shown in (6,533 Arabic words, by hand);
* `logins` — every demo person signs in, belongs to an organisation when the
  app has them, and lands on a screen they may open;
* `newcomers` — a brand-new person of every role that signs up walks their
  whole menu: a screen that crashes, answers "not found" or turns them away
  is a line (DITANS QA, 2026-11-02 — every one was found by a human tester);
* `looks` — the measured look of every screen named (`open_page look`,
  without the eye), so one call sweeps a portal for the arrow cursor, dead
  drawn controls and cut-off menus.

Each returns the `{total, green, red, untried}` shape `trials._check_lines`
reads, so they read like the build's own checks.
"""
from __future__ import annotations

import http.cookiejar
import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

#: Screens one `looks` call measures; the rest are named for the next call.
LOOKS_PER_CALL = 12


def _node(ref: str) -> str:
    """A frame by its node id alone: pages hold `6:66380`, a second design's
    refs carry their source in front."""
    return str(ref or "").split("/")[-1]


def _live_pages(doc: dict) -> list[dict]:
    return [p for p in doc.get("pages") or [] if isinstance(p, dict) and p.get("status") != "DEPRECATED"
            and p.get("route")]


# ── every workflow ──────────────────────────────────────────────────────────


def workflows(bench: Any, doc: dict, output_dir: str, only: list[str] | None = None) -> dict:
    """Every manual process run on the bench's copy, repaired by nobody: the
    process trials' check-only mode, each judged by what it wrote and by
    whether the person who ran it can then see it."""
    from services.blueprint.process_trials import manual_workflows, prove_processes
    from services.blueprint.service import BlueprintService

    flows = manual_workflows(doc)
    wanted = {str(w).strip().lower() for w in only or [] if str(w).strip()}
    ids = {str(f["id"]) for f in flows if not wanted or str(f["id"]).lower() in wanted
           or str(f.get("name") or "").strip().lower() in wanted}
    if not ids:
        return {"total": 0, "green": [], "red": [], "untried": []}
    svc = BlueprintService.load(output_dir=output_dir)
    out = prove_processes(svc, output_dir, rounds=0, record=False, only=ids,
                          bench_factory=lambda _dir: bench)
    return {"total": len(ids), "green": list(out.get("passed") or []),
            "red": [{"label": r.get("name"), "why": r.get("reason")} for r in out.get("left") or []],
            "untried": [{"label": r.get("name"), "why": r.get("reason")} for r in out.get("untried") or []]}


# ── the drawing ─────────────────────────────────────────────────────────────


def drawing(doc: dict) -> dict:
    """Drawn screens no page shows, and pages that show no drawing — in an
    application whose design is its specification. A phone drawing counts as
    shown when its desktop twin is."""
    from services.blueprint.page_planner import page_frames
    from services.drawn.convert import _spec_frames
    from services.drawn.pairs import wide_of

    frames = {_node(str(f["nodeId"])): str(f.get("name") or f["nodeId"]) for _s, f in _spec_frames(doc)}
    if not frames:
        return {"total": 0, "green": [], "red": [], "untried": [],
                "note": "this application is not built from a drawn design"}
    pages = _live_pages(doc)
    shown = {_node(f) for p in pages for f in page_frames(p)}
    twins = {_node(k): _node(v) for k, v in wide_of(doc).items()}
    green, red = [], []
    for node, name in frames.items():
        if node in shown or twins.get(node) in shown:
            green.append(name)
        else:
            red.append({"label": f"drawn screen \"{name}\"",
                        "why": "no page shows it — give it a page, or set it aside only if it is not a screen "
                               "(an email, a fragment drawn into another)"})
    for p in pages:
        if str(p.get("pattern") or "") == "auth":
            continue
        if page_frames(p):
            green.append(str(p.get("route")))
            continue
        red.append({"label": f"screen {p.get('name')} ({p.get('route')})",
                    "why": "shows no drawing — retire it if the design has no such screen, else bind it to "
                           "the frame it stands for"})
    return {"total": len(frames) + len([p for p in pages if str(p.get('pattern') or '') != 'auth']),
            "green": green, "red": red, "untried": []}


# ── the words ───────────────────────────────────────────────────────────────


def words(doc: dict) -> dict:
    """Every word the drawn screens show, per language the app is shown in
    besides its own."""
    from services.blueprint.languages import languages
    from services.drawn.words import shown_words, untranslated

    tags = languages(doc)[1:]
    if not tags or not any(isinstance(v, dict) for v in doc.get("drawnViews") or []):
        return {"total": 0, "green": [], "red": [], "untried": [],
                "note": "no drawn screens shown in a second language"}
    total = len(shown_words(doc))
    red, green = [], []
    for tag in tags:
        left = untranslated(doc, tag)
        if left:
            red.append({"label": f"{tag}: {len(left)} of {total} words untranslated",
                        "why": "e.g. " + ", ".join(f"\"{w[:40]}\"" for w in left[:8])
                               + " — `translate_words` fills them"})
        else:
            green.append(tag)
    return {"total": len(tags), "green": green, "red": red, "untried": []}


# ── the demo logins ─────────────────────────────────────────────────────────


def _sign_in(base: str, email: str, password: str) -> tuple[dict, Any]:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    csrf = json.loads(opener.open(f"{base}/api/auth/csrf", timeout=60).read() or b"{}").get("csrfToken", "")
    form = urllib.parse.urlencode({"csrfToken": csrf, "email": email, "password": password, "json": "true"}).encode()
    try:
        opener.open(urllib.request.Request(f"{base}/api/auth/callback/credentials", data=form), timeout=60)
    except urllib.error.HTTPError:
        pass                                   # a refused sign-in answers 401; the session says so
    session = json.loads(opener.open(f"{base}/api/auth/session", timeout=60).read() or b"{}") or {}
    return session, opener


def logins(bench: Any, doc: dict) -> dict:
    """Every demo person: signs in with the seeded password, holds the role it
    is for, belongs to an organisation when the app has organisations, and
    lands on a screen it may open."""
    from services.blueprint.account_model import demo_logins
    from services.blueprint.page_review import ADMIN_PASSWORD, _query
    from services.blueprint.projection import tenancy_policy

    app = bench.app()
    policy = tenancy_policy(doc)
    members = set(policy.get("memberRoles") or []) if policy.get("kind") == "organisation" else set()
    green, red = [], []
    people = demo_logins(doc)
    for email, role in people:
        label = f"{role} ({email})"
        try:
            session, opener = _sign_in(app.base, email, ADMIN_PASSWORD)
        except Exception as exc:  # noqa: BLE001 — a login that cannot be tried is a line
            red.append({"label": label, "why": f"the sign-in could not be tried: {type(exc).__name__}: {exc}"[:200]})
            continue
        user = session.get("user") or {}
        if not user:
            red.append({"label": label, "why": "cannot sign in with the seeded password — no such login, or "
                                               "its password is not the seed's"})
            continue
        held = str(user.get("role") or "")
        if held and held != role:
            red.append({"label": label, "why": f"signs in holding the role {held}, not {role}"})
            continue
        if role in members:
            safe = email.replace("'", "''")
            rows = _query(app, f"select coalesce(active_org_id::text, '') from users where email = '{safe}'")
            if not rows or not rows[0] or not rows[0][0]:
                red.append({"label": label, "why": "belongs to no organisation, so every screen scoped to one "
                                                   "is empty for them — make them a member of one of their kind"})
                continue
        try:
            res = opener.open(f"{app.base}/", timeout=120)
            landed, status = urllib.parse.urlparse(res.geturl()).path, res.status
        except urllib.error.HTTPError as exc:
            landed, status = urllib.parse.urlparse(exc.geturl() or "/").path, exc.code
        if status >= 400 or landed.rstrip("/") in ("/login", "/signin", "/sign-in", "/403"):
            red.append({"label": label, "why": f"after signing in, opening the app lands on {landed} (HTTP {status})"})
            continue
        green.append(f"{label} → {landed}")
    return {"total": len(people), "green": green, "red": red, "untried": []}


# ── a newcomer's first walk ─────────────────────────────────────────────────

#: Menu screens one newcomer opens per call; the rest are named.
NEWCOMER_SCREENS = 30

#: An error the server render threw, as the page's stream carries it.
_THROWN = re.compile(r'E\{\\"digest\\":\\"([^"\\]*)\\"(?:,\\"name\\":\\"([^"\\]*)\\")?'
                     r'(?:,\\"message\\":\\"((?:[^"\\]|\\\\.){0,200}))?')


def _thrown(html: str) -> list[tuple[str, str, str]]:
    """`(digest, name, message)` of every error the server render threw."""
    return [(m.group(1), m.group(2) or "Error", (m.group(3) or "").replace("\\\\", "\\"))
            for m in _THROWN.finditer(html)]


def _menu_routes(doc: dict, role: str = "") -> list[str]:
    """Every screen a menu leads to — the drawn shell of `role`'s portal (every
    shell when it has none): its entries and buttons; else the app's navigation."""
    from services.drawn.project import action_routes, nav_routes, portal_routes, role_portals
    out: list[str] = []
    shells = [v for v in doc.get("drawnViews") or [] if isinstance(v, dict) and v.get("kind") == "shell"]
    own = role_portals(doc, portal_routes(doc, shells)).get(role) if role and shells else None
    for v in shells:
        if own and str(v.get("key")) != own:
            continue
        out += [str(e.get("href")) for e in nav_routes(doc, v) if str(e.get("href") or "#") != "#"]
        out += list(action_routes(doc, v).values())
    if not out:
        for item in (doc.get("navigation") or {}).get("items") or [] if isinstance(doc.get("navigation"), dict) else []:
            if isinstance(item, dict) and item.get("route"):
                out.append(str(item["route"]))
    return [r for r in dict.fromkeys(out) if r.startswith("/") and "[" not in r]


def _may_open(doc: dict, role: str) -> set[str]:
    from services.blueprint.projection import restricted_roles
    out = set()
    for p in _live_pages(doc):
        access = str(p.get("access") or "authenticated")
        if access != "role_restricted" or role in (restricted_roles(doc, p) or []):
            out.add(str(p.get("route")))
    return out


def _newcomer_values(doc: dict, email: str) -> dict:
    from services.blueprint.account_model import account_fields
    values: dict[str, Any] = {}
    for f in account_fields(doc):
        if not f.get("required"):
            continue
        kind = f.get("kind")
        values[f["name"]] = (email if kind == "email" else 1 if kind == "number" else True if kind == "checkbox"
                             else (f.get("options") or [{}])[0].get("value", "") if kind == "select"
                             else "2000-01-01" if kind == "date" else "+15550100" if kind == "tel" else "Newcomer")
    return values


def _open(opener: Any, url: str, waits: int = 6) -> Any:
    """Open `url`, waiting out a dev server that restarted itself (Next restarts
    near its memory limit, mid-walk, on an app of DITANS's size)."""
    import time
    for attempt in range(waits + 1):
        try:
            return opener.open(url, timeout=180)
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, ConnectionError) as exc:
            if attempt == waits:
                raise
            logger.info("[newcomers] %s: %s — waiting for the server", url, exc)
            time.sleep(10)


def newcomers(bench: Any, doc: dict, only: list[str] | None = None) -> dict:
    """A brand-new person of every role that signs up, with nothing of their
    own yet, opens every screen their menu offers them. What a newcomer meets
    first is what the build's demo people never see: no organisation, no
    records, a name typed a minute ago. A crash, a "not found" or a refusal is
    a line; so is a sign-up that does not let them in."""
    import secrets

    from services.blueprint.account_model import signup_roles

    app = bench.app()
    roles = [r for r in signup_roles(doc) if not only or r in only]
    green, red, untried = [], [], []
    for role in roles:
        tag = re.sub(r"[^a-z0-9]+", ".", role.lower()).strip(".") or "person"
        email, password = f"newcomer.{tag}.{secrets.token_hex(3)}@example.com", "Nc-" + secrets.token_urlsafe(10)
        body = {"name": f"New {role}", "email": email, "password": password, "accountType": role,
                "account": _newcomer_values(doc, email)}
        try:
            req = urllib.request.Request(f"{app.base}/api/auth/signup", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=120)
            session, opener = _sign_in(app.base, email, password)
        except urllib.error.HTTPError as exc:
            said = exc.read().decode("utf-8", "replace")[:200]
            red.append({"label": f"a new {role}", "why": f"cannot sign up (HTTP {exc.code}): {said}"})
            continue
        except Exception as exc:  # noqa: BLE001 — a walk that cannot start is a line
            untried.append(f"a new {role}: {type(exc).__name__}: {exc}"[:200])
            continue
        if not (session.get("user") or {}):
            red.append({"label": f"a new {role}", "why": "signed up, then could not sign in"})
            continue
        allowed = _may_open(doc, role)
        walk = ["/"] + [r for r in _menu_routes(doc, role) if r in allowed]
        for route in walk[:NEWCOMER_SCREENS]:
            label = f"{route} as a new {role}"
            try:
                res = _open(opener, f"{app.base}{route}")
                status, landed, html = res.status, urllib.parse.urlparse(res.geturl()).path, \
                    res.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                status, landed = exc.code, urllib.parse.urlparse(exc.geturl() or route).path
                html = exc.read().decode("utf-8", "replace") if exc.fp else ""
            except Exception as exc:  # noqa: BLE001
                untried.append(f"{label}: {type(exc).__name__}"[:200])
                continue
            # WHAT THE SERVER RENDER THREW, read from the page's own stream: Next
            # answers 200 and sends a not-found or a crash as an error entry the
            # browser draws later (the jobs screen QA saw as 404, D-61).
            thrown = _thrown(html)
            # A rejection the code caught travels too, with no digest (a missing
            # optional file read in a try): only a digest is a render that broke.
            crash = next((t for t in thrown if t[0] and not t[0].startswith("NEXT_")), None)
            missing = any(t[0].startswith("NEXT_HTTP_ERROR_FALLBACK;404") for t in thrown)
            refused = any(t[0].startswith(("NEXT_HTTP_ERROR_FALLBACK;403", "NEXT_HTTP_ERROR_FALLBACK;401"))
                          for t in thrown)
            if status >= 500 or crash:
                red.append({"label": label, "why": "the screen crashes"
                            + (f": {crash[1]}: {crash[2]}" if crash and crash[2] else f" (HTTP {status})")
                            + " — a newcomer's records are empty or unset; show what an empty one looks like"})
            elif refused:
                red.append({"label": label, "why": "the screen refuses them — the menu offers what this role "
                                                   "may not open"})
            elif status == 404 or missing:
                red.append({"label": label, "why": "answers \"not found\" — its loader found nothing for a "
                                                   "newcomer (no organisation, no records); show the empty state"})
            elif landed.rstrip("/") in ("/login", "/signin", "/sign-in", "/403") or status == 403:
                red.append({"label": label, "why": f"turns them away to {landed} — the menu offers a screen this "
                                                   "role may not open"})
            else:
                green.append(label)
        if len(walk) > NEWCOMER_SCREENS:
            untried.append(f"a new {role}: {len(walk) - NEWCOMER_SCREENS} more menu screens (name them in `routes`)")
    return {"total": len(green) + len(red), "green": green, "red": red, "untried": untried}


# ── the measured look, many screens ─────────────────────────────────────────


def looks(bench: Any, doc: dict, routes: list[str], as_: str) -> list[str]:
    """`open_page look` without the eye, over many screens in one browser:
    the measured faults only, a screen per line."""
    from pathlib import Path

    from services.blueprint.page_review import run_shots
    from services.smith.trials import CHECK_RED, _entry, look_lines

    named = [str(r) for r in routes] or [str(p["route"]) for p in _live_pages(doc) if "[" not in str(p["route"])]
    batch, rest = named[:LOOKS_PER_CALL], named[LOOKS_PER_CALL:]
    entries = [_entry(bench, doc, r, as_)[1] for r in batch]
    for i, e in enumerate(entries):
        e["id"] = f"look-{i}"
    shots = run_shots(bench.app(), entries, Path(bench.output_dir) / ".forge" / "trials" / "shots",
                      probe=False, states=False, look=True)
    lines, wrong = [], 0
    for shot in shots:
        said = look_lines(shot.get("look") or {})
        bad = [l for l in said if CHECK_RED in l]
        wrong += bool(bad)
        lines.append(f"  {shot.get('route')}: " + ("not right" if bad else "nothing measured is wrong")
                     + (f" — {shot['unavailable']}" if shot.get("unavailable") else ""))
        lines += [f"  {l}" for l in bad]
    head = f"checks · looks: {len(shots) - wrong} of {len(shots)} screens measure right"
    if rest:
        lines.append(f"  ({len(rest)} more screens were not measured this call; name them in another: "
                     + ", ".join(rest[:12]) + ("…" if len(rest) > 12 else "") + ")")
    return [head] + lines


__all__ = ["LOOKS_PER_CALL", "drawing", "logins", "looks", "words", "workflows"]
