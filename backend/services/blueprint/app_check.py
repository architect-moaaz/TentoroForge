"""The whole application is used, as each kind of person, before the build is done.

The build knew when a page was missing; it could not know when a page was
wrong, because nothing ever opened one. "Verify & fix" did — every page in a
browser, every control pressed — but only when offered and accepted, and on
forge-v3 it could not run at all until 2026-10-01. Testers found the rest:
an admin landing on the customers' menu, a child page that 404'd, slots
showing dates from 2001, a duplicate check refusing every new name.

So after the pages are finished and the processes run through, every page is
opened as every role it is for — signed in with the seeded logins, on a copy
of the database — and used: its status, where it sends the person, every
browser error, the page with no data and on a record that does not exist,
every control pressed from a fresh load, every read the server swallowed, and
what the screen actually shows. No model judges any of it; each finding is a
fact the browser or the server reported.

A page with findings goes to Smith, unattended, with those findings and the
role they were seen as, to fix the cause wherever it lives; the page is then
checked again. What still fails after `ROUNDS` is recorded by name, and the
completion message says it (`runtime.check`).
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

ROUNDS = 2
#: Steps per page repair: read, fix, write, and the try that proves it.
STEPS = 12
#: Pages repaired in one build. A build with more failing pages than this has
#: a cause bigger than any one page; the rest are reported, not ground through.
MAX_REPAIRS = 15
#: Roles checked at once against the one running copy.
PARALLEL = 3


# --------------------------------------------------------------------------- #
# What the screen shows
# --------------------------------------------------------------------------- #

_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_BROKEN_WORDS = re.compile(r"\b(undefined|NaN|Invalid Date)\b|\[object Object\]")
_CRASH_TEXT = re.compile(r"Application error: a (client|server)-side exception|Unhandled Runtime Error|"
                         r"Something went wrong|Internal Server Error", re.I)
_MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
#: A label read as a date: V8 reads "Start Time 12" as 1 December 2001.
_LABEL_DATE = re.compile(rf"\b(0?1\s+({_MONTHS})[a-z]*\.?,?\s+2001|({_MONTHS})[a-z]*\.?\s+0?1,?\s+2001|"
                         rf"2001-\d\d-01|0?1/\d\d?/2001)\b")


def _placeholder_pattern(doc: dict) -> re.Pattern | None:
    """`Full Name 3`, `Phone 1`, `Child 2`: a field's or record type's own name
    with a row number — what sample data falls back to when it has no value."""
    from services.blueprint.projection import _humanise_field
    names: set[str] = set()
    for e in (doc.get("data") or {}).get("entities") or []:
        if not isinstance(e, dict) or e.get("status") == "DEPRECATED":
            continue
        if e.get("name"):
            names.add(_humanise_field(str(e["name"])))
        for f in e.get("fields") or []:
            if isinstance(f, dict) and f.get("name") and str(f.get("name")) != "id" \
                    and not str(f.get("name")).endswith("Id"):
                names.add(_humanise_field(str(f["name"])))
    names = {n for n in names if len(n) >= 3}
    if not names:
        return None
    alts = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.compile(rf"\b({alts}) \d{{1,3}}\b")


def screen_findings(text: str, doc: dict) -> list[str]:
    """What a person would read as broken on a page's visible text."""
    text = text or ""
    out: list[str] = []
    crash = _CRASH_TEXT.search(text)
    if crash:
        out.append(f"the page says \"{crash.group(0)}\"")
    ids = sorted(set(_UUID.findall(text)))
    if ids:
        out.append(f"it shows raw record ids ({ids[0]}{' and others' if len(ids) > 1 else ''}) where a person "
                   "expects a name")
    broken = sorted({m.group(0) for m in _BROKEN_WORDS.finditer(text)})
    if broken:
        out.append(f"it shows {', '.join(repr(b) for b in broken)} — a value that was never filled in")
    dates = sorted({m.group(0) for m in _LABEL_DATE.finditer(text)})
    if dates:
        out.append(f"it shows dates in 2001 ({dates[0]}) — usually a label or a time read as a date")
    pattern = _placeholder_pattern(doc)
    if pattern:
        found = sorted({m.group(0) for m in pattern.finditer(text)})
        if len(found) >= 2:
            out.append(f"it shows placeholder values ({', '.join(found[:4])}) rather than real ones — "
                       "the sample records carry labels, not values")
    return out


# --------------------------------------------------------------------------- #
# Who opens what
# --------------------------------------------------------------------------- #

def _roles(doc: dict) -> dict[str, str]:
    return {str(r.get("id")): str(r.get("name") or r.get("id")) for r in doc.get("roles") or []
            if isinstance(r, dict) and r.get("status") != "DEPRECATED"}


def visits(doc: dict) -> list[dict]:
    """`{page, route, name, entity, as}` — every live page, once per role it is
    for; a page for nobody in particular as the administrator; sign-in pages
    signed out."""
    from services.blueprint.account_model import admin_role
    from services.blueprint.scope import built_view

    view = built_view(doc)
    roles = _roles(view)
    admin = admin_role(view) or "Admin"
    ents = {str(e.get("id")): str(e.get("name")) for e in (view.get("data") or {}).get("entities") or []
            if isinstance(e, dict)}
    out: list[dict] = []
    for p in view.get("pages") or []:
        if not isinstance(p, dict) or not p.get("route") or str(p.get("status") or "").upper() in ("DEPRECATED", "REMOVED"):
            continue
        base = {"page": str(p.get("id")), "route": str(p["route"]), "name": str(p.get("name") or p["route"]),
                "entity": ents.get(str((p.get("data") or {}).get("primaryEntity") or ""))}
        if p.get("pattern") == "auth":
            out.append({**base, "as": "signed out"})
            continue
        users = [roles.get(str(u), str(u)) for u in p.get("users") or []]
        for role in (users or [admin]):
            out.append({**base, "as": role})
    return out


# --------------------------------------------------------------------------- #
# Reading what the browser saw
# --------------------------------------------------------------------------- #

def shot_findings(shot: dict, visit: dict, doc: dict) -> list[str]:
    """Facts about one page opened as one person that mean it does not work."""
    from services.blueprint.page_review import BROKEN_OUTCOMES
    if shot.get("skipped"):
        return []
    out: list[str] = []
    status = shot.get("status")
    if isinstance(status, int) and status >= 400:
        out.append(f"it answers HTTP {status}" + (" — the role it is for is refused" if status == 403 else ""))
    landed = str(shot.get("landed") or "")
    if visit["as"] != "signed out" and re.search(r"/(login|signin|sign-in)\b", landed):
        out.append(f"it sends a signed-in {visit['as']} to {landed}")
    for e in (shot.get("errors") or [])[:4]:
        out.append(f"the browser reports: {str(e)[:200]}")
    empty = (shot.get("states") or {}).get("empty") or {}
    if (isinstance(empty.get("status"), int) and empty["status"] >= 500) or empty.get("errors"):
        why = (empty.get("errors") or [f"HTTP {empty.get('status')}"])[0]
        out.append(f"with nothing to show it breaks ({str(why)[:200]}) instead of saying there is nothing yet")
    missing = (shot.get("states") or {}).get("missing") or {}
    if (isinstance(missing.get("status"), int) and missing["status"] >= 500) or missing.get("errors"):
        why = (missing.get("errors") or [f"HTTP {missing.get('status')}"])[0]
        out.append(f"on a record that does not exist it breaks ({str(why)[:200]}) instead of saying so")
    for c in shot.get("controls") or []:
        verdict = BROKEN_OUTCOMES.get(str(c.get("outcome")))
        if verdict:
            out.append(f"{c.get('kind') or 'control'} \"{c.get('label')}\" {verdict}"
                       + (f" ({str(c.get('detail'))[:200]})" if c.get("detail") else ""))
    out += screen_findings(str(shot.get("text") or ""), doc)
    return out


def _swallowed_by_entity(lines: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in lines:
        m = re.search(r"\[forge:swallowed\] \w+ (\S+) failed", line)
        if m:
            out.setdefault(m.group(1), []).append(line[:300])
    return out


# --------------------------------------------------------------------------- #
# The check
# --------------------------------------------------------------------------- #

def _entries(app: Any, doc: dict, batch: list[dict]) -> list[dict]:
    from services.smith.trials import _role, _session
    out = []
    for v in batch:
        entry: dict[str, Any] = {"id": f"{v['page']}::{v['as']}", "route": v["route"], "entity": v["entity"]}
        if v["as"] == "signed out":
            entry["anonymous"] = True
        else:
            try:
                _name, is_admin = _role(doc, v["as"])
            except ValueError:
                is_admin = True
            if not is_admin:
                who, jar = _session(app, doc, v["as"])
                entry["as"], entry["cookies"] = who, jar
        out.append(entry)
    return out


def check_pages(app: Any, doc: dict, todo: list[dict], out_dir: Path, *,
                server_said: Callable[[], list[str]] = lambda: []) -> dict[str, dict]:
    """Open `todo` (from `visits`) and read what happened: `{page: {name,
    route, findings: [(as, finding)]}}` for every page visited."""
    from services.blueprint.page_review import ReviewUnavailable, run_shots

    by_role: dict[str, list[dict]] = {}
    for v in todo:
        by_role.setdefault(v["as"], []).append(v)
    server_said()                                   # what was printed before belongs to no page

    def shoot(role: str) -> tuple[str, list[dict]]:
        batch = by_role[role]
        safe = re.sub(r"[^a-z0-9]+", "-", role.lower()).strip("-") or "role"
        try:
            shots = run_shots(app, _entries(app, doc, batch), out_dir / safe,
                              probe=role != "signed out", states=role != "signed out")
        except ReviewUnavailable as exc:
            shots = [{"id": f"{v['page']}::{role}", "errors": [f"the page could not be opened: {exc}"]}
                     for v in batch]
        return role, shots

    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        results = list(pool.map(shoot, list(by_role)))
    swallowed = _swallowed_by_entity(server_said())

    report: dict[str, dict] = {}
    for role, shots in results:
        by_id = {str(s.get("id")): s for s in shots if isinstance(s, dict)}
        for v in by_role[role]:
            page = report.setdefault(v["page"], {"name": v["name"], "route": v["route"], "findings": []})
            shot = by_id.get(f"{v['page']}::{role}")
            if shot is None:
                page["findings"].append((role, "it could not be opened at all — the browser reported nothing for it"))
                continue
            page["findings"] += [(role, f) for f in shot_findings(shot, v, doc)]
            for line in swallowed.get(str(v["entity"]), []):
                page["findings"].append((role, f"the server could not read its {v['entity']} records: {line}"))
    return report


def fault_ask(page_id: str, item: dict) -> str:
    seen = "\n".join(f"- as {who}: {what}" for who, what in item["findings"][:20])
    return (
        f"The build opened the page {item['name']} ({item['route']}, {page_id}) as the people it is for "
        f"and used it the way they would. This did not work:\n{seen}\n\n"
        "Find the cause and fix it where it lives — the page's code, a workflow, the data model, a "
        "rule, who may open it, or sample records that carry labels instead of values. Then open the "
        "page again as the same person and press what was broken: the page is finished only when it "
        "works for them. Nobody is waiting to answer questions: decide from the definition and act."
    )


def check_app(svc: Any, output_dir: str, *args: Any, **kwargs: Any) -> dict:
    """See `_check_app`; its model calls are the build's spend."""
    from services.build_usage import usage_scope
    with usage_scope(agent="app_check", output_dir=str(output_dir), phase="build", kind="build"):
        return _check_app(svc, output_dir, *args, **kwargs)


def _check_app(svc: Any, output_dir: str, *, emit: Callable[[str, dict], None] | None = None,
               run_turn: Callable[..., dict] | None = None,
               app_factory: Callable[[Path], Any] | None = None,
               rounds: int = ROUNDS, record: bool = True) -> dict:
    """Use every page as every role; repair what fails; returns the check's
    summary (also written to `runtime.check`)."""
    from services.blueprint.page_repair import _ledger

    say = emit or (lambda _e, _d: None)
    if run_turn is None:
        from services.smith4.platform import smith_result as run_turn
    if app_factory is None:
        from services.blueprint.page_review import RunningApp

        def app_factory(root: Path) -> Any:
            return RunningApp(root, log=Path(output_dir) / ".forge" / "check" / "server.log")

    def reload() -> None:
        from services.blueprint.service import BlueprintService
        try:
            svc.doc = BlueprintService.load(output_dir=output_dir).doc
        except Exception:  # noqa: BLE001
            logger.warning("[app-check] could not reload the Blueprint", exc_info=True)

    all_visits = visits(svc.doc)
    if not all_visits:
        return {"pages": 0, "working": 0, "fixed": [], "left": []}
    pages_total = len({v["page"] for v in all_visits})
    say("message", {"text": f"Opening every page as each kind of person it is for "
                            f"({pages_total} pages) and trying what they would do."})
    todo = all_visits
    fixed: list[str] = []
    last: dict[str, dict] = {}
    log = Path(output_dir) / ".forge" / "check" / "server.log"
    with _ledger(output_dir if record else None, pages_total, node="app_check") as ledger:
        for round_ in range(1, rounds + 2):
            if not todo:
                break
            log.parent.mkdir(parents=True, exist_ok=True)
            app = app_factory(Path(output_dir) / "app")
            try:
                running = app.__enter__()
                seen_at = [0]

                def server_said() -> list[str]:
                    try:
                        data = log.read_bytes()
                    except OSError:
                        return []
                    fresh, seen_at[0] = data[seen_at[0]:], len(data)
                    return [l.strip() for l in fresh.decode("utf-8", "replace").splitlines() if l.strip()]

                report = check_pages(running, svc.doc, todo, Path(output_dir) / ".forge" / "check" / f"round-{round_}",
                                     server_said=server_said)
            except Exception as exc:  # noqa: BLE001 — a check that cannot run is said, not fatal
                logger.warning("[app-check] the app could not be run: %s", exc)
                report = {v["page"]: {"name": v["name"], "route": v["route"],
                                      "findings": [(v["as"], f"the app could not be started to check it: {exc}")]}
                          for v in todo}
                last.update(report)
                break
            finally:
                try:
                    app.__exit__(None, None, None)
                except Exception:  # noqa: BLE001
                    pass
            last.update(report)
            failing = {pid: item for pid, item in report.items() if item["findings"]}
            for pid, item in report.items():
                if not item["findings"] and round_ > 1:
                    fixed.append(item["route"])
                ledger.node_subject("app_check", pid, len([1 for i in last.values() if not i["findings"]]),
                                    pages_total, not item["findings"])
            if not failing or round_ > rounds:
                break
            for i, (pid, item) in enumerate(failing.items()):
                if i >= MAX_REPAIRS:
                    break
                ledger.repair("app_check", pid, round_, rounds, "; ".join(f for _w, f in item["findings"][:3])[:600])
                say("message", {"text": f"{item['name']} ({item['route']}) does not work yet — "
                                        f"{item['findings'][0][1][:160]}. Fixing it."})
                try:
                    run_turn("", output_dir, fault_ask(pid, item), max_steps=STEPS, unattended=True)
                except Exception as exc:  # noqa: BLE001 — one repair never ends the build
                    logger.warning("[app-check] %s: %s", item["route"], exc)
                reload()
            repaired = set(list(failing)[:MAX_REPAIRS])
            todo = [v for v in visits(svc.doc) if v["page"] in repaired]

    left = [{"page": pid, "name": item["name"], "route": item["route"],
             "findings": [f"as {w}: {f}" for w, f in item["findings"][:8]]}
            for pid, item in last.items() if item["findings"]]
    for item in left:
        ledger_note = "; ".join(item["findings"][:3])[:600]
        logger.info("[app-check] still failing %s: %s", item["route"], ledger_note)
    summary = {"pages": pages_total, "working": pages_total - len(left),
               "fixed": sorted(set(fixed)), "left": left}
    runtime = dict(svc.doc.get("runtime") or {})
    issues = [i for i in runtime.get("issues") or [] if not (isinstance(i, dict) and i.get("kind") == "page_check")]
    issues += [{"kind": "page_check", "page": t["page"], "name": t["name"], "route": t["route"],
                "detail": " | ".join(t["findings"])[:600]} for t in left]
    runtime["issues"] = issues
    runtime["check"] = {"pages": summary["pages"], "working": summary["working"],
                        "fixed": summary["fixed"], "failing": [t["route"] for t in left]}
    svc.doc["runtime"] = runtime
    try:
        svc.save()
    except Exception:  # noqa: BLE001
        logger.warning("[app-check] could not record the check", exc_info=True)
    return summary


__all__ = ["MAX_REPAIRS", "ROUNDS", "check_app", "check_pages", "fault_ask", "screen_findings",
           "shot_findings", "visits"]
