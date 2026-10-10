"""The engineer's build loop: feature by feature, each proven before the next.

For every feature (`features.features`): the authoring nodes run for its
part alone (`Scope`), the app is projected and built, the feature's
statements of what must happen are tried on the Workbench, what fails is
handed back to its author (the statements' own give-back) and then, if it
still fails, to an unattended engineer turn with the failures in hand —
bounded by rounds and by the run's time budget. Then the next feature. At
the end every statement is tried once more, and what the run proved is what
the caller says.

The nodes, the executors, the checks and the observer are the build's own;
what changes is the order of work and that nothing starts on a feature that
has not been proven.

THE GRAPH'S ORDER IS KEPT. The scheduler honours a node's dependencies
only inside one run's plan, and the engineer runs several plans: Ecommerce1
(forge-v3, 2026-10-10) ran `decisions`, `auth_pages` and `ui_direction`
before the entity fields, the page set and the roles existed, then skipped
those on its resume because a feature was already "done", and the flows
writer declared 33 pages nobody had contracted. So every run's plan is
closed upstream — what is still pending above the features runs first,
every time — and the feature nodes are the convex slice of the graph
between the first feature node and the last.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Mapping

from services.engineer.features import (Feature, app_unbuilt, brief_for, features, statements_of, subjects_of,
                                        unbuilt_of)
from services.engineer.journal import Budget, Journal


class _Pulse:
    """The engineer's own run ledger, alive for the whole build.

    A graph run heartbeats its ledger while it runs and stops when it ends;
    between the engineer's runs — trying the statements, a fix turn — nothing
    on disk said a build was in flight, and a deploy's cutover read Crumb's
    build as idle and restarted the backend under it (forge-v3, 2026-10-09
    21:29). One ledger spans the build: planned as its features, a feature
    per node, a pulse every twenty seconds, finished with the merged report."""

    #: The build's first node, before the features are known: everything
    #: pending above them (the model, the design, the decisions).
    OPENING = "opening"

    def __init__(self, output_dir: str):
        import threading
        import time as _time
        from services.blueprint.run_ledger import RunLedger
        self.ledger = RunLedger(output_dir, f"{_time.strftime('%Y%m%d-%H%M%S')}-engineer", phase="build")
        self.ledger.planned([self.OPENING])
        self.ledger.node_start(self.OPENING)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._beat, name="forge-engineer-pulse", daemon=True)
        self._thread.start()

    def plan(self, features: list[Feature]) -> None:
        """The features, once the opening run has settled what they are."""
        self.ledger.node_done(self.OPENING)
        self.ledger.planned([f"feature:{f.id}" for f in features])

    def _beat(self) -> None:
        while not self._stop.wait(20.0):
            try:
                self.ledger.heartbeat()
            except Exception:  # noqa: BLE001 — a pulse never breaks the build
                pass

    def start(self, feature: Feature) -> None:
        self.ledger.node_start(f"feature:{feature.id}")

    def done(self, feature: Feature) -> None:
        self.ledger.node_done(f"feature:{feature.id}")

    def end(self, report: Any = None, error: BaseException | None = None) -> None:
        self._stop.set()
        try:
            if error is not None:
                self.ledger.crashed(error)
            else:
                self.ledger.finish(report)
        except Exception:  # noqa: BLE001
            logger.warning("[engineer] could not close the build's ledger", exc_info=True)

logger = logging.getLogger(__name__)

#: The build-phase nodes that are one feature's at a time. The slice is
#: closed by `build_nodes`: a node between two of these (`auth_pages`,
#: `ui_direction`) is a feature node too, or the graph's order is broken.
PER_FEATURE: tuple[str, ...] = (
    "page_details", "content_fields", "workflows", "workflow_steps", "business_rules",
    "analytics", "app_flows", "apis", "expectations", "page_layouts", "backend",
    "page_code", "frontend", "integration", "assemble",
)
#: A feature node that writes once for the whole application and is not
#: written again for the next feature: the section it writes, once present.
ONCE_WRITTEN: dict[str, str] = {"ui_direction": "composition"}
#: How many unattended fix turns a feature's failing statements get.
FIX_ROUNDS = 2
#: Steps an unattended fix turn may take.
FIX_STEPS = 26
#: Fix turns per round at most — the causes, not every statement.
FIX_TURNS_PER_ROUND = 4


class FeatureScope:
    """`orchestrator.Scope` for one feature."""

    def __init__(self, feature: Feature, *, first: bool):
        self.feature, self.first = feature, first

    def subjects(self, node: str, doc: Mapping[str, Any], pending: list[str]) -> list[str]:
        written = ONCE_WRITTEN.get(node)
        if written and doc.get(written):
            return []
        return subjects_of(self.feature, node, doc, pending, first=self.first)

    def brief(self, node: str, subject: str) -> str:
        # A fan-out node's call is narrowed by its subject; a node that writes
        # once for the app is told which feature this call is for.
        return "" if subject else brief_for(self.feature, node, self._doc)

    _doc: Mapping[str, Any] = {}

    def on(self, doc: Mapping[str, Any]) -> "FeatureScope":
        self._doc = doc
        return self


def build_nodes() -> tuple[list[str], list[str], list[str]]:
    """``(once, per_feature, last)``: the build phase's nodes split by when
    the engineer runs them, each in the graph's own order. Read off the
    graph: a node that depends on a feature node and that a feature node
    depends on is a feature node; one that depends on a feature node and
    that none depends on runs last; the rest run once, before."""
    from services.blueprint.orchestrator import descendants, levels
    from services.smith.smith import domain_nodes, model_nodes
    earlier = set(domain_nodes()) | set(model_nodes())
    order = [k for lvl in levels() for k in lvl if k not in earlier]
    per_set = set(PER_FEATURE)
    below: set[str] = set()
    for k in PER_FEATURE:
        below |= descendants(k)
    per = [k for k in order if k in per_set or (k in below and descendants(k) & per_set)]
    last = [k for k in order if k not in per and k in below]
    once = [k for k in order if k not in per and k not in last]
    return once, per, last


def first_nodes(plan: list[str], doc: Mapping[str, Any] | None = None) -> tuple[list[str], Any]:
    """Of the nodes a build still has to run, the ones that come before its
    first feature — the domain, the model, and the build-phase nodes no
    feature node feeds — in the graph's order; and, when the declaration
    itself is why the model could not finish, the declarer put back in front
    with the brief that mends it. Run on every build, resumed or not: the
    model is finished before anything is built on it."""
    from services.blueprint.orchestrator import levels
    once, per, last = build_nodes()
    asked = set(plan)
    scope: Any = None
    accounts = [str(e.get("name")) for e in ((doc or {}).get("data") or {}).get("entities") or []
                if isinstance(e, dict) and e.get("account") and e.get("status") != "DEPRECATED"]
    if len(accounts) > 1 and {"entity_fields", "data_model"} & asked:
        asked.add("data_model")
        scope = _ModelScope(
            f"{' and '.join(accounts)} are each marked `account: true`, and exactly one entity is the person "
            f"behind a login. Keep it on the one people sign up as; make the other a record linked to it "
            f"(a `userId` reference to that entity) or a role of it. Keep every other entity as declared.")
    return [k for lvl in levels() for k in lvl if k in asked and k not in per and k not in last], scope


def incomplete_nodes(doc: Mapping[str, Any], output_dir: str) -> list[str]:
    """The graph's nodes not yet complete for this document, in order — what
    the build entry hands the engineer as its plan."""
    from services.blueprint.orchestrator import completed_nodes, levels, nodes_recorded_done
    already = completed_nodes(doc, confirmed=nodes_recorded_done(output_dir) or None)
    return [k for lvl in levels() for k in lvl if k not in already]


def fix_ask(feature: Feature, items: list[dict]) -> str:
    """What the unattended engineer turn is asked about statements that
    still do not hold after their authors had their look."""
    lines = "\n".join(f"- \"{r.get('says')}\" — {' | '.join(r.get('failures') or [])[:300]}"
                      for r in items[:6])
    return (
        f"While building {feature.label}, these statements of what must happen did not hold when "
        f"tried as the people they are about:\n{lines}\n\n"
        "Find the one cause and fix it where it lives — a process's steps, a screen's code or its "
        "wiring, a field or record the data model lacks, a rule, who may open or start it. Then try "
        "the statements again (`try_expectation`) and stop when they hold. Nobody is waiting to answer "
        "questions: decide from the definition and act. A fault in the platform itself is not yours to "
        "patch around: report it with `report_platform_fault` and leave the statement failing."
    )


def merged(reports: list[Any]) -> Any:
    """One run report over the engineer's several runs: what every run
    completed, failed, blocked, repaired or left unrepaired, and the last
    reason it paused — the shape the build's callers read."""
    from services.blueprint.orchestrator import RunReport
    out = RunReport()
    for r in reports:
        for name in ("completed", "skipped", "failed", "blocked", "artifacts", "repaired", "change_requests",
                     "corrections"):
            for x in getattr(r, name, None) or []:
                if x not in getattr(out, name):
                    getattr(out, name).append(x)
        for name in ("skipped_because", "failed_because", "blocked_because", "degraded", "observed", "unrepaired"):
            getattr(out, name).update(getattr(r, name, None) or {})
        if getattr(r, "paused_because", ""):
            out.paused_because = str(r.paused_because)
    # A node that failed in one feature and completed in another completed.
    out.failed = [f for f in out.failed if f not in out.completed]
    return out


def build(output_dir: str, app_root: str, *, emit: Callable[[str, dict], None] | None = None,
          description: str = "", budget_minutes: float = 0, app_name: str = "",
          executor: Any = None, observer_agent: Any = None, observer: Any = None,
          done_nodes: set[str] | None = None, svc: Any = None, plan: list[str] | None = None,
          run: Callable[..., Any] | None = None, prove: Callable[..., dict] | None = None,
          fix: Callable[[str, str], dict] | None = None) -> dict:
    """Build the approved definition at `output_dir` feature by feature.
    Returns what was done and proven: ``{features: [...], statements, state,
    stopped, report}``. `plan` is the graph's nodes still to run (the build
    entry's; computed here when a caller has none); `done_nodes` are the
    ones an earlier run completed. `run`, `prove` and `fix` are the
    orchestrator's `run`, the statements' `prove_expectations` and an
    unattended Smith turn unless a caller (a test) hands in its own.

    A build that stops — the model could not be finished, a feature's
    screens have no code, the application is not whole at the end — says so
    in `stopped`, and its report carries it as `paused_because`, so the
    entry neither hands the application over nor calls it built."""
    from services.blueprint.service import BlueprintService

    say = emit or (lambda _e, _d: None)
    # ONE DOCUMENT. The caller's service, when it has one: Crumb's build
    # entry kept its own copy of the definition while the engineer worked on
    # another, and the state-settling save at the end wrote the model-phase
    # document (v27) over the built one (v62) — no page code, no statements,
    # no policies in what the person was shown (forge-v3, 2026-10-09).
    svc = svc if svc is not None else BlueprintService.load(output_dir=output_dir)
    journal = Journal(output_dir)
    journal.acquire()
    pulse: _Pulse | None = None
    try:
        pulse = _Pulse(output_dir)
        run = run or _orchestrator_run
        prove = prove or _prove
        fix = fix or _fix
        if executor is None:
            executor, observer_agent = _executor(svc, output_dir, say, observer_agent)
        budget = Budget(budget_minutes)
        skip = set(done_nodes or ())
        if plan is None:
            plan = incomplete_nodes(svc.doc, output_dir)
        plan = [k for k in plan if k not in skip]
        once, per, last = build_nodes()
        last = [k for k in last if k in plan]
        reports: list[Any] = []

        # WHAT COMES BEFORE THE FIRST FEATURE RUNS FIRST, EVERY TIME: the
        # domain and model nodes still pending, the design, the decisions.
        # A build on an unfinished model built nothing (Ecommerce1, forge-v3,
        # 2026-10-10), and its resume skipped the model again because a
        # feature had been marked done.
        first, model_scope = first_nodes(plan, svc.doc)
        if first:
            journal.write("first:start", nodes=first)
            if model_scope is not None or any(k in first for k in _model_keys()):
                say("message", {"text": "Finishing the product model first: "
                                        + ", ".join(k for k in first if k in _model_keys()) + "."})
            opening = run(svc, executor, plan=first, commit=True, user_request=description, app_root=app_root,
                          observer=observer, observer_agent=observer_agent, scope=model_scope)
            reports.append(opening)
            _reload(svc, output_dir)
            failed = _required_failures(opening)
            if failed:
                because = getattr(opening, "failed_because", None) or {}
                why = "; ".join(f"{f}: {str(because.get(f) or 'it failed')[:300]}" for f in failed)
                journal.write("first:failed", failed=failed, why=why)
                stopped = f"the product model could not be finished: {why}"
                say("message", {"text": "I could not finish the product model, so I have not built on it — "
                                        + why[:700] + ". Tell me what to change, or Build again once it is mended."})
                out = _stopped(journal, svc, reports, stopped, features=[])
                pulse.end(out["report"])
                return out
            journal.write("first:done", nodes=first)

        plan_features = features(svc.doc)
        rows_before = journal.finished_rows()
        earlier = [f.id for f in plan_features if proven_before(f, rows_before, svc.doc)]
        journal.write("run:start", features=[f.id for f in plan_features], done_before=earlier,
                      budget_minutes=budget_minutes)
        say("message", {"text": _opening(plan_features, earlier, app_name)})
        results: list[dict] = []
        stopped = ""
        pulse.plan([f for f in plan_features if f.id not in earlier])

        for i, feature in enumerate(plan_features):
            if feature.id in earlier:
                continue
            if budget.over():
                stopped = f"out of time after {budget.spent():.0f} minutes"
                journal.write("run:out_of_time", left=[f.id for f in plan_features[i:]])
                break
            journal.write("feature:start", feature=feature.id, name=feature.name,
                          pages=feature.pages, requirements=feature.requirements)
            pulse.start(feature)
            say("message", {"text": f"Building {feature.label}: its screens, its processes, and the "
                                    f"checks that say what must happen on them."})
            scope = FeatureScope(feature, first=(i == 0)).on(svc.doc)
            report = run(svc, executor, plan=per, commit=True, user_request=description,
                         app_root=app_root, observer=observer, observer_agent=observer_agent,
                         scope=scope)
            reports.append(report)
            _reload(svc, output_dir)
            if getattr(report, "paused_because", ""):
                stopped = f"paused: {report.paused_because}"
                journal.write("run:paused", feature=feature.id, why=report.paused_because)
                break
            failed = _mend_failed_nodes(svc, output_dir, app_root, feature, report, per, run, fix, budget,
                                        journal, say, executor=executor, description=description,
                                        observer=observer, observer_agent=observer_agent, scope=scope)
            # NOT BUILT IS NOT DONE. A feature whose screens have no code and
            # no layout, or whose processes have no steps, is not proven by
            # trying statements about it: it is recorded as unbuilt, and the
            # build stops with it rather than hand over what is not there.
            unbuilt = unbuilt_of(svc.doc, feature)
            proof = (_prove_feature(svc, output_dir, feature, prove, fix, budget, journal, say)
                     if not unbuilt else {"statements": 0, "passed": 0, "failing": [], "untried": [], "fixed": []})
            row = {"feature": feature.id, "name": feature.name, "pages": feature.pages,
                   "failed_nodes": failed, "unbuilt": unbuilt, **proof}
            results.append(row)
            journal.write("feature:done", **row)
            pulse.done(feature)
            say("message", {"text": _said_feature(feature, proof, unbuilt)})
            if unbuilt:
                stopped = f"{feature.label} is not built: " + "; ".join(unbuilt[:6])
                break

        whole: dict = {}
        if not stopped and last:
            reports.append(run(svc, executor, plan=last, commit=True, user_request=description,
                               app_root=app_root, observer=observer, observer_agent=observer_agent))
            _reload(svc, output_dir)
        if not stopped:
            # THE APPLICATION, WHOLE: every screen written, every process
            # with steps, the people it is for, the statements that say what
            # must happen — before a single one is tried once more.
            missing = app_unbuilt(svc.doc)
            if missing:
                stopped = "the application is not whole: " + "; ".join(missing[:8])
                journal.write("whole:unbuilt", missing=missing)
                say("message", {"text": "I have not handed the application over, because it is not whole: "
                                        + "; ".join(missing[:8]) + ". Build again to finish it."})
        if not stopped:
            # EVERY STATEMENT ONCE MORE, AND WHAT A LATER FEATURE BROKE IS
            # FIXED: Crumb's customer landed on /orders once the Orders
            # feature existed, and the statement from the first feature failed
            # at the end with nobody sent to mend it (2026-10-09).
            whole_feature = Feature(id="APP", name="the whole application",
                                    pages=[str(p.get("id")) for p in plan_pages(svc.doc)],
                                    requirements=[str(r.get("id")) for r in svc.doc.get("requirements") or []
                                                  if isinstance(r, dict) and r.get("id")])
            whole = (_prove_feature(svc, output_dir, whole_feature, prove, fix, budget, journal, say, ids=None)
                     if statements_exist(svc.doc) else {})
            journal.write("whole:done", passed=whole.get("passed"), statements=whole.get("statements"),
                          failing=whole.get("failing"), untried=whole.get("untried"), fixed=whole.get("fixed"))
        out = _stopped(journal, svc, reports, stopped, features=results, statements=whole)
        pulse.end(out["report"])
        return out
    except BaseException as exc:
        if pulse is not None:
            pulse.end(error=exc)
        raise
    finally:
        journal.release()


def _stopped(journal: Journal, svc: Any, reports: list[Any], stopped: str, *, features: list[dict],
             statements: dict | None = None) -> dict:
    """The build's result, with its report carrying why it stopped — the
    entry reads `paused_because` and neither hands over nor announces."""
    report = merged(reports)
    if stopped and not getattr(report, "paused_because", ""):
        report.paused_because = stopped
    out = {"features": features, "statements": statements or {}, "stopped": stopped,
           "state": str(svc.doc.get("state") or ""), "report": report}
    journal.write("run:end", **{k: v for k, v in out.items() if k not in ("features", "report")})
    return out


def _model_keys() -> set[str]:
    from services.smith.smith import domain_nodes, model_nodes
    return set(domain_nodes()) | set(model_nodes())


def _required_failures(report: Any) -> list[str]:
    """The failures of the opening run that nothing can be built on: a
    required node's, by its label (`entity_fields:ENTITY-001` → `entity_fields`)."""
    from services.blueprint.orchestrator import DAG
    out: list[str] = []
    for label in getattr(report, "failed", None) or []:
        key = str(label).split(":", 1)[0]
        if key in DAG and DAG[key].optional:
            continue
        out.append(str(label))
    return out


def proven_before(feature: Feature, rows: list[dict], doc: Mapping[str, Any]) -> bool:
    """Whether an earlier run built and proved this very feature: a
    `feature:done` row of the same id over the same screens, nothing of it
    unbuilt then, and nothing of it unbuilt now. Ecommerce1's resume took
    "MODULE-ALL, pages: []" as a proven feature and picked up from there
    (forge-v3, 2026-10-10)."""
    for r in rows:
        if str(r.get("feature")) != feature.id:
            continue
        if sorted(str(p) for p in r.get("pages") or []) != sorted(feature.pages):
            continue
        if r.get("unbuilt"):
            continue
        if not feature.pages and not r.get("statements"):
            continue
        if unbuilt_of(doc, feature):
            continue
        return True
    return False


def node_failure_ask(feature: Feature, failures: dict[str, str]) -> str:
    """What the unattended turn is asked when a build node failed for a
    feature — Crumb's assemble refused /baker/items: "needs a workflow that
    does not exist yet: unmark an item as sold out" (2026-10-09)."""
    lines = "\n".join(f"- {node}: {why[:400]}" for node, why in failures.items())
    return (
        f"While building {feature.label}, the build could not finish:\n{lines}\n\n"
        "Fix the cause where it lives — declare the process a screen needs and write its steps, "
        "mend the screen so it uses what exists, add the field or record the data model lacks — then "
        "write the screen again if it was the screen. Nobody is waiting to answer questions: decide "
        "from the definition and act. A fault in the platform itself is reported with "
        "`report_platform_fault`, not patched around."
    )


def _mend_failed_nodes(svc: Any, output_dir: str, app_root: str, feature: Feature, report: Any, per: list[str],
                       run: Callable[..., Any], fix: Callable[[str, str], dict], budget: Budget,
                       journal: Journal, say: Callable[[str, dict], None], **run_kw: Any) -> list[str]:
    """A node that failed for this feature goes to a fix turn with its
    reason, and the failed nodes run once more. Returns what still failed."""
    failed = [f for f in (getattr(report, "failed", None) or [])]
    if not failed or budget.over():
        return failed
    because = getattr(report, "failed_because", None) or {}
    nodes = sorted({str(f).split(":", 1)[0] for f in failed})
    reasons = {n: "; ".join(str(because.get(f) or "") for f in failed if str(f).split(":", 1)[0] == n)
               or "it failed" for n in nodes}
    journal.write("mend:start", feature=feature.id, nodes=nodes, reasons=reasons)
    say("message", {"text": f"{feature.label}: {', '.join(nodes)} did not finish — finding the cause and "
                            f"fixing it before trying the feature."})
    try:
        answer = fix(output_dir, node_failure_ask(feature, reasons))
    except Exception as exc:  # noqa: BLE001 — one fix turn never ends the build
        logger.warning("[engineer] mend turn failed: %s", exc)
        answer = {"status": "failed", "answer": str(exc)}
    journal.write("mend:end", feature=feature.id, status=(answer or {}).get("status"),
                  said=str((answer or {}).get("answer") or "")[:400])
    _reload(svc, output_dir)
    again = run(svc, run_kw.get("executor"), plan=[k for k in per if k in nodes or k in ("assemble",)],
                commit=True, user_request=run_kw.get("description", ""), app_root=app_root,
                observer=run_kw.get("observer"), observer_agent=run_kw.get("observer_agent"),
                scope=run_kw.get("scope"))
    _reload(svc, output_dir)
    still = list(getattr(again, "failed", None) or [])
    journal.write("mend:done", feature=feature.id, still=still)
    return still


def statements_exist(doc: Mapping[str, Any]) -> bool:
    from services.expects.statements import expectations
    return bool(expectations(dict(doc)))


class _ModelScope:
    """What the declarer is told when its declaration is why the model could
    not finish: Ecommerce1's `data_model` marked Customer and Vendor both
    `account: true`, and the field authors were refused for it (2026-10-10)."""

    def __init__(self, brief: str):
        self._brief = brief

    def subjects(self, node: str, doc: Mapping[str, Any], pending: list[str]) -> list[str]:
        return pending

    def brief(self, node: str, subject: str) -> str:
        return self._brief if node == "data_model" else ""


def plan_pages(doc: Mapping[str, Any]) -> list[dict]:
    return [p for p in doc.get("pages") or [] if isinstance(p, dict) and p.get("id")
            and p.get("status") != "DEPRECATED"]


def _prove_feature(svc: Any, output_dir: str, feature: Feature, prove: Callable[..., dict],
                   fix: Callable[[str, str], dict], budget: Budget, journal: Journal,
                   say: Callable[[str, dict], None], ids: list[str] | None = ...) -> dict:
    """The feature's statements, tried; what fails handed to its authors by
    the statements' own give-back, then to the engineer's fix turns. `ids`
    None means every statement (the whole-app pass)."""
    from services.blueprint.repair_groups import by_cause
    from services.expects.statements import expectations

    if ids is ...:
        ids = statements_of(feature, svc.doc)
    if ids is None:
        ids = [str(e.get("id")) for e in expectations(dict(svc.doc))]
    if not ids:
        return {"statements": 0, "passed": 0, "failing": [], "untried": [], "fixed": []}
    out = prove(svc, output_dir, only=ids, give_back=True)
    fixed: list[str] = list(out.get("fixed") or [])
    for round_ in range(1, FIX_ROUNDS + 1):
        failing = [r for r in out.get("results") or [] if r.get("verdict") == "failed"
                   and str(r.get("id")) in set(out.get("failing") or [])]
        if not failing or budget.over():
            break
        groups = by_cause(failing, lambda r: (r.get("failures") or [""])[0])[:FIX_TURNS_PER_ROUND]
        for group in groups:
            journal.write("fix:start", feature=feature.id, round=round_,
                          statements=[str(r.get("id")) for r in group])
            say("message", {"text": f"{feature.label}: {len(group)} statement{'s' if len(group) != 1 else ''} "
                                    f"not holding — finding the cause and fixing it."})
            try:
                answer = fix(output_dir, fix_ask(feature, group))
            except Exception as exc:  # noqa: BLE001 — one fix turn never ends the build
                logger.warning("[engineer] fix turn failed: %s", exc)
                answer = {"status": "failed", "answer": str(exc)}
            journal.write("fix:end", feature=feature.id, round=round_,
                          status=(answer or {}).get("status"), said=str((answer or {}).get("answer") or "")[:400])
            _reload(svc, output_dir)
        again = prove(svc, output_dir, only=[str(r.get("id")) for r in failing], give_back=False)
        now_passing = [str(r.get("id")) for r in again.get("results") or [] if r.get("verdict") == "passed"]
        fixed += [s for s in now_passing if s not in fixed]
        merged = {str(r.get("id")): r for r in out.get("results") or []}
        merged.update({str(r.get("id")): r for r in again.get("results") or []})
        out = {**out, "results": list(merged.values()),
               "failing": sorted(s for s, r in merged.items() if r.get("verdict") == "failed"),
               "untried": sorted(s for s, r in merged.items() if r.get("verdict") == "not_tried"),
               "passed": sum(1 for r in merged.values() if r.get("verdict") == "passed")}
    return {"statements": len(ids), "passed": int(out.get("passed") or 0),
            "failing": list(out.get("failing") or []), "untried": list(out.get("untried") or []),
            "fixed": fixed}


def _said_feature(feature: Feature, proof: dict, unbuilt: list[str] | None = None) -> str:
    if unbuilt:
        return f"{feature.label} is not built: " + "; ".join(unbuilt[:6]) + "."
    n, held = proof.get("statements", 0), proof.get("passed", 0)
    if not n:
        return f"{feature.label} is built; it has no statements of its own to try."
    untried = len(proof.get("untried") or [])
    tried = n - untried
    said = f"{feature.label}: {held} of {tried} statement{'s' if tried != 1 else ''} of what must happen hold"
    if untried:
        said += f" ({untried} could not be tried)"
    if proof.get("fixed"):
        said += f"; fixed while building: {', '.join(proof['fixed'][:6])}"
    return said + "."


def _opening(plan: list[Feature], earlier: list[str], app_name: str) -> str:
    left = [f for f in plan if f.id not in earlier]
    names = ", ".join(f.label for f in left)
    head = f"Building {app_name or 'the application'} feature by feature"
    if earlier and not left:
        return (f"Every feature of {app_name or 'the application'} is already proven ({len(earlier)}); "
                f"trying the whole application once more and finishing it.")
    if earlier:
        head += f" — {len(earlier)} already proven, picking up from there"
    return f"{head}: {names}. Each is tried as the people it is for before the next begins."


def _reload(svc: Any, output_dir: str) -> None:
    from services.blueprint.service import BlueprintService
    try:
        svc.doc = BlueprintService.load(output_dir=output_dir).doc
    except Exception:  # noqa: BLE001
        logger.warning("[engineer] could not reload the definition", exc_info=True)


def _orchestrator_run(*args: Any, **kwargs: Any) -> Any:
    from services.blueprint.orchestrator import run
    return run(*args, **kwargs)


def _prove(svc: Any, output_dir: str, **kwargs: Any) -> dict:
    from services.expects.build import prove_expectations
    return prove_expectations(svc, output_dir, **kwargs)


def _fix(output_dir: str, ask: str) -> dict:
    from services.smith4.platform import smith_result
    return smith_result("", output_dir, ask, max_steps=FIX_STEPS, unattended=True)


def _executor(svc: Any, output_dir: str, say: Callable[[str, dict], None], observer_agent: Any) -> tuple[Any, Any]:
    from services.blueprint.executors import RunUsage, make_executor, tiered_router
    from services.blueprint.observer import anthropic_observer
    usage = RunUsage.for_app(svc)
    router = tiered_router()
    executor = make_executor(svc, router, usage=usage)
    if observer_agent is None:
        observer_agent = anthropic_observer(router, usage=usage, output_dir=output_dir, emit=say)
    return executor, observer_agent


__all__ = ["build", "build_nodes", "first_nodes", "incomplete_nodes", "proven_before", "FeatureScope",
           "fix_ask", "PER_FEATURE", "FIX_ROUNDS"]
