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

#: The build-phase nodes that LAND the application in the tree: the
#: layouts, the code, the projections, the build. Everything else — the
#: contracts, the processes and their steps, the rules, the analytics, the
#: flows, the statements — is authored once, for the whole application, in
#: the opening, the graph's way.
#:
#: LANDED ONCE, PROVEN FEATURE BY FEATURE. Each feature was landed and
#: proven in turn: a production build and a trial run per feature, seven
#: builds for seven features, and the shared sections authored seven times
#: (ecom v2: $15.76 and 85 minutes for three of seven features; the graph
#: built a whole e-commerce app for $11.62 in 35). Now every screen and
#: process is written and built in one pass, as the graph did, and the
#: features are the order of PROVING and fixing: each tried as the people it
#: is for, what fails handed to its authors and then to Smith, before the
#: next feature's statements are tried. One build, one tree; a fix that
#: changes code rebuilds once.
PER_FEATURE: tuple[str, ...] = ("page_layouts", "backend", "page_code", "frontend", "integration", "assemble")
#: What runs after the landing and the proofs: what the build remembers and
#: the check of the definition against itself.
LAST: tuple[str, ...] = ("memory", "verification")
#: Written AFTER the landing and before the proofs: the statements of what
#: must happen are tried against screens, so no screen waits on them. In
#: the opening they stood in front of every page: Ecom L1's 62 processes
#: made the statements writer the slowest definition call, it retried at
#: its output cap for twenty minutes, and nothing was laid out meanwhile
#: (2026-10-11). The old graph composed pages beside the workflows, and a
#: tester saw screens while the rest limped; the engineer does again.
AFTER_LANDING: tuple[str, ...] = ("expectations",)
#: A feature node that writes once for the whole application and is not
#: written again for the next feature: the section it writes, once present.
ONCE_WRITTEN: dict[str, str] = {"ui_direction": "composition"}
#: Steps an unattended fix turn may take: reproduce, find the cause, change
#: it, try it. What needs more than that is reported, not chased.
FIX_STEPS = 15
#: Fix turns a build gets at most, across the whole application — the
#: causes, not every statement. Four turns on one feature held four
#: statements in forty minutes (Ecom L1, 2026-10-11).
FIX_TURNS = 6
#: Turns in a row that fix nothing before the fixing stops: a cause the
#: engineer cannot reach is reported, not chased with the next one.
FIX_DRY_STOP = 2


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


class _SkipFailed:
    """`orchestrator.Scope` that leaves out the subjects a previous run
    failed on (labels `node:subject`)."""

    def __init__(self, failed: set[str]):
        self.failed = failed

    def subjects(self, node: str, doc: Mapping[str, Any], pending: list[str]) -> list[str]:
        return [s for s in pending if f"{node}:{s}" not in self.failed]

    def brief(self, node: str, subject: str) -> str:
        return ""

    def on(self, doc: Mapping[str, Any]) -> "_SkipFailed":
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
    last = [k for k in order if k not in per and (k in below or k in LAST)]
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
    return [k for lvl in levels() for k in lvl
            if k in asked and k not in per and k not in last and k not in AFTER_LANDING], scope


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


#: What the person hears when a build node starts. The chat said one line
#: per phase and nothing while a phase ran, and twenty-five minutes of
#: silence read as "every single process go stuck" (Ecom L1, 2026-10-11).
#: `{n}` is the node's fan-out: screens, processes, parts.
NODE_SAYS: dict[str, str] = {
    "page_details": "Detailing {n} screens.",
    "workflows": "Deciding the processes.",
    "workflow_steps": "Writing the steps of {n} processes.",
    "business_rules": "Writing the rules.",
    "analytics": "Deciding the figures and charts.",
    "app_flows": "Mapping how people move through the application.",
    "page_layouts": "Laying out {n} screens.",
    "backend": "Writing the data layer.",
    "page_code": "Writing the code of {n} screens.",
    "frontend": "Assembling the frontend.",
    "integration": "Wiring the connections.",
    "assemble": "Building the application — the production build.",
    "expectations": "Writing down what must happen, in {n} parts.",
    "memory": "Writing down what was decided.",
    "verification": "Checking the definition against itself.",
}


class _Narrated:
    """The run's progress observer, with a line to the chat as each node
    starts and as a fan-out finishes."""

    def __init__(self, observer: Any, say: Callable[[str, dict], None]) -> None:
        self._observer, self._say = observer, say

    def __call__(self, line: dict) -> Any:
        event, node = str(line.get("event") or ""), str(line.get("node") or "")
        if event == "node:start" and node in NODE_SAYS:
            self._say("message", {"text": NODE_SAYS[node].format(n=int(line.get("subjects") or 1))})
        elif event == "node:done" and node in ("page_code", "assemble", "workflow_steps", "expectations"):
            self._say("message", {"text": f"{NODE_SAYS[node].split(' —')[0].rstrip('.').format(n='the')}: done."})
        if self._observer is not None:
            return self._observer(line)
        return None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._observer, name)


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
    observer = _Narrated(observer, say)
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
                # ONCE MORE, WITH WHAT WENT WRONG IN HAND. A writer refused
                # twice for its output's shape (ecom v3's `decisions`,
                # forge-v3, 2026-10-10) had the refusal's words to go on; the
                # person was asked to press Build again instead. The failed
                # nodes run once more before anyone is asked anything.
                nodes = sorted({str(f).split(":", 1)[0] for f in failed})
                journal.write("first:again", nodes=nodes)
                say("message", {"text": ", ".join(nodes) + " did not finish — trying once more."})
                again = run(svc, executor, plan=nodes, commit=True, user_request=description, app_root=app_root,
                            observer=observer, observer_agent=observer_agent, scope=model_scope)
                reports.append(again)
                _reload(svc, output_dir)
                failed = _required_failures(again)
            if failed:
                because = {**(getattr(opening, "failed_because", None) or {}),
                           **(getattr(reports[-1], "failed_because", None) or {})}
                why = "; ".join(f"{f}: {str(because.get(f) or 'it failed')[:300]}" for f in failed)
                journal.write("first:failed", failed=failed, why=why)
                stopped = f"the application could not be defined: {why}"
                say("message", {"text": "I could not finish defining the application, so I have not built it — "
                                        + why[:700] + ". I will look into it; tell me if you know what is wrong."})
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

        # LAND ONCE: every screen's layout and code, the projections, the
        # build — one pass, one tree, as the graph did. A node that fails for
        # some subject goes to a fix turn and runs once more.
        if per:
            # THE PLATFORM'S OWN FILES, CURRENT BEFORE THE BUILD. The assembly
            # copies a default only where the app has none, so a rebuilt app
            # kept the engine, the live-refresh client and the SDK parts it
            # was first built with (Ecom L1, 2026-10-11). What Smith's turns
            # do first, the build does first.
            try:
                from services.smith.sync_app import refresh_engine
                moved = refresh_engine(app_root, svc.doc)
                if moved:
                    journal.write("platform:refreshed", files=moved[:20])
            except Exception as exc:  # noqa: BLE001 — a refresh that fails leaves the app as it was
                logger.warning("[engineer] platform refresh failed: %s", exc)
            journal.write("land:start", nodes=per)
            say("message", {"text": "Writing every screen and building the application."})
            landed = run(svc, executor, plan=per, commit=True, user_request=description,
                         app_root=app_root, observer=observer, observer_agent=observer_agent)
            reports.append(landed)
            _reload(svc, output_dir)
            if getattr(landed, "paused_because", ""):
                stopped = f"paused: {landed.paused_because}"
                journal.write("run:paused", feature="APP", why=landed.paused_because)
            else:
                whole_app = Feature(id="APP", name="the application")
                unfinished = _mend_failed_nodes(svc, output_dir, app_root, whole_app, landed, per, run, fix, budget,
                                                journal, say, executor=executor, description=description,
                                                observer=observer, observer_agent=observer_agent, scope=None)
                journal.write("land:done", failed=unfinished)

        # THE STATEMENTS, ONCE THE SCREENS ARE THERE: written now, tried
        # feature by feature below. A group the writer cannot finish leaves
        # its feature untried, not unbuilt (the node is optional).
        statements = [k for k in AFTER_LANDING if k in plan]
        if statements and not stopped:
            # A GROUP THAT FAILED LAST TIME IS NOT ASKED AGAIN THIS TIME. Four
            # process groups the writer could not finish were re-asked on
            # every build, eight minutes each time (Ecom L1, 2026-10-11); the
            # application is handed over without their statements, and the
            # next definition change asks again.
            last = journal.last("statements:done") or {}
            # ...and what the last run already gave up on stays given up: a
            # run that skipped them failed none, and the next asked again.
            gave_up = ({str(x) for x in last.get("failed") or []}
                       | {str(x) for x in (journal.last("statements:start") or {}).get("skipped") or []})
            journal.write("statements:start", nodes=statements, skipped=sorted(gave_up))
            say("message", {"text": "Writing down what must happen, to try the application against."})
            wrote = run(svc, executor, plan=statements, commit=True, user_request=description,
                        app_root=app_root, observer=observer, observer_agent=observer_agent,
                        scope=_SkipFailed(gave_up) if gave_up else None)
            reports.append(wrote)
            _reload(svc, output_dir)
            journal.write("statements:done", failed=list(getattr(wrote, "failed", None) or []))

        # PROVEN ALL AT ONCE, SAID PER FEATURE. Features proved one after
        # another were an hour each (Ecom L1: 66 minutes for the first of
        # nine, 2026-10-11). Every statement of every feature is tried in one
        # pass on the benches, the authors' look is given back once over the
        # whole, and the fix turns work the causes across the application —
        # capped, and stopped when they stop fixing anything.
        whole: dict = {}
        if not stopped:
            for feature in plan_features:
                if feature.id in earlier:
                    continue
                # NOT BUILT IS NOT DONE. A feature whose screens have no code
                # and no layout, or whose processes have no steps, is not
                # proven by trying statements about it: it is recorded as
                # unbuilt, and the build stops with it rather than hand over
                # what is not there.
                unbuilt = unbuilt_of(svc.doc, feature)
                if unbuilt:
                    row = {"feature": feature.id, "name": feature.name, "pages": feature.pages, "failed_nodes": [],
                           "unbuilt": unbuilt, "statements": 0, "passed": 0, "failing": [], "untried": [], "fixed": []}
                    results.append(row)
                    journal.write("feature:start", feature=feature.id, name=feature.name,
                                  pages=feature.pages, requirements=feature.requirements)
                    journal.write("feature:done", **row)
                    say("message", {"text": _said_feature(feature, row, unbuilt)})
                    stopped = f"{feature.label} is not built: " + "; ".join(unbuilt[:6])
                    break
        if not stopped:
            todo = [f for f in plan_features if f.id not in earlier]
            if budget.over():
                stopped = f"out of time after {budget.spent():.0f} minutes"
                journal.write("run:out_of_time", left=[f.id for f in todo])
            elif todo:
                for f in todo:
                    journal.write("feature:start", feature=f.id, name=f.name, pages=f.pages,
                                  requirements=f.requirements)
                    pulse.start(f)
                say("message", {"text": "Trying the whole application as the people it is for."})
                journal.write("prove:start", features=[f.id for f in todo])
                whole = _prove_all(svc, output_dir, plan_features, prove, fix, budget, journal, say)
                for f in todo:
                    row = _feature_row(f, whole, svc.doc)
                    results.append(row)
                    journal.write("feature:done", **row)
                    pulse.done(f)
                    say("message", {"text": _said_feature(f, row)})
                journal.write("whole:done", passed=whole.get("passed"), statements=whole.get("statements"),
                              failing=whole.get("failing"), untried=whole.get("untried"),
                              fixed=whole.get("fixed"), turns=whole.get("turns"))
        if not stopped and last:
            reports.append(run(svc, executor, plan=last, commit=True, user_request=description,
                               app_root=app_root, observer=observer, observer_agent=observer_agent))
            _reload(svc, output_dir)
        if not stopped:
            # THE APPLICATION, WHOLE: every screen written, every process
            # with steps, the people it is for, the statements that say what
            # must happen — before a single one is tried once more.
            missing = app_unbuilt(svc.doc)
            if missing and not budget.over():
                # WHAT IS MISSING IS THE ENGINEER'S TO FINISH, NOT THE PERSON'S.
                # "Build again to finish it" was said to a tester about a
                # process the build itself had left without steps (Ecommerce1,
                # forge-v3, 2026-10-10 05:50). A fix turn with the list, then
                # the sweep once more, and only what still cannot be finished
                # is reported.
                journal.write("whole:unbuilt", missing=missing)
                say("message", {"text": "The application is not whole yet: " + "; ".join(missing[:6])
                                        + ". Finishing it."})
                try:
                    answer = fix(output_dir, whole_ask(missing))
                except Exception as exc:  # noqa: BLE001 — one fix turn never ends the build
                    logger.warning("[engineer] whole-app mend failed: %s", exc)
                    answer = {"status": "failed", "answer": str(exc)}
                journal.write("whole:mend", status=(answer or {}).get("status"),
                              said=str((answer or {}).get("answer") or "")[:400])
                _reload(svc, output_dir)
                # What the fix wrote is landed and built once more.
                reports.append(run(svc, executor, plan=per, commit=True, user_request=description,
                                   app_root=app_root, observer=observer, observer_agent=observer_agent))
                _reload(svc, output_dir)
                missing = app_unbuilt(svc.doc)
            if missing:
                stopped = "the application is not whole: " + "; ".join(missing[:8])
                journal.write("whole:unfinished", missing=missing)
                say("message", {"text": "I could not finish the application, so I have not handed it over: "
                                        + "; ".join(missing[:8]) + ". Tell me what to change, or Build again and I will carry on from here."})
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


def whole_ask(missing: list[str]) -> str:
    """What the unattended turn is asked when the built application is not
    whole: what is missing, named; finish it where it lives."""
    lines = "\n".join(f"- {m}" for m in missing[:8])
    return (
        f"Every feature is built, and the application is not whole:\n{lines}\n\n"
        "Finish each where it lives — write the steps of a process that has none (`write_workflow_steps`), "
        "write the screen that has no code and no layout, declare the roles the screens need, write the "
        "statements of what must happen — then stop. Nobody is waiting to answer questions: decide from the "
        "definition and act. A fault in the platform itself is reported with `report_platform_fault`, "
        "not patched around."
    )


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


def untried_or_failing(doc: Mapping[str, Any], plan: list[Feature], results: list[dict]) -> list[str]:
    """The statements the end of the build tries: those a feature's proof
    left failing or untried, those no feature's proof covered at all, and
    the people's arrivals — where someone lands is what a later feature
    moves (Crumb's customer landed on /orders once Orders existed,
    2026-10-09). Not what held in its own feature: Crumb's pass tried all
    thirteen again, twelve of which had just held; ecom v2's would have
    tried 45."""
    from services.expects.statements import expectations
    rows_ = expectations(dict(doc))
    every = [str(e.get("id")) for e in rows_]
    arrivals = {str(e.get("id")) for e in rows_ if str(e.get("kind") or "") == "arrival"}
    covered: set[str] = set()
    for f in plan:
        covered |= set(statements_of(f, doc))
    again: list[str] = []
    for row in results:
        again += [str(x) for x in (row.get("failing") or []) + (row.get("untried") or [])]
    for sid in every:
        if (sid not in covered or sid in arrivals) and sid not in again:
            again.append(sid)
    seen: set[str] = set()
    return [s for s in again if s in set(every) and not (s in seen or seen.add(s))]


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


def _prove_all(svc: Any, output_dir: str, plan_features: list[Feature], prove: Callable[..., dict],
               fix: Callable[[str, str], dict], budget: Budget, journal: Journal,
               say: Callable[[str, dict], None]) -> dict:
    """Every statement of the application, tried once with the authors'
    look; then the causes of what still fails, each to one unattended fix
    turn and tried again — at most FIX_TURNS turns, and no more once
    FIX_DRY_STOP turns in a row have fixed nothing."""
    from services.blueprint.repair_groups import by_cause

    out = prove(svc, output_dir, only=None, give_back=True)
    merged: dict[str, dict] = {str(r.get("id")): r for r in out.get("results") or []}
    fixed: list[str] = list(out.get("fixed") or [])
    owner = {sid: f for f in plan_features for sid in statements_of(f, svc.doc)}
    failing = [r for r in merged.values() if r.get("verdict") == "failed"]
    turns = dry = 0
    for group in by_cause(failing, lambda r: (r.get("failures") or [""])[0]):
        if turns >= FIX_TURNS or dry >= FIX_DRY_STOP or budget.over():
            break
        feature = owner.get(str(group[0].get("id"))) or Feature(id="APP", name="the application")
        ids = [str(r.get("id")) for r in group]
        turns += 1
        journal.write("fix:start", feature=feature.id, turn=turns, statements=ids)
        say("message", {"text": f"{feature.label}: {len(group)} statement{'s' if len(group) != 1 else ''} "
                                f"not holding — finding the cause and fixing it (turn {turns} of {FIX_TURNS})."})
        try:
            answer = fix(output_dir, fix_ask(feature, group))
        except Exception as exc:  # noqa: BLE001 — one fix turn never ends the build
            logger.warning("[engineer] fix turn failed: %s", exc)
            answer = {"status": "failed", "answer": str(exc)}
        status = str((answer or {}).get("status") or "")
        journal.write("fix:end", feature=feature.id, turn=turns, status=status,
                      said=str((answer or {}).get("answer") or "")[:400])
        if status in ("no_op", "failed"):
            dry += 1
            continue
        _reload(svc, output_dir)
        again = prove(svc, output_dir, only=ids, give_back=False)
        held = [str(r.get("id")) for r in again.get("results") or [] if r.get("verdict") == "passed"]
        for r in again.get("results") or []:
            merged[str(r.get("id"))] = r
        fixed += [sid for sid in held if sid not in fixed]
        dry = 0 if held else dry + 1
        journal.write("fix:yield", turn=turns, held=held)
    if dry >= FIX_DRY_STOP:
        journal.write("fix:stopped", turns=turns, why=f"{FIX_DRY_STOP} turns in a row fixed nothing")
        say("message", {"text": "The fix turns stopped fixing anything, so what is left is reported rather than chased."})
    rows = list(merged.values())
    return {"statements": len(rows), "passed": sum(1 for r in rows if r.get("verdict") == "passed"),
            "failing": sorted(sid for sid, r in merged.items() if r.get("verdict") == "failed"),
            "untried": sorted(sid for sid, r in merged.items() if r.get("verdict") == "not_tried"),
            "fixed": fixed, "results": rows, "turns": turns}


def _feature_row(feature: Feature, whole: dict, doc: Mapping[str, Any]) -> dict:
    """One feature's share of the whole proof: its statements, what held,
    what failed, what the fix turns mended."""
    ids = set(statements_of(feature, doc))
    rows = [r for r in whole.get("results") or [] if str(r.get("id")) in ids]
    return {"feature": feature.id, "name": feature.name, "pages": feature.pages, "failed_nodes": [], "unbuilt": [],
            "statements": len(rows), "passed": sum(1 for r in rows if r.get("verdict") == "passed"),
            "failing": sorted(str(r.get("id")) for r in rows if r.get("verdict") == "failed"),
            "untried": sorted(str(r.get("id")) for r in rows if r.get("verdict") == "not_tried"),
            "fixed": [sid for sid in whole.get("fixed") or [] if sid in ids]}


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
    head = f"Building {app_name or 'the application'}, then trying it feature by feature"
    if earlier and not left:
        return (f"Every feature of {app_name or 'the application'} is already proven ({len(earlier)}); "
                f"trying what is left once more and finishing it.")
    if earlier:
        head += f" — {len(earlier)} already proven, picking up from there"
    return f"{head}: {names}. Each is tried as the people it is for, and fixed, before the next."


def _reload(svc: Any, output_dir: str) -> None:
    """The document as the disk holds it — under the service's lock, since
    the next feature's authoring may be applying to it on another thread."""
    from services.blueprint.service import BlueprintService
    import threading
    lock = getattr(svc, "lock", None)
    if not hasattr(lock, "__enter__"):
        lock = threading.Lock()
    try:
        fresh = BlueprintService.load(output_dir=output_dir).doc
        with lock:
            svc.doc = fresh
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
           "fix_ask", "PER_FEATURE", "FIX_TURNS", "FIX_DRY_STOP"]
