"""The statements, tried where the application changes: at the end of a build
and after each change Smith makes.

At the end of a build every statement is tried (`runner`). Nothing is ground
through repair turns. A failure is sorted by what it shows:

  * the same failure across several statements is the PLATFORM's — a fault
    in the runtime or the generator every app would share — said, not
    repaired in this app;
  * a process the statement ran that refused or failed, or ran and did not
    keep what it should, is that PROCESS's author's (`workflow_steps`);
  * a screen that would not do what was asked, or showed the wrong thing, is
    that SCREEN's author's (`recode_page`, as edits);
  * anything else (where someone lands, who is let in) is said.

Each author is given its findings once; the statements it was given are then
tried once more. What still fails is recorded (`runtime.expectations`) and
said in the completion message. After a change in chat, the statements the
change reaches are tried and what no longer holds is said.

The statement is never what gets fixed: changing what must happen is a
change to the requirements, said to the person.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Callable

from services.expects.statements import expectations

logger = logging.getLogger(__name__)

#: The same failure in this many statements is the platform's, not the app's.
PLATFORM_SPREAD = 3
#: Authors given their findings in one build: a build with more failing
#: parts than this has a cause bigger than any one of them.
MAX_REPAIRS = 6
#: Statements one change is tried against; the rest wait for the next build.
MAX_CHANGE_STATEMENTS = 12
_FLOW_CALL = re.compile(r"/api/workflows/(FLOW-\d+)/execute")


def _people(doc: dict, st: dict) -> str:
    roles = {str(r.get("id")): str(r.get("name")) for r in doc.get("roles") or [] if isinstance(r, dict)}
    who = []
    for s in st.get("steps") or []:
        name = "a guest" if s.get("as") == "guest" else roles.get(str(s.get("as")), str(s.get("as")))
        if name not in who:
            who.append(name)
    return ", ".join(who) or "its people"


def observation(res: dict) -> str:
    """One statement's result as Smith reads it — the verdict on the first
    line (`trials.failed` reads it there), then what was seen."""
    head = {"passed": "holds", "failed": "does not hold", "not_tried": "could not be tried"}.get(
        str(res.get("verdict")), str(res.get("verdict")))
    out = [f"{res.get('id')} {head} — \"{res.get('says')}\""]
    out += [f"  - {f}" for f in res.get("failures") or []]
    if res.get("untried"):
        out.append("Not tried:")
        out += [f"  - {f}" for f in res["untried"]]
    if res.get("log"):
        out.append("What happened:")
        out += [f"  {line}" for line in res["log"][:30]]
    if res.get("also"):
        out.append("Also seen on the way:")
        out += [f"  {line}" for line in res["also"][:8]]
    return "\n".join(out)


def _left_out(doc: dict | None, flow: str, sent: list[dict]) -> list[str]:
    """The required inputs of `flow` the screen did not send, from the
    request bodies the statement recorded; [] when unknown."""
    if not doc:
        return []
    wf = next((w for w in doc.get("workflows") or [] if isinstance(w, dict) and str(w.get("id")) == flow), None)
    required = [str(i.get("name")) for i in (wf or {}).get("inputs") or []
                if isinstance(i, dict) and i.get("name") and i.get("required")]
    for c in sent:
        if f"/{flow}/" not in str(c.get("path")) or not c.get("request"):
            continue
        try:
            body = json.loads(c["request"])
        except ValueError:
            continue
        given = body.get("input") if isinstance(body, dict) and isinstance(body.get("input"), dict) else body
        if isinstance(given, dict):
            return [r for r in required if given.get(r) in (None, "")]
    return []


def owner_of(res: dict, doc: dict | None = None) -> tuple[str, str] | None:
    """Whose part a failed statement shows to be wrong, from what it sent:
    `("workflow_steps", FLOW-…)` for a process that refused, failed, or ran
    and did not keep what it should; `("page_code", PAGE-…)` for a screen
    that did nothing or showed the wrong thing; None when it is neither."""
    sent = [c for c in res.get("sent") or [] if isinstance(c, dict)]
    flows = [(m.group(1), int(c.get("status") or 0)) for c in sent
             if (m := _FLOW_CALL.search(str(c.get("path") or "")))]
    failed = [f for f, status in flows if status >= 400 and '"refused":true' not in str(
        next((c.get("body") for c in sent if f in str(c.get("path"))), "")).replace(" ", "")]
    if failed:
        return ("workflow_steps", failed[-1])
    text = " ".join(res.get("failures") or [])
    if flows and re.search(r"is stored|is not stored|^no .* is stored| stored$", text, re.M):
        # RAN AND KEPT NOTHING: the screen left out what the process needs
        # (its fault), or the process had all it needs (the process's).
        if res.get("where") and _left_out(doc, flows[-1][0], sent):
            return ("page_code", str(res["where"]))
        return ("workflow_steps", flows[-1][0])
    if res.get("where") and re.search(r"could not |was told nothing|nothing was sent|does not see|sees ", text):
        return ("page_code", str(res["where"]))
    return None


def author_brief(doc: dict, items: list[tuple[dict, dict]], node: str = "", subject: str = "") -> str:
    """What one author is told: each statement of its part that does not
    hold, with what the screen sent and what came back."""
    parts = []
    for _st, res in items:
        text = observation(res)
        sent = [c for c in res.get("sent") or [] if c.get("request") or c.get("body")]
        if sent:
            text += "\nWhat the screen sent, and what came back:\n" + "\n".join(
                f"  {c.get('method')} {c.get('path')} {c.get('status')}\n    sent: {str(c.get('request'))[:400]}"
                f"\n    back: {str(c.get('body'))[:300]}" for c in sent[:4])
        if node == "page_code" and subject:
            missing = sorted({m for c in res.get("sent") or [] if (f := _FLOW_CALL.search(str(c.get("path"))))
                              for m in _left_out(doc, f.group(1), [c])})
            if missing:
                text += f"\nThe screen did not send what the process needs: {', '.join(missing)}."
        parts.append(text)
    return ("These statements of what must happen were tried in the running application and do not "
            "hold. Change your part so that they do; do not change what they say.\n\n" + "\n\n".join(parts))


def _results_file(output_dir: str) -> Path:
    return Path(output_dir) / ".forge" / "expects" / "results.json"


def last_results(output_dir: str) -> dict[str, dict]:
    """Each statement's last result, by id."""
    try:
        rows = json.loads(_results_file(output_dir).read_text()).get("results") or []
    except (OSError, ValueError):
        return {}
    return {str(r.get("id")): r for r in rows if isinstance(r, dict)}


def prove_expectations(svc: Any, output_dir: str, *args: Any, **kwargs: Any) -> dict:
    """See `_prove`; its model calls are the build's spend."""
    from services.build_usage import usage_scope
    with usage_scope(agent="expectations", output_dir=str(output_dir), phase="build", kind="build"):
        return _prove(svc, output_dir, *args, **kwargs)


def _prove(svc: Any, output_dir: str, *, emit: Callable[[str, dict], None] | None = None,
           app_factory: Callable[[Path], Any] | None = None,
           trial: Callable[..., dict] | None = None,
           author: Callable[[Any, str, str, str, str], list[str]] | None = None,
           only: list[str] | None = None, record: bool = True, give_back: bool = True) -> dict:
    """Try every statement (or `only` those); give each failing part's author
    its findings once and try those statements again. Returns `{statements,
    passed, fixed, failing, untried, platform, touched, results}`."""
    from services.blueprint.repair_groups import by_cause
    from services.expects import runner

    say = emit or (lambda _e, _d: None)
    if app_factory is None:
        from services.blueprint.page_review import RunningApp

        def app_factory(root: Path) -> Any:
            return RunningApp(root, log=Path(output_dir) / ".forge" / "expects" / "server.log")
    trial = trial or runner.run
    author = author or _author

    def tried_once(ids: list[str]) -> list[dict]:
        app = app_factory(Path(output_dir) / "app")
        try:
            running = app.__enter__()
            return list(trial(running, svc.doc, Path(output_dir), only=ids).get("results") or [])
        finally:
            try:
                app.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass

    faults: list = []

    def tried(ids: list[str]) -> list[dict]:
        # A RUN THAT COULD NOT HAPPEN IS TRIED ONCE MORE, fresh. E-commerce's
        # browser hung opening the app on a loaded host ("did not answer goto
        # within 120s") and all 46 statements went untried (forge-v3,
        # 2026-10-09): a new app and a new browser, once, before that is said.
        # THE PLATFORM'S OWN FAULT IS SAID AS SUCH. The Workbench could not
        # get the app installed, seeded or signed in to: not the app's
        # failure, not the check's — the platform's, recorded once for every
        # statement it kept from being tried, and not tried again now.
        from services import workbench
        last_exc: Exception | None = None
        for attempt in (1, 2):
            try:
                return tried_once(ids)
            except Exception as exc:  # noqa: BLE001 — a run that cannot happen is said, not fatal
                last_exc = exc
                fault = workbench.fault_of(exc)
                if fault is not None:
                    logger.warning("[expects] platform fault: %s", fault)
                    faults.append(fault)
                    return [{"id": sid, "verdict": "not_tried", "untried": [str(fault)]} for sid in ids]
                logger.warning("[expects] the app could not be run (attempt %d): %s", attempt, exc)
        return [{"id": sid, "verdict": "not_tried", "untried": [f"the app could not be started: {last_exc}"]}
                for sid in ids]

    rows = [st for st in expectations(svc.doc) if not only or str(st.get("id")) in only]
    if not rows:
        return {"statements": 0, "passed": 0, "fixed": [], "failing": [], "untried": [], "platform": [],
                "touched": [], "results": []}
    if only is None:
        say("message", {"text": f"Trying the {len(rows)} statements of what must happen, each as the "
                                f"people it is about, in the running app."})
    last = {str(r.get("id")): r for r in tried([str(st.get("id")) for st in rows])}
    by_id = {str(st.get("id")): st for st in rows}
    failing = [r for r in last.values() if r.get("verdict") == "failed"]

    # THE PLATFORM'S: one failure across several statements.
    platform: list[dict] = []
    own: list[dict] = []
    for group in by_cause(failing, lambda r: (r.get("failures") or [""])[0]):
        if len(group) >= PLATFORM_SPREAD:
            platform.append({"statements": [str(r.get("id")) for r in group],
                             "failure": (group[0].get("failures") or [""])[0][:300]})
        else:
            own += group
    for fault in faults[:1]:
        platform.append({"statements": [sid for sid, r in last.items() if str(fault) in (r.get("untried") or [])],
                         "failure": str(fault)[:300], "precondition": fault.precondition})

    # EACH AUTHOR ONCE, with every finding of its part.
    def parts_of(results: list[dict]) -> dict[tuple[str, str], list[tuple[dict, dict]]]:
        out: dict[tuple[str, str], list[tuple[dict, dict]]] = {}
        for res in results:
            who = owner_of(res, svc.doc)
            if who is not None and str(res.get("id")) in by_id:
                out.setdefault(who, []).append((by_id[str(res["id"])], res))
        return out

    touched: list[str] = []
    fixed: list[str] = []
    parts = dict(list(parts_of(own).items())[:MAX_REPAIRS])
    # EACH AUTHOR GETS TWO LOOKS: its findings, then — if its statements still
    # do not hold — what they showed after its change.
    for attempt in (1, 2) if give_back else ():
        if not parts:
            break
        sent_back: list[str] = []
        for (node, subject), items in parts.items():
            names = "; ".join(f"\"{st.get('says')}\"" for st, _r in items[:3])
            say("message", {"text": f"Not holding yet: {names}. Sending it back to whoever wrote "
                                    f"{'that process' if node == 'workflow_steps' else 'that screen'}"
                                    + (" again, with what it showed after the change." if attempt == 2 else ".")})
            try:
                touched += [t for t in author(svc, output_dir, node, subject,
                                              author_brief(svc.doc, items, node, subject)) if t not in touched]
                sent_back += [str(r.get("id")) for _st, r in items]
            except Exception as exc:  # noqa: BLE001 — one author never ends the build
                logger.warning("[expects] %s %s: %s", node, subject, exc)
            _reload(svc, output_dir)
        still: list[dict] = []
        for res in tried(sent_back) if sent_back else []:
            sid = str(res.get("id"))
            if res.get("verdict") == "passed":
                fixed.append(sid)
            elif res.get("verdict") == "failed":
                still.append(res)
            last[sid] = res
        # The second look goes to whoever the new evidence names — a process
        # given what it needs may now point at the screen, or the other way.
        parts = {k: v for k, v in parts_of(still).items()}

    summary = {"statements": len(rows),
               "passed": sum(1 for r in last.values() if r.get("verdict") == "passed"),
               "fixed": sorted(fixed),
               "failing": sorted(sid for sid, r in last.items() if r.get("verdict") == "failed"),
               "untried": sorted(sid for sid, r in last.items() if r.get("verdict") == "not_tried"),
               "platform": platform, "touched": touched, "results": list(last.values())}
    if record:
        _record(svc, summary, partial=only is not None)
    return summary


def _reload(svc: Any, output_dir: str) -> None:
    from services.blueprint.service import BlueprintService
    try:
        svc.doc = BlueprintService.load(output_dir=output_dir).doc
    except Exception:  # noqa: BLE001
        logger.warning("[expects] could not reload the Blueprint", exc_info=True)


def _author(svc: Any, output_dir: str, node: str, subject: str, brief: str) -> list[str]:
    """Give one part's author its findings: a process's steps re-decided by
    the workflow author and written into the app; a screen's code changed by
    its writer, as edits. Returns the files that changed."""
    app_root = str(Path(output_dir) / "app")
    if node == "page_code":
        from services.smith.compose import recode_page
        route = next((str(p.get("route")) for p in svc.doc.get("pages") or []
                      if isinstance(p, dict) and str(p.get("id")) == subject), "")
        if not route:
            return []
        out = recode_page(svc, route, app_root=app_root, request=brief)
        return [f"page {route}"] if out.get("applied") else []
    if node == "workflow_steps":
        from services.smith.section_change import rerun
        from services.smith.sync_app import sync
        rerun(svc, "workflow_steps", brief=brief, request=f"make {subject} do what its statements say",
              interpretation=f"re-decide {subject} from what was tried", subject=subject, app_root=app_root)
        return list((sync(svc, app_root) or {}).get("changed") or [])
    return []


def _record(svc: Any, summary: dict, *, partial: bool) -> None:
    """`runtime.expectations`, and a `runtime.issues` row for each statement
    that still does not hold. A partial run updates the statements it tried
    and keeps what the last run said of the rest."""
    runtime = dict(svc.doc.get("runtime") or {})
    prior = runtime.get("expectations") if isinstance(runtime.get("expectations"), dict) else {}
    tried = {str(r.get("id")) for r in summary.get("results") or []}
    failing = set(summary["failing"])
    untried = set(summary["untried"])
    if partial:
        failing |= {s for s in prior.get("failing") or [] if s not in tried}
        untried |= {s for s in prior.get("untried") or [] if s not in tried}
    total = len(expectations(svc.doc))
    issues = [i for i in runtime.get("issues") or []
              if not (isinstance(i, dict) and i.get("kind") == "expectation"
                      and (not partial or str(i.get("statement")) in tried))]
    platform_ids = {sid for p in summary.get("platform") or [] for sid in p.get("statements") or []}
    issues += [{"kind": "expectation", "statement": r.get("id"), "says": r.get("says"),
                "detail": " | ".join(r.get("failures") or [])[:600]}
               for r in summary.get("results") or [] if r.get("verdict") == "failed"
               and str(r.get("id")) not in platform_ids]
    # One failure across several statements: the platform's, said once.
    issues = [i for i in issues if not (isinstance(i, dict) and i.get("kind") == "platform")]
    issues += [{"kind": "platform", "statements": p["statements"], "detail": p["failure"],
                **({"precondition": p["precondition"]} if p.get("precondition") else {})}
               for p in summary.get("platform") or []]
    # What no screen may show, seen on the way, once per screen and finding.
    issues = [i for i in issues if not (isinstance(i, dict) and i.get("kind") == "screen")]
    seen_on_way = sorted({a for r in summary.get("results") or [] for a in r.get("also") or []
                          if not a.startswith("the ")})
    issues += [{"kind": "screen", "detail": a[:300]} for a in seen_on_way[:20]]
    runtime["issues"] = issues
    runtime["expectations"] = {
        "statements": total, "passed": max(total - len(failing) - len(untried), 0),
        "fixed": sorted(set(list(prior.get("fixed") or []) + summary["fixed"])) if partial else summary["fixed"],
        "failing": sorted(failing), "untried": sorted(untried),
        "version": int(svc.doc.get("version") or 0)}
    svc.doc["runtime"] = runtime
    try:
        svc.save()
    except Exception:  # noqa: BLE001
        logger.warning("[expects] could not record the statements' results", exc_info=True)


# --------------------------------------------------------------------------- #
# After a change
# --------------------------------------------------------------------------- #

def reached(doc: dict, touched: list[str]) -> list[str]:
    """The statements a change could have reached: those whose steps or
    checks are on a screen the change reached (`app_check.affected_pages`)."""
    from services.blueprint.app_check import affected_pages
    pages = affected_pages(doc, touched)
    if not pages:
        return []
    out = []
    for st in expectations(doc):
        used = {str(s.get("page")) for s in (st.get("steps") or []) + (st.get("then") or []) if s.get("page")}
        if used & pages:
            out.append(str(st.get("id")))
    return out


def check_change(output_dir: str, touched: list[str], *,
                 app_factory: Callable[[Path], Any] | None = None,
                 trial: Callable[..., dict] | None = None) -> dict | None:
    """After a change: try the statements it reached and say what no longer
    holds — the person, or Smith's next turn, takes it from there. None when
    it reached none. `said` is the sentence for the reply."""
    from services.blueprint.service import BlueprintService
    from services.build_usage import usage_scope

    if app_factory is None and not (Path(output_dir) / "app" / "package.json").is_file():
        return None
    with usage_scope(agent="change_check", output_dir=str(output_dir), phase="change", kind="smith"):
        svc = BlueprintService.load(output_dir=output_dir)
        ids = reached(svc.doc, touched)[:MAX_CHANGE_STATEMENTS]
        if not ids:
            return None
        out = _prove(svc, output_dir, app_factory=app_factory, trial=trial, only=ids, give_back=False)
    n = len(ids)
    if out["failing"]:
        by_id = {str(st.get("id")): st for st in expectations(svc.doc)}
        names = "; ".join(f"\"{(by_id.get(s) or {}).get('says', s)}\"" for s in out["failing"][:3])
        said = (f"I then tried the {n} statement{'' if n == 1 else 's'} of what must happen that this change "
                f"reaches. Not holding: {names}. Tell me to carry on and I will fix "
                f"{'it' if len(out['failing']) == 1 else 'them'}.")
    else:
        said = (f"I then tried the {n} statement{'' if n == 1 else 's'} of what must happen that this change "
                f"reaches: {'it holds' if n == 1 else 'they hold'}"
                + (f" (fixed on the way: {', '.join(out['fixed'])})" if out["fixed"] else "") + ".")
    return {"tried": ids, "failing": out["failing"], "fixed": out["fixed"], "touched": out["touched"], "said": said}


# --------------------------------------------------------------------------- #
# What Smith reads
# --------------------------------------------------------------------------- #

def lines(doc: dict, output_dir: str) -> list[str]:
    """`EXP-054 [does not hold] When the admin deactivates a product, …` —
    each statement with its last result, for Smith's context."""
    last = last_results(output_dir)
    out: list[tuple[bool, str]] = []
    for st in expectations(doc):
        sid = str(st.get("id"))
        r = last.get(sid) or {}
        mark = {"passed": "holds", "failed": "does not hold", "not_tried": "not tried"}.get(
            str(r.get("verdict")), "not tried yet")
        line = f"{sid} [{mark}] {st.get('says')}"
        if r.get("verdict") == "failed" and r.get("failures"):
            line += f" — {r['failures'][0][:140]}"
        out.append((r.get("verdict") != "failed", line))
    # What does not hold first: a context shortened to fit keeps it.
    return [line for _ok, line in sorted(out, key=lambda x: x[0])]


__all__ = ["prove_expectations", "check_change", "reached", "observation", "owner_of", "author_brief", "lines",
           "last_results", "PLATFORM_SPREAD", "MAX_REPAIRS", "MAX_CHANGE_STATEMENTS"]
