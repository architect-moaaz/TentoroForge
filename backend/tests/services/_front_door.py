"""The old front door, for the tests that drove the seams through it.

Some two hundred tests exercise a seam — restyle, undo, remove a page — by
constructing a `SmithSession` with an injected `understand_ask_fn` that
returns the understanding the old classifier would have produced, and calling
`run_iteration`. The classifier is gone (Smith v4 chooses from step one) and
so is `run_iteration`; the seams are not, and neither is what those tests
assert about them.

This is the adapter: the same constructor, the same method, and inside it the
understanding becomes the first tool call of a v4 turn — the verb with its
fields, or `answer`, `ask_user`, `propose_plan` — followed by `done`. It lives
under `tests/` because production has no such thing: a caller of the platform
constructs no session and injects no understanding; it says what it wants and
the loop decides.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from services.smith_session import IterationMove, SmithSession as _Bootstrap, TurnResult  # noqa: F401
from services.smith4 import handle
from services.smith4.outcome import Outcome


def as_first_step(understanding: dict) -> dict:
    """What the old classifier decided, as the move a v4 chooser would make."""
    u = dict(understanding or {})
    answer = str(u.get("answer") or "").strip()
    if answer:
        return {"tool": "answer", "args": {"text": answer}, "why": ""}
    asks = [str(a).strip() for a in (u.get("asks") or []) if str(a).strip()]
    if len(asks) > 1:
        return {"tool": "propose_plan", "args": {"steps": asks}, "why": ""}
    question = str(u.get("clarification_needed") or "").strip()
    if question:
        options = [str(o).strip() for o in (u.get("clarification_options") or []) if str(o).strip()]
        return {"tool": "ask_user", "args": {"question": question, "options": options}, "why": ""}
    verb = str(u.get("verb") or "rename").strip().lower()
    args = {k: v for k, v in u.items()
            if k not in ("verb", "answer", "asks", "clarification_needed", "clarification_options")
            and v not in (None, "", [], {})}
    return {"tool": verb, "args": args, "why": ""}


def chooser_from(understand: Callable, *, reasoning: Any = None) -> Callable:
    """A chooser that makes the understanding's move until it has been carried
    out (or refused as a question sent to look, in which case it is made
    again), then ends the turn. The seam is handed the sink the session was
    given, as the old front door handed it."""
    def choose(ask: str, page: str, observations: list, history: list) -> dict:
        kwargs: dict = {"history": history}
        if reasoning is not None:
            kwargs["reasoning"] = reasoning
        try:
            u = understand(ask, page, **kwargs)
        except TypeError:
            u = understand(ask, page)
        first = as_first_step(u or {})
        made = [o for o in observations if o.tool == first["tool"] and o.status != "error"]
        if made:
            return {"tool": "done", "args": {}, "why": ""}
        # The old front door asked for a missing slot; the loop names that
        # question on the error it hands back, and this adapter asks it.
        # Once, and then kept up: the loop sends a first question to look
        # before it may stand, so the adapter asks again after that refusal.
        slot = next((o for o in observations if o.tool == first["tool"] and o.status == "error"
                     and " Ask: " in o.said), None)
        if slot is not None:
            return {"tool": "ask_user", "args": {"question": slot.said.split(" Ask: ", 1)[1].strip()}, "why": ""}
        return first
    return choose


@dataclass
class SmithSession:
    """Constructor-compatible with the old session; `run_iteration` is a v4 turn."""
    project_id: str
    output_dir: str
    discovery_fn: Any = None
    planner_fn: Any = None
    generator_fn: Any = None
    guards_fn: Optional[Callable] = None
    understand_ask_fn: Optional[Callable] = None
    iteration_move_fn: Optional[Callable] = None
    next_step_fn: Optional[Callable] = None
    reasoning_fn: Any = None
    _ask: str = field(default="", init=False)

    def run_bootstrap(self, user_message: str) -> TurnResult:
        return _Bootstrap(project_id=self.project_id, output_dir=self.output_dir,
                          discovery_fn=self.discovery_fn, planner_fn=self.planner_fn,
                          generator_fn=self.generator_fn, guards_fn=self.guards_fn,
                          reasoning_fn=self.reasoning_fn).run_bootstrap(user_message)

    def run_iteration(self, user_message: str,
                      history: list | None = None) -> TurnResult:
        choose = self.next_step_fn
        if choose is None:
            assert self.understand_ask_fn, "iteration requires understand_ask_fn or next_step_fn"
            choose = chooser_from(self.understand_ask_fn, reasoning=self.reasoning_fn)
        out: Outcome = handle(project_id=self.project_id, output_dir=str(self.output_dir),
                              message=user_message, history=history, choose=choose,
                              move=self.iteration_move_fn, guards=self.guards_fn,
                              reasoning=self.reasoning_fn)
        return TurnResult(status=out.status, answer=out.said, options=list(out.options),
                          diff_summary=out.diff_summary, touched_paths=list(out.touched),
                          finding=out.finding)


__all__ = ["SmithSession", "TurnResult", "IterationMove", "as_first_step", "chooser_from"]
