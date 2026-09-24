"""The page reviewer — every coded page looked at, and fixed by its author.

A page that compiles can still be a poor page: crowded, flat, a table where a
board was wanted, a KPI with no context, an action you cannot find. Only
looking at it shows that. So after the application is assembled, this:

1. boots it the way a user would — `start.sh --seed-only` (its database,
   migrated and seeded) and the dev server;
2. signs in and screenshots every page that has code (`scripts/page_shots.mjs`),
   opening a `[id]` route on a real record;
3. shows each screenshot to a reviewer model with the page's contract, the
   app's direction and the design principles, and gets a verdict: a score,
   what works, and each problem with where it is and how to fix it;
4. hands every page that did not pass back to the UI engineer with that
   review as its brief and its current code, compiles the rewrite, commits it,
   and — the dev server reloading what changed — looks again.

Bounded: `ROUNDS` looks at most. A page still judged wanting keeps its best
compiled version and the review is recorded; nothing is lost. Everything the
reviewer needs outside Python (Docker for the database, Playwright for the
browser) is checked first — without it the review is skipped and says why.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import logging
import os
import shutil
import signal
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROUNDS = 2
PASS_SCORE = 8
_BACKEND = Path(__file__).resolve().parents[2]
_SHOTS = _BACKEND / "scripts/page_shots.mjs"

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["score", "verdict", "strengths", "issues"],
    "properties": {
        "score": {"type": "integer", "description": "1-10; 8 means ready to ship next to Linear or Stripe."},
        "verdict": {"type": "string", "enum": ["pass", "revise"]},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "issues": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": False,
                      "required": ["severity", "where", "problem", "fix"],
                      "properties": {
                          "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                          "where": {"type": "string"},
                          "problem": {"type": "string"},
                          "fix": {"type": "string"}}},
        },
    },
}


class ReviewUnavailable(RuntimeError):
    """Something the review needs outside Python is missing."""


def _playwright_modules() -> Path:
    """Where `playwright` resolves from — the verify image's own node_modules
    in this repository, the one Playwright install the platform keeps."""
    modules = _BACKEND.parent / "docker/forge-verify/node_modules"
    if (modules / "playwright").is_dir():
        return modules
    raise ReviewUnavailable("Playwright is not installed (docker/forge-verify/node_modules)")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


#: The reviewer's own build directory. `next dev` compiles into `distDir`, and
#: two dev servers sharing one directory overwrite each other's modules — the
#: person's own server on this app then fails every page with
#: "__webpack_modules__[moduleId] is not a function" (2g13o6yz, 2026-09-19).
#: The generated `next.config.js` reads `NEXT_DIST_DIR`, as `verify_build` does.
REVIEW_DIST_DIR = ".next-review"


def _database_url(app_root: Path) -> str | None:
    """The app's DATABASE_URL, from `.env.local` or `.env`."""
    import re as _re
    for name in (".env.local", ".env"):
        try:
            text = (app_root / name).read_text()
        except OSError:
            continue
        m = _re.search(r"^DATABASE_URL=(\S+)", text, _re.M)
        if m:
            return m.group(1).strip().strip('"')
    return None


def _database_port(app_root: Path) -> int | None:
    """The port the app's DATABASE_URL points at."""
    import re as _re
    m = _re.search(r"@[^:/]+:(\d+)/", _database_url(app_root) or "")
    return int(m.group(1)) if m else None


def _clone_database(app_root: Path) -> tuple[str, str, str] | None:
    """A copy of the app's database for the reviewer to click through.

    Pressing every control creates, updates and deletes rows. The person's own
    database is theirs; the review works on `<name>_review`, cloned from it in
    the app's own Postgres container and dropped afterwards. Returns
    (container, copy name, the copy's URL), or None when it cannot be made."""
    url = _database_url(app_root) or ""
    import re as _re
    m = _re.match(r"^(postgres(?:ql)?://[^/]+/)([A-Za-z0-9_]+)", url)
    if not m:
        return None
    base, name = m.group(1), m.group(2)
    copy = f"{name}_review"
    # By the port it publishes: `start.sh` names the compose project through an
    # environment variable `.env` does not keep, so `docker compose ps` run
    # later from the app finds nothing. The port is what the app itself uses.
    port = _database_port(app_root)
    ps = subprocess.run(["docker", "ps", "-q", "--filter", f"publish={port}"],
                        capture_output=True, text=True, timeout=60) if port else None
    container = (ps.stdout.strip().splitlines() or [""])[0] if ps and ps.stdout else ""
    if not container:
        return None
    script = (f'dropdb -U postgres --if-exists {copy} && createdb -U postgres {copy} && '
              f'pg_dump -U postgres {name} | psql -U postgres -q {copy} > /dev/null')
    done = subprocess.run(["docker", "exec", container, "sh", "-c", script],
                          capture_output=True, text=True, timeout=300)
    if done.returncode != 0:
        logger.warning("[page_review] could not copy the database: %s", done.stderr[-300:])
        return None
    return container, copy, base + copy


def _listening(port: int | None) -> bool:
    if not port:
        return False
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


class RunningApp:
    """The generated app, its database up and its dev server serving — beside
    whatever the person is already running, never over it."""

    def __init__(self, app_root: Path):
        self.root = app_root
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen | None = None
        self.started_db = False
        self.clone: tuple[str, str, str] | None = None

    def __enter__(self) -> "RunningApp":
        # A DATABASE THAT IS UP IS SOMEONE'S. `start.sh` finds its port taken,
        # moves the app to another one and rewrites `.env` under the running
        # server; stopping compose afterwards took the person's database down.
        # So a running database is used as it is and left running.
        if not _listening(_database_port(self.root)):
            if not shutil.which("docker"):
                raise ReviewUnavailable("Docker is not available for the app's database")
            seeded = subprocess.run(["bash", "start.sh", "--seed-only"], cwd=self.root,
                                    capture_output=True, text=True, timeout=600)
            if seeded.returncode != 0:
                raise ReviewUnavailable(f"start.sh --seed-only failed: {seeded.stdout[-600:]}{seeded.stderr[-400:]}")
            self.started_db = True
        self.clone = _clone_database(self.root)
        if self.clone is None:
            raise ReviewUnavailable("could not make a copy of the app's database to click through")
        self.proc = subprocess.Popen(
            ["npx", "next", "dev", "--port", str(self.port)], cwd=self.root,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            env={**os.environ, "BROWSER": "none", "NEXTAUTH_URL": self.base,
                 # Also what the SDK's empty state answers to: only this server
                 # builds into `.next-review`.
                 "NEXT_DIST_DIR": REVIEW_DIST_DIR, "DATABASE_URL": self.clone[2]})
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(f"{self.base}/api/auth/csrf", timeout=30)
                return self
            except Exception:  # noqa: BLE001 — not up yet
                time.sleep(2)
        self.__exit__(None, None, None)
        raise ReviewUnavailable("the dev server did not start within 180s")

    def __exit__(self, *exc: Any) -> None:
        if self.proc is not None:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(os.getpgid(self.proc.pid), sig)
                    self.proc.wait(timeout=10)
                    break
                except Exception:  # noqa: BLE001
                    continue
        if self.clone is not None:
            container, copy, _ = self.clone
            subprocess.run(["docker", "exec", container, "dropdb", "-U", "postgres", "--if-exists", copy],
                           capture_output=True, timeout=120)
        if self.started_db:
            subprocess.run(["docker", "compose", "stop"], cwd=self.root, capture_output=True, timeout=120)
        shutil.rmtree(self.root / REVIEW_DIST_DIR, ignore_errors=True)


def shoot(app: RunningApp, doc: dict, page_ids: list[str], out_dir: Path) -> list[dict]:
    """Screenshot the pages, signed in as the seeded administrator."""
    modules = _playwright_modules()
    ents = {str(e.get("id")): e for e in (doc.get("data") or {}).get("entities") or []}
    pages = []
    for p in doc.get("pages") or []:
        if str(p.get("id")) in page_ids:
            ent = ents.get(str((p.get("data") or {}).get("primaryEntity") or ""))
            pages.append({"id": p.get("id"), "route": p.get("route"),
                          "entity": (ent or {}).get("name")})
    cfg = out_dir / "shots.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"baseUrl": app.base, "email": "admin@example.com",
                               "password": "admin1234", "outDir": str(out_dir), "pages": pages,
                               "probe": True}))
    work = out_dir / "run"
    work.mkdir(exist_ok=True)
    link = work / "node_modules"
    if not link.exists():
        link.symlink_to(modules)
    script = work / "page_shots.mjs"
    shutil.copyfile(_SHOTS, script)
    env = {**os.environ}
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(Path.home() / "Library/Caches/ms-playwright"))
    proc = subprocess.run(["node", str(script), str(cfg)], cwd=work, capture_output=True,
                          text=True, timeout=180 + 240 * len(pages), env=env)
    line = next((l for l in reversed(proc.stdout.splitlines()) if l.startswith("[") or l.startswith("{")), "")
    result = json.loads(line) if line else {"error": proc.stderr[-400:]}
    if isinstance(result, dict):
        raise ReviewUnavailable(f"screenshots failed: {result.get('error')}")
    return result


#: What a control did that means it does not work.
BROKEN_OUTCOMES = {"nothing": "does nothing when pressed", "error": "errors",
                   "broken-link": "leads to a page that is not there",
                   "workflow-failed": "runs a workflow that fails"}


def hard_findings(shot: dict) -> list[str]:
    """What the browser proved is broken — no judgement involved, so these
    fail the page whatever it scores: an error while it loads, empty or not,
    a record page that crashes on a record that does not exist, and a control
    that does nothing or fails when pressed."""
    out = [f"the page errors as it loads: {e}" for e in shot.get("errors") or []]
    if shot.get("status") and int(shot["status"]) >= 500:
        out.append(f"the page answers HTTP {shot['status']}")
    empty = (shot.get("states") or {}).get("empty")
    if empty:
        if empty.get("status") and int(empty["status"]) >= 500:
            out.append(f"with no data the page answers HTTP {empty['status']}")
        out += [f"with no data the page errors: {e}" for e in empty.get("errors") or []]
    missing = (shot.get("states") or {}).get("missing")
    if missing:
        # The rendered 404 counts, not only the status: a streamed response
        # (the app has a `loading.tsx`) sends the not-found page as HTTP 200.
        if missing.get("status") != 404 and str(missing.get("state")) != "404":
            out.append(f"for a record that does not exist the page renders as if it did "
                       f"(HTTP {missing.get('status')}) — load must return null so it is a 404")
        out += [f"for a record that does not exist the page errors: {e}" for e in missing.get("errors") or []]
    for c in shot.get("controls") or []:
        if c.get("outcome") in BROKEN_OUTCOMES:
            out.append(f"the {c.get('kind')} \"{c.get('label')}\" {BROKEN_OUTCOMES[c['outcome']]}"
                       f" ({c.get('detail')})")
    return out


def reviewer_system(doc: dict) -> str:
    """Who the reviewer is and what it holds a page to — shared with
    `page_look`, which asks the same reviewer as a page is written."""
    from services.blueprint.ui_engineer import DESIGN_PRINCIPLES

    comp = doc.get("composition") or {}
    return ("You review screens of a business application before they ship. You are a senior "
              "product designer with the bar of Linear, Stripe, Notion and Vercel: exacting about "
              "hierarchy, spacing, alignment, density, typography, colour used for meaning, and "
              "whether the page does its job for the people who use it. The data is seeded demo "
              "data — judge the design and the behaviour it implies, not how many rows exist. "
              "The app's frame (the sidebar or the public top bar, with the menu and the app's "
              "name) is the platform's and is the same on every page — judge the content. A page "
              "that draws its own sidebar, top navigation or app header is a high-severity issue: "
              "remove it. "
              "Be specific: every issue names where on the page it is and exactly what to change, "
              "in terms a front-end engineer can act on without seeing the screenshot.\n\n"
              f"The app's direction:\n{comp.get('vision') or '(none stated)'}\n"
              + "\n".join(f"- {c.get('topic')}: {c.get('rule')}" for c in comp.get("conventions") or [])
              + f"\n\nThe standard pages are held to:\n{DESIGN_PRINCIPLES}\n\n"
              f"Score 1-10. {PASS_SCORE} or more with no high-severity issue passes.")


def critique(doc: dict, page: dict, shot: dict, client: Any) -> tuple[dict, Any]:
    """The reviewer's verdict on one screenshot."""
    from services.blueprint.ui_engineer import _page_brief

    system = reviewer_system(doc)
    hard = hard_findings(shot)
    broken = "\n".join(f"- {h}" for h in hard) or "(none)"
    pressed = "\n".join(f"- {c.get('kind')} \"{c.get('label')}\": {c.get('outcome')} — {c.get('detail')}"
                        for c in shot.get("controls") or []) or "(no controls)"
    user = ("The page's contract:\n```json\n" + json.dumps(_page_brief(doc, page), indent=1)
            + f"\n```\nIt was opened at {shot.get('url')} (HTTP {shot.get('status')}).\n\n"
            f"What the browser proved broken:\n{broken}\n\n"
            f"Every control was pressed; what each did:\n{pressed}\n\n"
            "The first screenshot is the page with its data; the second, when attached, is the "
            "same page with no data at all — its empty state. Review both.")
    images = [shot["file"]]
    empty = ((shot.get("states") or {}).get("empty") or {}).get("file")
    if empty and Path(empty).exists():
        images.append(empty)
    t0 = time.monotonic()
    reply = client(system=system, user=user, schema=REVIEW_SCHEMA, images=images)
    body = json.loads(getattr(reply, "text", reply))
    body["broken"] = hard
    if hard or any(i.get("severity") == "high" for i in body.get("issues") or []) \
            or int(body.get("score") or 0) < PASS_SCORE:
        body["verdict"] = "revise"
    return body, (getattr(reply, "usage", None), time.monotonic() - t0)


def review_brief(review: dict, shot: dict) -> str:
    lines = [f"A reviewer looked at this page as it renders and scored it {review.get('score')}/10. "
             "Keep what works and fix every issue:"]
    for s in review.get("strengths") or []:
        lines.append(f"  + {s}")
    broken = review.get("broken") or hard_findings(shot)
    if broken:
        lines.append("BROKEN — proved in the browser, fix every one first:")
        lines += [f"  ! {b}" for b in broken]
    for i in review.get("issues") or []:
        lines.append(f"  - [{i.get('severity')}] {i.get('where')}: {i.get('problem')} → {i.get('fix')}")
    return "\n".join(lines)


def review_app(svc: Any, app_root: str | Path, client: Any, *, usage: Any = None,
               rounds: int = ROUNDS, workers: int = 6, only: set[str] | None = None,
               emit: Any = None) -> dict[str, Any]:
    """Look at every coded page and have the failing ones rewritten.

    Returns what happened per page: its scores by round, whether it passed,
    and whether it was rewritten. Writes nothing but `pageCode` (through the
    same contract as any authored page) and the files that project from it."""
    from services.blueprint.agent_contract import AgentResult, ArtifactProposal, apply_agent_result
    from services.blueprint.app_sdk import project_code_pages
    from services.blueprint.ui_engineer import CompileError, compose_page

    root = Path(app_root)
    project = str((svc.doc.get("application") or {}).get("id", ""))

    def record(node: str, agent: str, spent: Any) -> None:
        u, elapsed = spent if isinstance(spent, tuple) else (spent, 0.0)
        if usage is not None and u is not None:
            usage.record(node=node, agent=agent, usage=u, elapsed_s=elapsed, project=project)

    with svc.lock:
        pending = [str(r.get("page")) for r in svc.doc.get("pageCode") or []
                   if r.get("status") != "DEPRECATED" and (only is None or str(r.get("page")) in only)]
        routes = {str(p.get("id")): str(p.get("route") or p.get("id")) for p in svc.doc.get("pages") or []}

    def say(phase: str, **payload: Any) -> None:
        if emit is not None:
            try:
                emit("review", {"phase": phase, **payload})
            except Exception:  # noqa: BLE001 — narration never fails a review
                pass
    report: dict[str, Any] = {pid: {"scores": [], "rewritten": False} for pid in pending}
    if not pending:
        return {"pages": report, "skipped": "no coded pages"}

    out_root = Path(svc.output_dir) / ".forge" / "review"
    # THE BEST VERSION WINS. A rewrite is not always better — the edit page of
    # 2g13o6yz went 7 -> 6 and the worse one stayed (2026-09-19). Each judged
    # version is ranked (nothing proven broken first, then the score) and the
    # best one is what the page keeps.
    best: dict[str, tuple[tuple[int, int], dict, dict]] = {}
    latest: dict[str, tuple[int, int]] = {}
    with RunningApp(root) as app:
        for round_ in range(1, rounds + 1):
            say("shots", round=round_, pages=[routes.get(p, p) for p in pending])
            with svc.lock:
                doc = json.loads(json.dumps(svc.doc))
            shots = {s["id"]: s for s in shoot(app, doc, pending, out_root / f"round-{round_}")
                     if not s.get("skipped")}
            pages = {str(p.get("id")): p for p in doc.get("pages") or []}

            def judge(pid: str) -> tuple[str, dict | None]:
                if pid not in shots:
                    return pid, None
                body, spent = critique(doc, pages[pid], shots[pid], client)
                record("page_review", "page_reviewer", spent)
                return pid, body

            say("analysis", round=round_)
            with cf.ThreadPoolExecutor(workers) as pool:
                verdicts = dict(pool.map(judge, pending))
            failing = []
            for pid, v in verdicts.items():
                if v is None:
                    report[pid]["skipped"] = "no screenshot"
                    continue
                report[pid]["scores"].append(v.get("score"))
                report[pid]["review"] = v
                report[pid]["passed"] = v.get("verdict") == "pass"
                rank = (0 if v.get("broken") else 1, int(v.get("score") or 0))
                latest[pid] = rank
                row = next((r for r in doc.get("pageCode") or [] if str(r.get("page")) == pid), None)
                if row is not None and (pid not in best or rank > best[pid][0]):
                    best[pid] = (rank, dict(row), v)
                if v.get("verdict") != "pass":
                    failing.append(pid)
            logger.info("[page_review] round %d: %d of %d pages need work", round_, len(failing), len(pending))
            if not failing or round_ == rounds:
                break

            def rewrite(pid: str) -> tuple[str, dict | None]:
                current = next((r for r in doc.get("pageCode") or [] if str(r.get("page")) == pid), None)
                try:
                    body, spent = compose_page(doc, pages[pid], root, client,
                                               brief=review_brief(verdicts[pid], shots[pid]),
                                               current=current)
                except CompileError as exc:
                    logger.warning("[page_review] %s rewrite did not compile: %s", pid, exc)
                    return pid, None
                for s in spent:
                    record("page_code", "ui_engineer", s)
                return pid, body

            say("fixing", round=round_, pages=[routes.get(p, p) for p in failing])
            with cf.ThreadPoolExecutor(workers) as pool:
                rewrites = [r for r in pool.map(rewrite, failing) if r[1] is not None]
            for pid, body in rewrites:
                result = AgentResult(task_id=f"TASK-page_review-{pid}-{round_}", agent="ui_engineer",
                                     confidence=0.9,
                                     proposals=[ArtifactProposal(section="pageCode", natural_key=pid, body=body)])
                with svc.lock:
                    apply_agent_result(svc, result, commit=True)
                report[pid]["rewritten"] = True
            with svc.lock:
                project_code_pages(svc.doc, root)
            time.sleep(4)                       # the dev server recompiles what changed
            pending = [pid for pid, _ in rewrites]
            if not pending:
                break
        # A page whose last version ranks below its best gets the best back.
        restored = []
        for pid, (rank, row, verdict) in best.items():
            if latest.get(pid, rank) < rank:
                keep = {k: row[k] for k in ("page", "rationale", "load", "view", "requirements") if k in row}
                with svc.lock:
                    apply_agent_result(svc, AgentResult(
                        task_id=f"TASK-page_review-{pid}-best", agent="ui_engineer", confidence=0.9,
                        proposals=[ArtifactProposal(section="pageCode", natural_key=pid, body=keep)]),
                        commit=True)
                report[pid]["passed"] = verdict.get("verdict") == "pass"
                report[pid]["review"] = verdict
                restored.append(pid)
        if restored:
            with svc.lock:
                project_code_pages(svc.doc, root)
            logger.info("[page_review] kept the better earlier version of %s", ", ".join(restored))
    return {"pages": report}


__all__ = ["review_app", "critique", "shoot", "RunningApp", "ReviewUnavailable", "REVIEW_SCHEMA"]
