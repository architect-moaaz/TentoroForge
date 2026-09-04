"""A conversation with Smith, from a terminal (PRD §6, §16, §69, §114).

Not the product surface — §108–§112 describe that, and it is a web workspace.
This exists so the conversational layer can be driven against a real model and
a real Blueprint without one, which is the only way to find out whether the
prompts work.

    python3 -m services.smith.cli --blueprint fleet/blueprints/ats-live.json

Opens on the ATS fixture: 18 requirements, 8 entities, 18 pages, 16 workflows,
54 artifacts below §17's ask-the-user line. The fixture is copied into a
working directory and adopted (§12 ids re-bound), so the standing fixture is
never written to.

Commands
--------
    status                      what Smith knows
    ask                         §16 — the 3–5 questions that matter most
    trace REQ-017               §18 — has this requirement been implemented?
    explain <question>          §7.27 — read-only
    /page PAGE-009 /cmp CMP-033 <text>
                                §69 — a preview selection, then a request
    <anything else>             one turn

``--dry-run`` prints the prompt that would be sent and stops. Nothing is
billed, and it is the fastest way to see what Smith is actually being told.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:  # `python3 -m` from the repo root
    sys.path.insert(0, str(BACKEND))

from services.smith.change import resolve_preview  # noqa: E402
from services.smith.smith import Smith  # noqa: E402

DEFAULT_BLUEPRINT = BACKEND / "fleet" / "blueprints" / "ats-live.json"
DEFAULT_OUTPUT = BACKEND.parent / "output" / "smith-session"


class DryRunModel:
    """Prints what would have been sent, and refuses to invent an answer.

    Deliberately not a stub that returns plausible JSON. A dry run that
    produced a fake plan would exercise the plumbing and tell you nothing about
    the prompt, which is the only thing a dry run is for.
    """

    enforces_schema = True

    def __call__(self, *, system: str, user: str, schema: Any = None) -> str:
        print("\n--- system " + "-" * 60)
        print(system)
        print("\n--- user " + "-" * 62)
        print(user[:6000] + ("\n… (truncated)" if len(user) > 6000 else ""))
        print("-" * 72)
        raise SystemExit(0)


def _load_env() -> None:
    """Read ``backend/.env`` for credentials, the way ``main.py`` does.

    ``load_dotenv`` never overrides a variable that is already set, so an
    explicit export still wins. Nothing here reads or prints a value.
    """
    from dotenv import load_dotenv

    load_dotenv(BACKEND / ".env")


def _model(dry_run: bool, model_name: str) -> Any:
    if dry_run:
        return DryRunModel()
    import os

    _load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set and was not found in backend/.env. "
            "Use --dry-run to see the prompts without calling a model."
        )
    from services.blueprint.executors import AnthropicModel

    return AnthropicModel(model=model_name)


def _open(
    blueprint: Path, output_dir: Path, *, new: str = "", domain: str = "",
    **kw: Any,
) -> Smith:
    """Adopt the Blueprint into a working directory, resume one, or start empty.

    Resuming is the interesting half: the conversation, the versions and the
    ids are all on disk, so a second run continues rather than restarts (§118).

    ``new`` starts from nothing — §107 step 1, the case Smith could not handle
    at all until the lifecycle was wired: no artifacts, no impact, nothing to
    be incremental about.
    """
    current = output_dir / ".forge" / "blueprint" / "current.json"
    if current.exists():
        print(f"resuming {output_dir}")
        return Smith.load(output_dir, **kw)

    if new:
        from services.blueprint.service import BlueprintService

        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"new application {new!r} ({domain or 'unknown domain'}) in {output_dir}")
        svc = BlueprintService.create(
            output_dir=output_dir, app_id=new.lower().replace(" ", "-"),
            name=new, domain=domain or "unknown",
        )
        return Smith(svc, **kw)

    output_dir.mkdir(parents=True, exist_ok=True)
    doc = json.loads(blueprint.read_text("utf-8"))
    print(f"adopting {blueprint.name} into {output_dir}")
    return Smith.adopt(doc, output_dir, **kw)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def show_greeting(smith: Smith) -> None:
    """§107 step 1. Printed before the first prompt, not on request."""
    g = smith.greet()
    print(f"\nSmith: {g.headline}")
    if g.detail:
        print(f"  {g.detail}")
    for opener in g.openers:
        print(f"    · {opener.kind} — {opener.example}")
    if g.next_act:
        print(f"  {g.next_act}")


def show_status(smith: Smith) -> None:
    s = smith.status()
    print(f"\n{s['application']}  v{s['version']}  [{s['state']}]")
    print(f"  conversation   {s['messages']} messages")
    c = s["clarification"]
    print(f"  open questions {c['open']} ({c['blocking']} blocking) "
          f"across {len(c['sections'])} sections")
    if c["weakest"]:
        print(f"  thin           {', '.join(c['weakest'])}")
    d = s["decisions"]
    print(f"  decisions      {d['total']} ({d['byUser']} made by you)")
    code = s["code"]
    print(f"  implementation {code['mapped']}/{code['artifacts']} artifacts mapped")


def show_questions(smith: Smith) -> None:
    """§16 — show the selection arithmetic next to the questions.

    The 'why' line is the part worth seeing: it is the whole reason these five
    and not the other forty-nine.
    """
    batch = smith.open_questions()
    if not batch:
        print("\nNothing material is unresolved.")
        return
    print("\nSelected by materiality:")
    for q in batch:
        print(f"  {q.artifact:12} {q.section:14} score {q.score:5.2f}  {q.label[:48]}")
        print(f"  {'':12} {q.why}")

    worded = smith.ask()
    print("\n" + worded.render())


def _print_domain(summary: dict) -> None:
    """§107 step 8's gate — what Smith understood, in a shape a person reads.

    Prose rather than counts, because this is the gate where the user is asked
    whether Smith has the problem right, and "4 personas" is not something
    anyone can agree or disagree with.
    """
    print("\n  --- what I understood (§107 step 8) ---")
    if summary.get("application"):
        print(f"  {summary['application']}")

    for objective in summary.get("objectives") or []:
        print(f"    · {objective}")

    for person in summary.get("personas") or []:
        line = person.get("name", "")
        if person.get("description"):
            line += f" — {person['description']}"
        print(f"    who: {line}")

    for term, meaning in (summary.get("terminology") or {}).items():
        print(f"    word: {term} = {meaning}")

    if summary.get("capabilities"):
        print(f"    does: {', '.join(summary['capabilities'])}")

    reqs, assumed = summary.get("requirements") or [], summary.get("assumed") or []
    print(f"  {len(reqs)} requirements", end="")
    # The assumptions are the reason to read the rest, so they are named rather
    # than counted: a user can only correct a guess they can see.
    print(f", {len(assumed)} I assumed — {', '.join(assumed)}" if assumed else "")


def _print_design(summary: dict) -> None:
    """The half of §26's plan that is not a count.

    The palette is the one thing at this gate a person judges at a glance, and
    the first thing they notice is wrong. Printed as the swatch names beside
    their values, because "primary" and "#0f766e" mean something together and
    neither means much alone.
    """
    if not any(summary.get(k) for k in
               ("personality", "colors", "density", "navigation")):
        return

    print("\n  --- design language ---")
    if summary.get("personality"):
        print(f"  {summary['personality']}")
    for role, value in (summary.get("colors") or {}).items():
        print(f"    {role:14} {value}")
    for label, key in (("density", "density"), ("navigation", "navigation")):
        if summary.get(key):
            print(f"    {label:14} {summary[key]}")
    if summary.get("referencesShown"):
        # Shown, not used. Whether the palette came off them is a claim only
        # `visualPersonality` can make.
        print(f"    shown          {', '.join(summary['referencesShown'])}")


def show_turn(smith: Smith, turn: Any) -> None:
    if not turn.ok:
        print(f"\n[rejected] {turn.rejected}")
        print(f"Smith: {turn.reply}")
        return

    print(f"\nSmith: {turn.reply}")
    if turn.plan:
        print(f"  intent {turn.plan.intent}  confidence {turn.plan.confidence:.2f}")
        if turn.plan.summary:
            print(f"  read as: {turn.plan.summary}")

    if turn.moved:
        print(f"  §94 state: {turn.state_before} -> {turn.state_after}")

    if turn.command:
        result = turn.command_result or {}
        if "refused" in result:
            print(f"  {turn.command}: refused — {result['refused']}")
        else:
            print(f"  {turn.command}: " + ", ".join(
                f"{k}={v}" for k, v in result.items() if not isinstance(v, dict)))

    if turn.domain_summary:
        _print_domain(turn.domain_summary)

    if turn.plan_summary:
        print("\n  --- build plan (§26) ---")
        for key, count in turn.plan_summary.items():
            print(f"  {count:5}  {key}")

    if turn.design_summary:
        _print_design(turn.design_summary)

    if turn.run and not turn.command_result.get("refused"):
        r = turn.run
        print(f"  ran {len(r.completed)} nodes, {len(r.skipped)} skipped, "
              f"{len(r.blocked)} blocked, {len(r.failed)} failed")
        if r.failed:
            print(f"  failed: {', '.join(r.failed)}")

    for rec in turn.recorded:
        kind = "delegated to Smith" if rec.delegated else "your decision"
        print(f"  recorded {rec.id} on {rec.artifact} ({kind}): {rec.decision}")

    if turn.change:
        change = turn.change
        if not change.applied:
            print(f"  no change: {change.reason}")
        else:
            print("\n  --- impact (§71) ---")
            for line in change.impact.render().splitlines():
                print(f"  {line}")
            print(f"  Blueprint is now v{change.version}")
            if change.run:
                r = change.run
                print(f"  ran {len(r.completed)} nodes, "
                      f"{len(r.skipped)} skipped, {len(r.failed)} failed")
                # Naming them matters more than counting them: a skipped node
                # leaves the Blueprint holding whatever it held before, which
                # is indistinguishable from a node that ran and changed nothing.
                for node in r.skipped:
                    why = getattr(r, "skipped_because", {}).get(node, "")
                    print(f"    skipped: {node}" + (f" (unmet: {why})" if why else ""))
                for node in r.blocked:
                    print(f"    blocked: {node}")
                for node in r.failed:
                    why = getattr(r, "failed_because", {}).get(node, "")
                    print(f"    failed:  {node}" + (f" — {why}" if why else ""))

    if turn.trace:
        print("\n  --- traceability (§18) ---")
        for line in turn.trace.render().splitlines():
            print(f"  {line}")
        print(f"  verdict: {turn.trace.verdict}")


def show_trace(smith: Smith, requirement: str) -> None:
    trace = smith.trace(requirement)
    art = next(
        (r for r in smith.doc.get("requirements") or [] if r["id"] == requirement), None
    )
    if art:
        print(f"\n{requirement}: {art.get('description', '')}")
    print(trace.render())
    print(f"\nverdict: {trace.verdict}")
    for facet, detail in trace.facets.items():
        print(f"  {facet}: {'ok' if detail['ok'] else 'FAILED'}")
        for note in detail["notes"][:3]:
            print(f"      {note}")
    if trace.files:
        print("\nimplemented in:")
        for f in trace.files:
            print(f"  {f}")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def handle(smith: Smith, line: str, *, run_agents: bool) -> None:
    line = line.strip()
    if not line:
        return

    if line in ("status", "/status"):
        return show_status(smith)
    if line in ("ask", "/ask"):
        return show_questions(smith)
    if line.startswith(("trace ", "/trace ")):
        return show_trace(smith, line.split(None, 1)[1].strip().upper())
    if line.startswith(("explain ", "/explain ")):
        print("\n" + smith.explain(line.split(None, 1)[1].strip()))
        return

    # §69 — a preview selection carried inline: /page PAGE-009 /cmp CMP-033 …
    page = component = ""
    while line.startswith("/"):
        flag, _, rest = line.partition(" ")
        value, _, rest = rest.partition(" ")
        if flag in ("/page", "/p"):
            page = value.upper()
        elif flag in ("/cmp", "/component", "/c"):
            component = value.upper()
        else:
            break
        line = rest.strip()

    preview = None
    if page or component:
        preview = resolve_preview(smith.doc, page=page, component=component)
        print(f"  selection: {preview.describe()}")

    show_turn(smith, smith.turn(line, preview=preview, run_agents=run_agents))


def repl(smith: Smith, *, run_agents: bool) -> None:
    # §107 step 1, before anything is asked of the user. A returning session
    # opens on where the application actually is rather than on a prompt.
    show_greeting(smith)
    print("\nType a request, or: status | ask | trace REQ-017 | explain <q>")
    print("Lifecycle (§107): describe it, then \"draft the blueprint\", "
          "\"looks good\", \"build it\".")
    print("§69 preview selection: /page PAGE-009 /cmp CMP-033 make this compact")
    print("Ctrl-D to leave. Everything is saved as you go.\n")
    while True:
        try:
            line = input("you> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        try:
            handle(smith, line, run_agents=run_agents)
        except SystemExit:
            raise
        except Exception as exc:  # a bad turn should not end the conversation
            print(f"\n[error] {type(exc).__name__}: {exc}")


def main(argv: list[str] | None = None) -> int:
    # A run that takes half an hour and prints nothing is a run nobody can
    # review. Unbuffered so the report survives however the process ends.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:  # noqa: BLE001 - not worth failing a run over
        pass
    parser = argparse.ArgumentParser(
        prog="services.smith.cli", description="Talk to Smith about an application.",
    )
    parser.add_argument("--blueprint", type=Path, default=DEFAULT_BLUEPRINT,
                        help="Blueprint to adopt on first run.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT,
                        help="Working directory. Resumed if it already exists.")
    parser.add_argument("--model", default="claude-opus-5")
    parser.add_argument("--app-root", type=Path, default=None,
                        help="Where the generated application is written. "
                             "Defaults to <output-dir>/app, beside the "
                             "Blueprint it is projected from.")
    parser.add_argument("--new", default="", metavar="NAME",
                        help="Start an empty application instead of adopting a "
                             "Blueprint (§107 step 1).")
    parser.add_argument("--domain", default="",
                        help="Domain for --new: ATS, CRM, HRMS, … (§96).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the prompt that would be sent, then stop.")
    parser.add_argument("--fresh", action="store_true",
                        help="Discard the working directory and re-adopt.")
    parser.add_argument("--run-agents", action="store_true",
                        help="Execute the incremental DAG after a change (§72). "
                             "Off by default: a change costs one model call, a "
                             "regeneration costs a dozen.")
    parser.add_argument("say", nargs="*", help="One request, then exit.")
    args = parser.parse_args(argv)

    if not args.new and not args.blueprint.exists():
        parser.error(f"no Blueprint at {args.blueprint}")
    if args.fresh and args.output_dir.exists():
        shutil.rmtree(args.output_dir)

    # Every projection node blocks without somewhere to write, and a blocked
    # projection takes its dependents with it — an incremental change planned
    # eighteen nodes and silently ran a handful, because `integration` had
    # nowhere to project to and `testing`, `memory` and `verification` all hang
    # off it. Defaulting this beside the Blueprint means a change regenerates
    # the application by default rather than only the definition of it.
    app_root = str(args.app_root or (args.output_dir / "app"))

    model = _model(args.dry_run, args.model)
    executor = None
    if args.run_agents and not args.dry_run:
        from services.blueprint.executors import make_executor

        smith = _open(args.blueprint, args.output_dir, model=model,
                      new=args.new, domain=args.domain, app_root=app_root)
        smith.executor = make_executor(smith.blueprint, model)
    else:
        smith = _open(args.blueprint, args.output_dir, model=model,
                      executor=executor, new=args.new, domain=args.domain,
                      app_root=app_root)

    show_status(smith)

    if args.say:
        handle(smith, " ".join(args.say), run_agents=args.run_agents)
        return 0
    repl(smith, run_agents=args.run_agents)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
