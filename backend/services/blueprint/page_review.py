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


class RunningApp:
    """The generated app, its database up and its dev server serving."""

    def __init__(self, app_root: Path):
        self.root = app_root
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen | None = None

    def __enter__(self) -> "RunningApp":
        if not shutil.which("docker"):
            raise ReviewUnavailable("Docker is not available for the app's database")
        seeded = subprocess.run(["bash", "start.sh", "--seed-only"], cwd=self.root,
                                capture_output=True, text=True, timeout=600)
        if seeded.returncode != 0:
            raise ReviewUnavailable(f"start.sh --seed-only failed: {seeded.stdout[-600:]}{seeded.stderr[-400:]}")
        self.proc = subprocess.Popen(
            ["npx", "next", "dev", "--port", str(self.port)], cwd=self.root,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            env={**os.environ, "BROWSER": "none", "NEXTAUTH_URL": self.base})
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
        subprocess.run(["docker", "compose", "stop"], cwd=self.root, capture_output=True, timeout=120)


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
                               "password": "admin1234", "outDir": str(out_dir), "pages": pages}))
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
                          text=True, timeout=120 + 90 * len(pages), env=env)
    line = next((l for l in reversed(proc.stdout.splitlines()) if l.startswith("[") or l.startswith("{")), "")
    result = json.loads(line) if line else {"error": proc.stderr[-400:]}
    if isinstance(result, dict):
        raise ReviewUnavailable(f"screenshots failed: {result.get('error')}")
    return result


def critique(doc: dict, page: dict, shot: dict, client: Any) -> tuple[dict, Any]:
    """The reviewer's verdict on one screenshot."""
    from services.blueprint.ui_engineer import DESIGN_PRINCIPLES, _page_brief

    comp = doc.get("composition") or {}
    system = ("You review screens of a business application before they ship. You are a senior "
              "product designer with the bar of Linear, Stripe, Notion and Vercel: exacting about "
              "hierarchy, spacing, alignment, density, typography, colour used for meaning, and "
              "whether the page does its job for the people who use it. The data is seeded demo "
              "data — judge the design and the behaviour it implies, not how many rows exist. "
              "Be specific: every issue names where on the page it is and exactly what to change, "
              "in terms a front-end engineer can act on without seeing the screenshot.\n\n"
              f"The app's direction:\n{comp.get('vision') or '(none stated)'}\n"
              + "\n".join(f"- {c.get('topic')}: {c.get('rule')}" for c in comp.get("conventions") or [])
              + f"\n\nThe standard pages are held to:\n{DESIGN_PRINCIPLES}\n\n"
              f"Score 1-10. {PASS_SCORE} or more with no high-severity issue passes.")
    errors = "\n".join(f"- {e}" for e in shot.get("errors") or []) or "(none)"
    user = ("The page's contract:\n```json\n" + json.dumps(_page_brief(doc, page), indent=1)
            + f"\n```\nIt was opened at {shot.get('url')} (HTTP {shot.get('status')}). "
            f"Browser errors while it loaded:\n{errors}\n\nThe screenshot is attached. Review it.")
    t0 = time.monotonic()
    reply = client(system=system, user=user, schema=REVIEW_SCHEMA, images=[shot["file"]])
    body = json.loads(getattr(reply, "text", reply))
    if any(i.get("severity") == "high" for i in body.get("issues") or []) or int(body.get("score") or 0) < PASS_SCORE:
        body["verdict"] = "revise"
    return body, (getattr(reply, "usage", None), time.monotonic() - t0)


def review_brief(review: dict, shot: dict) -> str:
    lines = [f"A reviewer looked at this page as it renders and scored it {review.get('score')}/10. "
             "Keep what works and fix every issue:"]
    for s in review.get("strengths") or []:
        lines.append(f"  + {s}")
    for i in review.get("issues") or []:
        lines.append(f"  - [{i.get('severity')}] {i.get('where')}: {i.get('problem')} → {i.get('fix')}")
    if shot.get("errors"):
        lines.append("The browser reported errors while it loaded — fix their cause:")
        lines += [f"  ! {e}" for e in shot["errors"]]
    return "\n".join(lines)


def review_app(svc: Any, app_root: str | Path, client: Any, *, usage: Any = None,
               rounds: int = ROUNDS, workers: int = 6) -> dict[str, Any]:
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
        pending = [str(r.get("page")) for r in svc.doc.get("pageCode") or [] if r.get("status") != "DEPRECATED"]
    report: dict[str, Any] = {pid: {"scores": [], "rewritten": False} for pid in pending}
    if not pending:
        return {"pages": report, "skipped": "no coded pages"}

    out_root = Path(svc.output_dir) / ".forge" / "review"
    with RunningApp(root) as app:
        for round_ in range(1, rounds + 1):
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
    return {"pages": report}


__all__ = ["review_app", "critique", "shoot", "RunningApp", "ReviewUnavailable", "REVIEW_SCHEMA"]
