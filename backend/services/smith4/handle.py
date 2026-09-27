"""What a turn is about, before the loop runs — and what it carries after.

A change is often two turns: the ask, Smith's question, the answer. The turn
that acts must see both. `pending_ask` holds the ask between them; an agreed
plan is worked one step per turn; a yes to an import applies the mapping that
was shown. None of this is interpretation, and none of it belongs inside the
loop: it decides what the ask IS. Everything after that is the loop's.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from services.smith import pending_ask
from services.smith import plan as plan_mod
from services.smith4.outcome import Outcome, from_seam
from services.smith4.turn import turn
from services.smith4.verbs import Ctx


def handle(*, project_id: str, output_dir: str, message: str,
           history: list | None = None,
           choose: Callable | None = None,
           move: Callable | None = None,
           guards: Callable | None = None,
           reasoning: Any = None,
           max_steps: int | None = None,
           attachments: list[dict] | None = None,
           evidence: list[str] | None = None,
           app_name: str = "") -> Outcome:
    """One turn on a built application. `choose` decides each step; absent,
    `services.smith.loop.next_step` on the real model. `move` is the tree
    editor for layout pages; absent, `move_dispatcher`."""
    choose = choose or _default_choose(reasoning, images=_image_paths(attachments))
    if move is None:
        from services.smith.move_dispatcher import move_dispatcher
        move = move_dispatcher
    typed = (message or "").strip()

    def ctx_for(ask: str) -> Ctx:
        return Ctx(output_dir=str(output_dir), project_id=str(project_id), message=typed,
                   ask=ask, reasoning=reasoning, guards=guards or (lambda _o: []), move=move,
                   attachments=list(attachments or []), history=list(history or []),
                   evidence=[str(e) for e in (evidence or []) if str(e).strip()],
                   app_name=str(app_name or ""))

    # AGREED TO ALL OF IT, SO DO ALL OF IT. "Do them in order" did the first
    # step and said "say next" — the person had just said the whole plan
    # (Test2, 2026-09-28: an Area record added, and the screen, the explorer
    # and the form left waiting on three more messages). Each step is a normal
    # turn; the run stops at the first that asks something or cannot be done,
    # and at a time budget, and says what is still to do either way.
    if plan_mod.peek(output_dir) and typed == plan_mod.ALL_LABEL:
        return _in_step(output_dir, _all_steps(output_dir, lambda step: turn(
            ctx_for(step), choose=choose, history=history, max_steps=max_steps)))
    # AGREED, SO DO THE FIRST ONE NOW.
    if plan_mod.peek(output_dir) and (plan_mod.wants_next(typed)
                                      or typed in (plan_mod.ALL_LABEL, plan_mod.FIRST_LABEL)):
        step = plan_mod.take_next(output_dir)
        if typed == plan_mod.FIRST_LABEL:
            plan_mod.clear(output_dir)
        if step:
            pending_ask.clear(output_dir)
            result = turn(ctx_for(step), choose=choose, history=history, max_steps=max_steps)
            note = plan_mod.remaining_note(plan_mod.peek(output_dir))
            if note and result.status == "resolved":
                result.said += note
            return _in_step(output_dir, result)
    # AGREED, SO LOAD THEM NOW — under the mapping that was shown.
    from services.smith import data_import
    if data_import.wants(data_import.peek(output_dir), typed):
        pending_ask.clear(output_dir)
        return from_seam(data_import.run(str(output_dir), message=typed, reasoning=reasoning),
                         ok="Loaded.", fail="I could not load that and nothing has been written.")
    if typed == plan_mod.REWORD_LABEL:
        plan_mod.clear(output_dir)
        return Outcome(status="asked", said="Go ahead — tell me the one thing you want first.")

    ask = pending_ask.joined(pending_ask.take(output_dir), typed)
    result = turn(ctx_for(ask), choose=choose, history=history, max_steps=max_steps)
    if result.status == "asked":
        pending_ask.remember(output_dir, ask)
    elif result.done:
        note = plan_mod.remaining_note(plan_mod.peek(output_dir))
        if note and note.strip() not in result.said:
            result.said += note
    return _in_step(output_dir, result)


def _in_step(output_dir: str, result: Outcome) -> Outcome:
    """A turn that changed the application leaves it in step with its
    definition — every generated file and the database schema.

    The Blueprint is what the application is; the files are what it was last
    written out as. A seam that re-projects less than it changed, a platform
    fix to a projection, a hand edit — each leaves the two apart, and Smith,
    reading the definition, cannot see what the person sees. Asked twice why
    Location Data listed no areas over twelve rows, it rewrote the page twice:
    the engine's list of records predated the record (Test2, 2026-09-28).
    Writing everything out after every change makes drift last one turn, not
    until somebody diagnoses it. Deterministic and quick; a failure here is
    logged and never costs the turn."""
    if not (result.done and result.touched):
        return result
    from pathlib import Path

    app_root = Path(output_dir) / "app"
    if not (app_root / "package.json").is_file():
        return result
    try:
        from services.blueprint.service import BlueprintService
        from services.smith.sync_app import sync
        out = sync(BlueprintService.load(output_dir=str(output_dir)), str(app_root))
        moved = out["changed"] + out["added"] + out["removed"]
        result.touched = list(dict.fromkeys([*result.touched, *moved]))
    except Exception:  # noqa: BLE001 — the change stands; the next turn catches up
        import logging
        logging.getLogger(__name__).exception("[smith] bringing %s in step failed", output_dir)
    return result


#: How long one "do them in order" may keep working before it stops between
#: steps and says what is left — inside the chat turn's own bound, so the
#: person hears from Smith rather than from the timeout.
PLAN_BUDGET_S = 480.0


def _all_steps(output_dir: str, run_step: Callable[[str], Outcome],
               budget_s: float = PLAN_BUDGET_S, clock: Callable[[], float] = time.monotonic) -> Outcome:
    """Every step of the agreed plan, in order, as one reply."""
    started = clock()
    said: list[str] = []
    touched: list[str] = []
    steps: list[str] = []
    last = Outcome(status="no_op")
    while True:
        step = plan_mod.take_next(output_dir)
        if not step:
            break
        pending_ask.clear(output_dir)
        last = run_step(step)
        if last.said.strip():
            said.append(last.said.strip())
        touched += [t for t in last.touched if t not in touched]
        steps += list(last.steps)
        if not last.done:
            if last.status == "asked":
                # Its answer continues the plan: the rest stays waiting.
                pending_ask.remember(output_dir, step)
            break
        if clock() - started > budget_s:
            break
    note = plan_mod.remaining_note(plan_mod.peek(output_dir))
    return Outcome(status=last.status, said="\n\n".join(said) + (note if last.done else ""),
                   options=list(last.options), touched=touched,
                   diff_summary=", ".join(touched[:8]) if touched else "", finding=last.finding,
                   steps=steps)


def _image_paths(attachments: list[dict] | None) -> list[str]:
    """The pictures attached to this turn, by path — what the person sees."""
    out = []
    for a in attachments or []:
        kind = str(a.get("mime") or a.get("content_type") or "")
        name = str(a.get("filename") or a.get("path") or "").lower()
        if (kind.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))) and a.get("path"):
            out.append(str(a["path"]))
    return out


def _default_choose(reasoning: Any, images: list[str] | None = None) -> Callable:
    from services.smith.loop import next_step

    def choose(ask: str, page: str, observations: list, history: list) -> dict:
        return next_step(ask, page, observations, history, reasoning=reasoning, images=images or [])

    return choose


__all__ = ["handle"]
