"""After hand-over: check the whole application against the bar, then fix
the reds to green — by cause, capped by yield — saying each as it turns.

The application is the person's the moment it boots (`_run_dag` hands it
over with the scorecard). This runs after, in the background, and does what
three loops used to do inside the build turn, one after another, each with
its own rounds: page repair, process trials, the app check (ECom L2 spent an
hour and a half in them while the person saw "Building…"). Here each check
runs ONCE (`rounds=0`) and writes its criterion; the route, access, rule and
domain checks are added on the same running copy; then ONE loop over every
red, grouped by what a repair is addressed to — a page, a process, a rule, a
record type — sends each group to Smith unattended, checks only that
group's items again, and counts what turned green. It stops after
`FIX_TURNS`, or after `DRY_STOP` turns in a row that turned nothing — a
fault that two turns did not move is said, not paid for a third time.

Page groups are fixed in parallel (different files); anything that
re-projects the application — a process, a rule, a record type — alone.
A person's own Smith turn on the same tree is waited for, never raced.
What a check could not try is never here: `untried` is the check's own
failure, said as such on the card and left alone.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from services.blueprint import scorecard as sc

logger = logging.getLogger(__name__)

#: Fix turns per hand-over (each turn is one Smith turn per group in the batch).
FIX_TURNS = 6
#: Turns in a row that turned nothing green before the loop stops.
DRY_STOP = 2
#: Page groups fixed at once; pages are different files.
PAGE_PARALLEL = 3
#: Steps a repair turn may take: the fix, the page or process, and the try.
STEPS = 12
#: How long to wait on a person's own Smith turn before fixing on the same tree.
TURN_WAIT_S = 600


def _say(emit: Callable | None) -> Callable[[str], None]:
    def say(text: str) -> None:
        if emit is not None:
            emit("message", {"text": text})
    return say


def run_checks_to_green(svc: Any, output_dir: str, app_root: str, report: Any, *,
                        emit: Callable[[str, dict], None] | None = None,
                        run_turn: Callable[..., dict] | None = None,
                        app_factory: Callable[[Path], Any] | None = None,
                        bench_factory: Callable[[str], Any] | None = None,
                        client: Any = None,
                        cancelled: Callable[[], bool] = lambda: False,
                        record: bool = True) -> dict:
    """Check everything once, write the card, fix the reds to green. Returns
    `{turns, yield, stopped, card}`."""
    from services.blueprint.page_repair import _ledger
    say = _say(emit)
    if run_turn is None:
        from services.smith4.platform import smith_result as run_turn

    def reload() -> None:
        from services.blueprint.service import BlueprintService
        try:
            svc.doc = BlueprintService.load(output_dir=output_dir).doc
        except Exception:  # noqa: BLE001
            logger.warning("[fix-to-green] could not reload the Blueprint", exc_info=True)

    def scorecard_event(phase: str) -> None:
        if emit is not None:
            emit("scorecard", {"summary": sc.summary(svc.doc), "phase": phase})

    turns, yields, stopped = 0, [], None
    ledger_ctx = _ledger(output_dir if record else None, 1, node="checks", phase="checking")
    with ledger_ctx as ledger:
        sc.set_status(svc, "checking")
        scorecard_event("checking")
        _check_everything(svc, output_dir, app_root, report, say=say, run_turn=run_turn,
                          app_factory=app_factory, bench_factory=bench_factory, client=client,
                          cancelled=cancelled, record=record)
        scorecard_event("checking")
        reds = sc.reds(svc.doc)
        if reds and not cancelled():
            sc.set_status(svc, "fixing")
            scorecard_event("fixing")
            say(f"{len(reds)} thing{'s' if len(reds) != 1 else ''} to fix. Working through them by cause; "
                "I'll say each one here as it turns green. The app stays usable meanwhile.")
        dry = 0
        while reds and turns < FIX_TURNS and dry < DRY_STOP:
            if cancelled():
                stopped = "stopped by the person"
                break
            _wait_for_the_person(output_dir, cancelled)
            groups = by_cause(reds)
            batch = _next_batch(groups)
            turns += 1
            before = {(r["criterion"], r["id"]): r for r in reds}
            ledger.node_subject("checks", f"turn {turns}", turns, FIX_TURNS, True)
            card_before = sc.read(svc.doc)
            _fix(batch, output_dir, run_turn=run_turn, say=say)
            reload()
            # THE CARD IS THE CHECKS' TO WRITE. A Smith turn loads the engine's
            # copy of the Blueprint, which still carries the hand-over card, and
            # its save put that card back over the one the checks had written
            # (12 reds became "21 of 21" mid-loop, 6132cfss, 2026-10-11).
            if card_before is not None:
                sc.restore(svc, card_before)
            _check_again(svc, output_dir, app_root, report, batch, run_turn=run_turn, app_factory=app_factory,
                         bench_factory=bench_factory, client=client, cancelled=cancelled, record=record)
            reds = sc.reds(svc.doc)
            after = {(r["criterion"], r["id"]) for r in reds}
            turned = [(key[0], before[key]) for key in sorted(set(before) - after)]
            yields.append(len(turned))
            dry = 0 if turned else dry + 1
            for criterion, it in turned:
                say(sc.green_line(criterion, it))
            scorecard_event("fixing")
        if reds and stopped is None and turns:
            stopped = "yield" if dry >= DRY_STOP else ("turns" if turns >= FIX_TURNS else None)
        _write_smith(svc, turns, yields, before_total=len(sc.reds(svc.doc)) + sum(yields))
        card = sc.set_status(svc, "stopped" if stopped == "stopped by the person" else "done",
                             fix={"turns": turns, "yield": yields, "stopped": stopped})
        scorecard_event("stopped" if stopped == "stopped by the person" else "done")
        if stopped == "stopped by the person":
            ledger_ctx.stopped = stopped
            say("Stopped checking. The app stays as it is: " + sc.closing(svc.doc))
        else:
            say(sc.closing(svc.doc))
    return {"turns": turns, "yield": yields, "stopped": stopped, "card": card}


# --------------------------------------------------------------------------- #
# The checks
# --------------------------------------------------------------------------- #

def _check_everything(svc: Any, output_dir: str, app_root: str, report: Any, *, say: Callable,
                      run_turn: Callable, app_factory: Any, bench_factory: Any, client: Any,
                      cancelled: Callable[[], bool], record: bool) -> None:
    """Every check once; each writes its criterion; a check that cannot run
    leaves its criterion untried and never stops the others."""
    pages_total = int(sc.read(svc.doc)["criteria"]["pages"]["total"]) if sc.read(svc.doc) else 0
    # PAGES: coded (the funnel) and working (opened as every role, controls pressed).
    try:
        from services.blueprint.page_repair import _repair_pages
        out = _repair_pages(svc, output_dir, app_root, report, run_turn=run_turn, rounds=0, record=False)
        missing = [sc.item(t["page"], t["name"], t["reason"], t["page"]) for t in out["left"]]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[fix-to-green] the page funnel failed", exc_info=True)
        missing, _ = [], exc
    # LOGIC: every process run through; every rule refusing its refused case.
    processes = {"passed": [], "fixed": [], "left": [], "untried": []}
    try:
        from services.blueprint.process_trials import _prove_processes
        kwargs = {"bench_factory": bench_factory} if bench_factory is not None else {}
        if client is not None:
            kwargs["client"] = client
        processes = _prove_processes(svc, output_dir, run_turn=run_turn, rounds=0, record=False,
                                     cancelled=cancelled, **kwargs)
    except Exception as exc:  # noqa: BLE001 — the check's own failure: said, never red
        logger.warning("[fix-to-green] the process trials failed", exc_info=True)
        from services.blueprint.process_trials import manual_workflows
        processes["untried"] = [{"workflow": str(w.get("id")), "name": str(w.get("name") or w.get("id")),
                                 "reason": f"the trial could not run: {type(exc).__name__}: {str(exc)[:160]}"}
                                for w in manual_workflows(svc.doc)]
    try:
        from services.blueprint.app_check import _check_app
        kwargs = {"app_factory": app_factory} if app_factory is not None else {}
        out = _check_app(svc, output_dir, run_turn=run_turn, rounds=0, record=record, cancelled=cancelled, **kwargs)
        broken = [sc.item(t["page"], t["name"], t["findings"][0] if t["findings"] else "does not work", t["page"])
                  for t in out["left"] if t["page"] not in {m["id"] for m in missing}]
        untried = [sc.item(t["page"], t["name"], t["reasons"][0] if t["reasons"] else "could not be opened", t["page"])
                   for t in out["untried"]]
        total = max(int(out.get("pages") or 0), pages_total)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[fix-to-green] the app check failed", exc_info=True)
        broken, untried, total = [], [sc.item("pages", sc.LABELS["pages"], f"the check failed: {exc}"[:200], "pages")], pages_total
    reds = missing + broken
    sc.write(svc, "pages", green=max(total - len(reds) - len(untried), 0), red=reds, untried=untried, total=total)
    say(f"Checked {total} page{'s' if total != 1 else ''}: {max(total - len(reds) - len(untried), 0)} work, "
        f"{len(reds)} don't" + (f", {len(untried)} I couldn't open" if untried else "") + ".")
    rules = _on_a_bench(svc, output_dir, bench_factory=bench_factory, client=client, cancelled=cancelled,
                        what=("routes", "access", "rules", "systems", "audit", "domain"))
    _write_logic(svc, processes, rules.get("rules"))
    say(_logic_line(svc))


def _on_a_bench(svc: Any, output_dir: str, *, bench_factory: Any, client: Any, cancelled: Callable[[], bool],
                what: tuple[str, ...], only_pages: set[str] | None = None, only_entities: set[str] | None = None,
                only_rules: set[str] | None = None, only_flows: set[str] | None = None) -> dict:
    """Routes, access, rules, the clock and the domain score on ONE running copy."""
    from services.smith import trials
    results: dict[str, dict] = {}
    factory = bench_factory or trials.Bench
    bench = factory(output_dir)
    # THE CHECK'S OWN SIGNING SECRETS, on the copy only: a webhook is proven
    # by signing a call with a value no real system holds.
    if "systems" in what and hasattr(bench, "extra_env"):
        try:
            from services.blueprint.webhook_check import signing_secrets
            bench.extra_env.update(signing_secrets(svc.doc))
        except Exception:  # noqa: BLE001
            logger.warning("[fix-to-green] no signing secrets for the bench", exc_info=True)
    try:
        try:
            app = bench.app()
        except trials.TrialUnavailable as exc:
            why = f"the app could not be started to check it: {exc}"
            for c in [c for c in what if c != "rules"]:
                sc.write(svc, c, green=0, red=[], untried=[sc.item(c, sc.LABELS[c], why[:300], c)])
            return {"rules": {"total": 0, "green": [], "red": [], "untried": [sc.item("rules", "Rules", why[:300], "rules")]}}
        if "routes" in what:
            try:
                from services.blueprint.route_check import check_routes
                out = check_routes(app, svc.doc, only=only_pages, cancelled=cancelled)
                _merge(svc, "routes", out, only_pages)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[fix-to-green] the route check failed", exc_info=True)
                sc.write(svc, "routes", green=0, red=[], untried=[sc.item("routes", sc.LABELS["routes"], f"the check failed: {exc}"[:200], "routes")])
        if "access" in what:
            try:
                from services.blueprint.access_check import check_access
                out = check_access(app, svc.doc, only=only_entities, cancelled=cancelled)
                _merge(svc, "access", out, only_entities)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[fix-to-green] the access check failed", exc_info=True)
                sc.write(svc, "access", green=0, red=[], untried=[sc.item("access", sc.LABELS["access"], f"the check failed: {exc}"[:200], "access")])
        if "rules" in what:
            try:
                from services.blueprint.rule_trials import refuse_rules
                if client is None:
                    from services.blueprint.executors import DEFAULT_MODEL, AnthropicModel
                    client = AnthropicModel(model=DEFAULT_MODEL, effort="low")
                results["rules"] = refuse_rules(svc.doc, bench, client, only=only_rules, cancelled=cancelled)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[fix-to-green] the rule trials failed", exc_info=True)
                results["rules"] = {"total": 0, "green": [], "red": [],
                                    "untried": [sc.item("rules", "Rules", f"the check failed: {exc}"[:200], "rules")]}
        if "systems" in what:
            try:
                from services.blueprint.clock_check import check_clock
                out = check_clock(app, svc.doc, bench=bench, app_root=str(Path(output_dir) / "app"), client=client,
                                  only=only_flows, cancelled=cancelled)
                from services.blueprint.webhook_check import check_webhooks
                hooks = check_webhooks(app, svc.doc, secrets=getattr(bench, "extra_env", None),
                                       only=only_flows, cancelled=cancelled)
                for k in ("green", "red", "untried"):
                    out[k] = list(out[k]) + list(hooks[k])
                out["total"] = int(out["total"]) + int(hooks["total"])
                _merge(svc, "systems", out, only_flows)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[fix-to-green] the clock check failed", exc_info=True)
                sc.write(svc, "systems", green=0, red=[], untried=[sc.item("systems", sc.LABELS["systems"], f"the check failed: {exc}"[:200], "systems")])
        if "audit" in what:
            try:
                from services.blueprint.audit_check import check_audit
                out = check_audit(app, svc.doc, cancelled=cancelled)
                sc.write(svc, "audit", green=out["green"], red=out["red"], untried=out["untried"], total=out["total"])
            except Exception as exc:  # noqa: BLE001
                logger.warning("[fix-to-green] the audit check failed", exc_info=True)
                sc.write(svc, "audit", green=0, red=[], untried=[sc.item("audit", sc.LABELS["audit"], f"the check failed: {exc}"[:200], "audit")])
        if "domain" in what:
            try:
                from services.blueprint.domain_score import score_domain
                out = score_domain(svc, output_dir, app=app, client=client)
                sc.write(svc, "domain", green=out["green"], red=out["red"], untried=out["untried"], total=out["total"])
            except Exception as exc:  # noqa: BLE001
                logger.warning("[fix-to-green] the domain score failed", exc_info=True)
                sc.write(svc, "domain", green=0, red=[], untried=[sc.item("domain", sc.LABELS["domain"], f"the check failed: {exc}"[:200], "domain")])
    finally:
        try:
            bench.close()
        except Exception:  # noqa: BLE001
            pass
    return results


def _merge(svc: Any, criterion: str, out: dict, only: set[str] | None) -> None:
    """Write a criterion; a check of some items keeps what the last check
    said of the rest."""
    green, red, untried = list(out["green"]), list(out["red"]), list(out["untried"])
    total = int(out["total"])
    if only is not None:
        prior = (sc.read(svc.doc) or {}).get("criteria", {}).get(criterion) or {}
        keep = lambda it: str(it.get("cause")) not in only  # noqa: E731
        red = [r for r in prior.get("red") or [] if keep(r)] + red
        untried = [u for u in prior.get("untried") or [] if keep(u) and "not checked" not in str(u.get("why"))] + untried
        total = int(prior.get("total") or 0) or total
        green_n = max(total - len(red) - len(untried), 0)
    else:
        green_n = len(green)
    sc.write(svc, criterion, green=green_n, red=red, untried=untried, total=total)


def _write_logic(svc: Any, processes: dict, rules: dict | None) -> None:
    green = len(processes.get("passed") or []) + len(processes.get("fixed") or [])
    red = [sc.item(t["workflow"], t["name"], t["reason"], t["workflow"]) for t in processes.get("left") or []]
    untried = [sc.item(t["workflow"], t["name"], t["reason"], t["workflow"]) for t in processes.get("untried") or []]
    if rules:
        green += len(rules.get("green") or [])
        red += list(rules.get("red") or [])
        untried += list(rules.get("untried") or [])
    sc.write(svc, "logic", green=green, red=red, untried=untried)


def _logic_line(svc: Any) -> str:
    v = (sc.read(svc.doc) or {}).get("criteria", {}).get("logic") or {}
    return (f"Ran the processes and tried the rules: {v.get('green', 0)} of {v.get('total', 0)} hold"
            + (f", {len(v.get('red') or [])} don't" if v.get("red") else "")
            + (f", {len(v.get('untried') or [])} I couldn't try" if v.get("untried") else "") + ".")


def _write_smith(svc: Any, turns: int, yields: list[int], *, before_total: int) -> None:
    left = sc.reds(svc.doc)
    fixed = sum(yields)
    red = [sc.item(r["id"], r["label"], r["why"], r["cause"]) for r in left] if turns else []
    sc.write(svc, "smith", green=fixed, red=red, untried=[], total=before_total if turns else 0)


# --------------------------------------------------------------------------- #
# The fix loop
# --------------------------------------------------------------------------- #

def by_cause(reds: list[dict]) -> list[dict]:
    """`{cause, kind, items}` — the reds a single repair turn is addressed to.
    A page's reds across criteria (does not open, wrong route answer, a
    control that fails) are one cause; a process or a rule is its own; a
    record type whose scope leaks is its own."""
    groups: dict[str, dict] = {}
    for r in reds:
        cause = str(r.get("cause") or r.get("id"))
        kind = ("process" if cause.startswith("FLOW-") else "rule" if cause.startswith("RULE-")
                else "access" if cause.startswith("ENTITY-") else "integration" if cause.startswith("INT-")
                else "audit" if cause == "audit" else "page")
        g = groups.setdefault(cause, {"cause": cause, "kind": kind, "items": []})
        g["items"].append(r)
    order = {"page": 0, "process": 1, "rule": 2, "access": 3, "integration": 4, "audit": 5}
    return sorted(groups.values(), key=lambda g: (order[g["kind"]], g["cause"]))


def _next_batch(groups: list[dict]) -> list[dict]:
    pages = [g for g in groups if g["kind"] == "page"]
    if pages:
        return pages[:PAGE_PARALLEL]
    return groups[:1]


def ask_for(group: dict, doc: dict) -> str:
    """What Smith is asked to do about one cause: the reds, each with how it
    was found, in the words the checks already use."""
    from services.blueprint.app_check import fault_ask as page_ask
    items = group["items"]
    if group["kind"] == "page":
        page = next((p for p in doc.get("pages") or [] if isinstance(p, dict) and str(p.get("id")) == group["cause"]), {})
        item = {"name": str(page.get("name") or items[0].get("label")), "route": str(page.get("route") or ""),
                "findings": [(str(r.get("criterion") or "check"), str(r.get("why") or "")) for r in items]}
        return page_ask(group["cause"], item)
    seen = "\n".join(f"- {r.get('label')}: {r.get('why')}" for r in items[:12])
    what = {"process": "process", "rule": "rule", "access": "record type", "integration": "outside system",
            "audit": "audit trail"}[group["kind"]]
    return (f"The build tried the {what} {items[0].get('label')} ({group['cause']}) as the people it is for. "
            f"This did not hold:\n{seen}\n\n"
            "Find the cause and fix it where it lives — the steps, a rule, the data model, who may do what, "
            "an ownership rule, or sample records — then run it again the same way: it is fixed only when it "
            "holds for them. Nobody is waiting to answer questions: decide from the definition and act.")


def _fix(batch: list[dict], output_dir: str, *, run_turn: Callable, say: Callable) -> None:
    def one(group: dict) -> None:
        from services.blueprint.service import BlueprintService
        try:
            doc = BlueprintService.load(output_dir=output_dir).doc
        except Exception:  # noqa: BLE001
            doc = {}
        label = str(group["items"][0].get("label") or group["cause"])
        say(f"{label} — {str(group['items'][0].get('why') or '')[:160]}. Fixing it.")
        try:
            run_turn("", output_dir, ask_for(group, doc), max_steps=STEPS, unattended=True)
        except Exception as exc:  # noqa: BLE001 — one repair never ends the loop
            logger.warning("[fix-to-green] %s: %s", group["cause"], exc)
    if len(batch) > 1 and all(g["kind"] == "page" for g in batch):
        with ThreadPoolExecutor(max_workers=min(PAGE_PARALLEL, len(batch)), thread_name_prefix="forge-fix") as pool:
            list(pool.map(one, batch))
    else:
        for g in batch:
            one(g)


def _check_again(svc: Any, output_dir: str, app_root: str, report: Any, batch: list[dict], *, run_turn: Callable,
                 app_factory: Any, bench_factory: Any, client: Any, cancelled: Callable[[], bool], record: bool) -> None:
    """Only the batch's causes are checked again."""
    pages = {g["cause"] for g in batch if g["kind"] == "page"}
    flows = {g["cause"] for g in batch if g["kind"] == "process"}
    rules = {g["cause"] for g in batch if g["kind"] == "rule"}
    entities = {g["cause"] for g in batch if g["kind"] == "access"}
    card = sc.read(svc.doc) or sc.empty(svc.doc)
    if pages:
        try:
            from services.blueprint.app_check import _check_app
            kwargs = {"app_factory": app_factory} if app_factory is not None else {}
            out = _check_app(svc, output_dir, run_turn=run_turn, rounds=0, record=record, only=pages,
                             cancelled=cancelled, **kwargs)
            prior = card["criteria"]["pages"]
            still = {t["page"] for t in out["left"]}
            tried_not = {t["page"] for t in out["untried"]}
            red = [r for r in prior["red"] if str(r.get("cause")) not in pages or str(r.get("cause")) in still]
            red += [sc.item(t["page"], t["name"], t["findings"][0] if t["findings"] else "does not work", t["page"])
                    for t in out["left"] if t["page"] not in {str(r.get("cause")) for r in red}]
            untried = [u for u in prior["untried"] if str(u.get("cause")) not in pages] + \
                      [sc.item(t["page"], t["name"], t["reasons"][0] if t["reasons"] else "could not be opened", t["page"])
                       for t in out["untried"] if t["page"] in tried_not]
            total = int(prior["total"])
            sc.write(svc, "pages", green=max(total - len(red) - len(untried), 0), red=red, untried=untried, total=total)
        except Exception:  # noqa: BLE001
            logger.warning("[fix-to-green] the page check again failed", exc_info=True)
    if flows:
        try:
            from services.blueprint.process_trials import _prove_processes
            kwargs = {"bench_factory": bench_factory} if bench_factory is not None else {}
            if client is not None:
                kwargs["client"] = client
            out = _prove_processes(svc, output_dir, run_turn=run_turn, rounds=0, record=False, only=flows,
                                   cancelled=cancelled, **kwargs)
            prior = (sc.read(svc.doc) or card)["criteria"]["logic"]
            red = [r for r in prior["red"] if str(r.get("cause")) not in flows]
            red += [sc.item(t["workflow"], t["name"], t["reason"], t["workflow"]) for t in out["left"]]
            untried = [u for u in prior["untried"] if str(u.get("cause")) not in flows]
            untried += [sc.item(t["workflow"], t["name"], t["reason"], t["workflow"]) for t in out["untried"]]
            total = int(prior["total"])
            sc.write(svc, "logic", green=max(total - len(red) - len(untried), 0), red=red, untried=untried, total=total)
        except Exception:  # noqa: BLE001
            logger.warning("[fix-to-green] the process check again failed", exc_info=True)
    if pages or rules or entities or flows:
        results = _on_a_bench(svc, output_dir, bench_factory=bench_factory, client=client, cancelled=cancelled,
                              what=tuple(c for c, on in (("routes", pages), ("access", entities), ("rules", rules),
                                                         ("systems", flows)) if on),
                              only_pages=pages or None, only_entities=entities or None, only_rules=rules or None,
                              only_flows=flows or None)
        if rules and results.get("rules"):
            prior = (sc.read(svc.doc) or card)["criteria"]["logic"]
            out = results["rules"]
            red = [r for r in prior["red"] if str(r.get("cause")) not in rules] + list(out["red"])
            untried = [u for u in prior["untried"] if str(u.get("cause")) not in rules] + list(out["untried"])
            total = int(prior["total"])
            sc.write(svc, "logic", green=max(total - len(red) - len(untried), 0), red=red, untried=untried, total=total)


def _wait_for_the_person(output_dir: str, cancelled: Callable[[], bool]) -> None:
    """A person's own Smith turn on this tree finishes first."""
    from services.run_registry import turn_in_flight
    waited = 0.0
    while turn_in_flight(output_dir) and waited < TURN_WAIT_S and not cancelled():
        time.sleep(5)
        waited += 5


__all__ = ["DRY_STOP", "FIX_TURNS", "PAGE_PARALLEL", "ask_for", "by_cause", "run_checks_to_green"]
