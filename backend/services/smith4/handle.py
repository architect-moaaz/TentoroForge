"""What a turn is about, before the loop runs — and what it carries after.

A change is often two turns: the ask, Smith's question, the answer. The turn
that acts must see both. `pending_ask` holds the ask between them; an agreed
plan is worked one step per turn; a yes to an import applies the mapping that
was shown. None of this is interpretation, and none of it belongs inside the
loop: it decides what the ask IS. Everything after that is the loop's.
"""
from __future__ import annotations

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
           attachments: list[dict] | None = None) -> Outcome:
    """One turn on a built application. `choose` decides each step; absent,
    `services.smith.loop.next_step` on the real model. `move` is the tree
    editor for layout pages; absent, `move_dispatcher`."""
    choose = choose or _default_choose(reasoning)
    if move is None:
        from services.smith.move_dispatcher import move_dispatcher
        move = move_dispatcher
    typed = (message or "").strip()

    def ctx_for(ask: str) -> Ctx:
        return Ctx(output_dir=str(output_dir), project_id=str(project_id), message=typed,
                   ask=ask, reasoning=reasoning, guards=guards or (lambda _o: []), move=move,
                   attachments=list(attachments or []))

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
            return result
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
    return result


def _default_choose(reasoning: Any) -> Callable:
    from services.smith.loop import next_step

    def choose(ask: str, page: str, observations: list, history: list) -> dict:
        return next_step(ask, page, observations, history, reasoning=reasoning)

    return choose


__all__ = ["handle"]
