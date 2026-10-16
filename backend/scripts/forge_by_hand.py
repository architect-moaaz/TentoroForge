"""Build an app through Forge's OWN code, with a person (or an agent session) answering where a model would.

Everything the Build button does still happens: the approvals, the designer question, the node graph in
its order, the run ledger, the page compiler and its wiring checks, assembly, the app check. Only the
model is replaced. Each time the platform would call a model for something that matters, it writes the
request to a file and WAITS; you read it, write the answer the model would have written, and it carries
on. Every other agent step that has nothing to add gets the empty envelope an agent returns then.

No real model is ever called: the model API keys are blanked for this process, so nothing here can spend
them. (To use a real model, run the platform normally instead of this script.)

THE COMMANDS  (from the repo root; use the backend's Python so its packages are found)

    PY=backend/venv/Scripts/python.exe          # Windows;  backend/venv/bin/python on macOS / Linux
    SCRIPT=backend/scripts/forge_by_hand.py

  Start the platform API with the file model, so the web UI works and model calls wait for you:
    $PY $SCRIPT serve --port 6500

  Or build a project folder with no UI at all (what Build does, for an existing Blueprint):
    $PY $SCRIPT build output/<short_id> --designer forge

  Then, from ANY other shell or session, see what is waiting and answer it:
    $PY $SCRIPT pending
    $PY $SCRIPT show 003-page-PAGE-001
    $PY $SCRIPT answer-page PAGE-001 --load load.ts --view view.tsx --rationale "why this layout"
    $PY $SCRIPT answer-plan PAGE-003 --state "None" --section "Form" --behaviour "runs List Tool"
    $PY $SCRIPT answer-native PAGE-001 --screen Screen.tsx --rationale "why this layout"
    $PY $SCRIPT answer 001-coverage --json reply.json        # any other request: the exact JSON reply

  What each request is, and the shape of its reply, is at the end of the request file itself
  (`# SCHEMA`). The kinds that wait by default:
    coverage   the Figma coverage check        reply: {requirements, unmatchedFrames, missingScreens, frameChanges}
    pageplan   how to build a page             reply: {state, sections[], behaviours[]}
    page       write one page                  reply: {rationale, load, view}
    native     write one page as a native      reply: {rationale, screen, needs}   (only when the app is native)
  Add --wait-all to `serve`/`build` to make EVERY agent step wait (to author a Blueprint from nothing).

THE QUEUE is a folder (default output/.file-model-queue, or --queue / FORGE_FILE_MODEL_QUEUE):
    <n>-<kind>[-<PAGE-ID>].request.md       what the platform asked: system, user, schema
    <n>-<kind>[-<PAGE-ID>].response.json    your answer, exactly the text the model would have returned
A request with no response file is waiting. Answer it and the platform carries on within a second.
If a page you wrote fails the compiler or a check, the SAME page is asked again with the errors in its
prompt: look at `pending` again.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
DEFAULT_QUEUE = REPO / "output" / ".file-model-queue"
WAIT_S = 3 * 3600
POLL_S = 1.0

#: What the platform asks that is worth a person's answer, by the first words of its prompt. Every other
#: agent step gets the empty envelope (`EMPTY`) unless --wait-all.
_COVERAGE_OPENING = "You check whether a design a person drew in Figma"
EMPTY = {"proposals": [], "confidence": 0.9, "issues": [], "change_requests": [],
         "assumptions": ["Nothing to add at this step."]}


def kind_of(system: str, user: str) -> str | None:
    """``coverage`` / ``pageplan`` / ``page`` / ``native`` for the requests that wait by default, else None."""
    if (system or "").startswith(_COVERAGE_OPENING):
        return "coverage"
    if "Decide how to build this page" in (user or ""):
        return "pageplan"
    if (user or "").lstrip().startswith("Write this page."):
        return "page"
    if (user or "").lstrip().startswith("Write this page as a native screen."):
        return "native"
    return None


class FileModel:
    """The model, as files. Callable like the platform's model client; `for_task` returns it unchanged."""

    enforces_schema = True
    accepts_images = False
    max_tokens = 0

    def __init__(self, queue: Path, *, wait_all: bool = False, wait_s: float = WAIT_S, poll_s: float = POLL_S,
                 log=print):
        self.queue, self.wait_all, self.wait_s, self.poll_s, self.log = Path(queue), wait_all, wait_s, poll_s, log
        self.queue.mkdir(parents=True, exist_ok=True)
        self._n = max([int(p.name[:3]) for p in self.queue.glob("*.request.md") if p.name[:3].isdigit()] or [0])
        self._node = ""

    def for_task(self, node: str, agent: str) -> "FileModel":
        return self

    def __call__(self, *, system, user, schema=None, images=None, **kw):
        kind = kind_of(system or "", user or "")
        if kind is None and not self.wait_all:
            return json.dumps(EMPTY)
        kind = kind or "step"
        self._n += 1
        stem = f"{self._n:03d}-{kind}"
        page = re.search(r'"id": "(PAGE-\d+)"', user or "")
        if page and kind in ("page", "pageplan", "native"):
            stem += "-" + page.group(1)
        request, response = self.queue / f"{stem}.request.md", self.queue / f"{stem}.response.json"
        request.write_text("# SYSTEM\n\n" + (system or "") + "\n\n# USER\n\n" + (user or "")
                           + "\n\n# SCHEMA\n\n```json\n" + json.dumps(schema, indent=1) + "\n```\n", encoding="utf-8")
        self.log(f"[file-model] waiting for an answer: {stem}")
        started = time.time()
        while time.time() - started < self.wait_s:
            if response.exists():
                self.log(f"[file-model] answered: {stem}")
                return response.read_text(encoding="utf-8")
            time.sleep(self.poll_s)
        raise TimeoutError(f"nobody answered {stem} in {self.wait_s:.0f}s")


# --------------------------------------------------------------------------- #
# Putting the file model where the platform's model would be
# --------------------------------------------------------------------------- #

def _resolve_commands_on_windows() -> None:
    """The platform runs `["npm", …]` / `["npx", …]` as plain argument lists, which Windows cannot start:
    npm is `npm.cmd` there. Resolve those few names through PATH in this process only, so the build can
    install and compile an app here; nothing in the product is changed."""
    if os.name != "nt":
        return
    import shutil
    import subprocess

    original = subprocess.Popen.__init__

    def init(self, args, *a, **kw):
        if isinstance(args, (list, tuple)) and args and args[0] in ("npm", "npx", "node", "tsc", "tsx", "esbuild"):
            found = shutil.which(args[0])
            if found:
                args = [found, *args[1:]]
        original(self, args, *a, **kw)

    subprocess.Popen.__init__ = init


def install(queue: Path, *, wait_all: bool = False) -> FileModel:
    """Blank the model keys and replace the platform's model router, BEFORE the platform is imported."""
    for key in ("ANTHROPIC_API_KEY", "KIMI_API_KEY", "FORGE_UI_DESIGNER"):
        os.environ[key] = ""                       # set (empty) so .env cannot fill them in
    sys.path.insert(0, str(BACKEND))
    os.chdir(BACKEND)
    from dotenv import load_dotenv

    load_dotenv(BACKEND / ".env")                  # does not override what is already set
    for key in ("ANTHROPIC_API_KEY", "KIMI_API_KEY", "FORGE_UI_DESIGNER"):
        os.environ[key] = ""
    model = FileModel(queue, wait_all=wait_all)
    _resolve_commands_on_windows()
    from services.blueprint import executors, observer

    executors.tiered_router = lambda *a, **k: model
    observer.anthropic_observer = lambda *a, **k: None
    return model


def cmd_serve(args: argparse.Namespace) -> int:
    install(Path(args.queue), wait_all=args.wait_all)
    import uvicorn

    import main                                    # the product's own app, imported AFTER the router was replaced

    print(f"[file-model] queue: {args.queue}", flush=True)
    uvicorn.run(main.app, host=args.host, port=args.port, log_level="info")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    out = Path(args.output_dir).resolve()
    install(Path(args.queue), wait_all=args.wait_all)
    from routers import blueprint_generate as router
    from services.blueprint.service import BlueprintService
    from services.smith import ui_designer

    if args.designer:
        svc = BlueprintService.load(output_dir=str(out))
        ui_designer.record(svc, args.designer)

    def emit(kind: str, data: Any) -> None:
        text = data.get("text") if isinstance(data, dict) else None
        if kind in ("message", "plan", "error", "done") or kind.startswith("node"):
            print(f"[{kind}]", (text or json.dumps(data, default=str))[:300], flush=True)

    print(f"[file-model] queue: {args.queue}", flush=True)
    result = router._run_dag(str(out), str(out / "app"), "", approved=True, emit=emit, app_name=args.name or "")
    print("RESULT", json.dumps({k: v for k, v in (result or {}).items() if k != "report"}, default=str)[:500])
    return 0


# --------------------------------------------------------------------------- #
# Reading and answering the queue (no platform needed: works from any shell)
# --------------------------------------------------------------------------- #

def _requests(queue: Path) -> list[Path]:
    return sorted(queue.glob("*.request.md"))


def _waiting(queue: Path) -> list[Path]:
    return [p for p in _requests(queue) if not p.with_name(p.name.replace(".request.md", ".response.json")).exists()]


def _resolve(queue: Path, stem: str) -> Path:
    exact = queue / f"{stem}.request.md"
    if exact.exists():
        return exact
    hits = [p for p in _waiting(queue) if stem in p.name] or [p for p in _requests(queue) if stem in p.name]
    if len(hits) != 1:
        raise SystemExit(f"{stem!r} matches {len(hits)} requests: {[p.name for p in hits]}")
    return hits[0]


def _write_answer(request: Path, body: str) -> Path:
    json.loads(body)                               # an answer that is not JSON would fail the platform's decode
    out = request.with_name(request.name.replace(".request.md", ".response.json"))
    out.write_text(body, encoding="utf-8")
    return out


def cmd_pending(args: argparse.Namespace) -> int:
    waiting = _waiting(Path(args.queue))
    if not waiting:
        print("nothing is waiting")
    for p in waiting:
        print(p.name.replace(".request.md", ""))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    sys.stdout.write(_resolve(Path(args.queue), args.stem).read_text(encoding="utf-8"))
    return 0


def cmd_answer(args: argparse.Namespace) -> int:
    request = _resolve(Path(args.queue), args.stem)
    body = sys.stdin.read() if args.json == "-" else Path(args.json).read_text(encoding="utf-8")
    print("answered", _write_answer(request, body).name)
    return 0


def cmd_answer_page(args: argparse.Namespace) -> int:
    request = _resolve(Path(args.queue), f"-page-{args.page}")
    body = {"rationale": args.rationale.strip(), "load": Path(args.load).read_text(encoding="utf-8"),
            "view": Path(args.view).read_text(encoding="utf-8")}
    print("answered", _write_answer(request, json.dumps(body)).name)
    return 0


def cmd_answer_native(args: argparse.Namespace) -> int:
    request = _resolve(Path(args.queue), f"-native-{args.page}")
    body = {"rationale": args.rationale.strip(), "screen": Path(args.screen).read_text(encoding="utf-8"),
            "needs": args.need}
    print("answered", _write_answer(request, json.dumps(body)).name)
    return 0


def cmd_answer_plan(args: argparse.Namespace) -> int:
    request = _resolve(Path(args.queue), f"-pageplan-{args.page}")
    body = {"state": args.state, "sections": args.section, "behaviours": args.behaviour}
    print("answered", _write_answer(request, json.dumps(body)).name)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="forge_by_hand.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--queue", default=os.environ.get("FORGE_FILE_MODEL_QUEUE", str(DEFAULT_QUEUE)),
                    help="the folder the requests and answers live in")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="the platform API with the file model")
    s.add_argument("--port", type=int, default=6500)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--wait-all", action="store_true", help="every agent step waits for an answer")
    s.set_defaults(fn=cmd_serve)

    b = sub.add_parser("build", help="build a project folder with no UI")
    b.add_argument("output_dir", help="the project's folder, e.g. output/<short_id> (it has .forge/blueprint)")
    b.add_argument("--designer", choices=("forge", "uxpilot", "figma"),
                   help="answer 'who designs the screens?' first, so the build is not stopped to ask")
    b.add_argument("--name", default="", help="the application's name, for the narration")
    b.add_argument("--wait-all", action="store_true", help="every agent step waits for an answer")
    b.set_defaults(fn=cmd_build)

    sub.add_parser("pending", help="the requests waiting for an answer").set_defaults(fn=cmd_pending)

    sh = sub.add_parser("show", help="print one request")
    sh.add_argument("stem", help="e.g. 003-page-PAGE-001 (a unique part of the name is enough)")
    sh.set_defaults(fn=cmd_show)

    an = sub.add_parser("answer", help="answer a request with a JSON file (or - for stdin)")
    an.add_argument("stem")
    an.add_argument("--json", required=True)
    an.set_defaults(fn=cmd_answer)

    ap_ = sub.add_parser("answer-page", help="answer a page request from its load.ts and view.tsx")
    ap_.add_argument("page", help="PAGE-001")
    ap_.add_argument("--load", required=True)
    ap_.add_argument("--view", required=True)
    ap_.add_argument("--rationale", required=True)
    ap_.set_defaults(fn=cmd_answer_page)

    nt = sub.add_parser("answer-native", help="answer a native-screen request from its Screen.tsx")
    nt.add_argument("page", help="PAGE-001")
    nt.add_argument("--screen", required=True)
    nt.add_argument("--rationale", required=True)
    nt.add_argument("--need", action="append", default=[], help="a change no workflow makes (rare)")
    nt.set_defaults(fn=cmd_answer_native)

    pl = sub.add_parser("answer-plan", help="answer a page-plan request")
    pl.add_argument("page", help="PAGE-003")
    pl.add_argument("--state", required=True)
    pl.add_argument("--section", action="append", default=[], required=True)
    pl.add_argument("--behaviour", action="append", default=[], required=True)
    pl.set_defaults(fn=cmd_answer_plan)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.fn(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
