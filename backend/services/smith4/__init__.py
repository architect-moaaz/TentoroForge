"""Smith v4 — the loop is the front door.

`docs/superpowers/specs/2026-09-25-smithv4-front-door.md`.

Three Smiths came before this one. The legacy agent kept a loop and had no
write boundary; the Blueprint Smith kept the boundary and dropped the loop —
one interpretation call chose a verb, deterministic code did it, and the turn
ended. The loop was then bolted to the side of that dispatcher, and every
place the dispatcher ended a turn early had to be patched to let the loop
have a look: an answer from the slice, a clarification from the slice, a
finding from an oracle. Three patches on a shape that was wrong.

Here the first model call is the same call as every other. There is no
`understand_ask`, no verb classifier, no `limits.py`. The model is shown the
ask, the exchange, a first page of the application, and a catalogue — reads,
writes, the verbs as tools, and the ways a turn can end — and chooses. What
it chooses is carried out by the same seams the build uses, and what those
seams prove comes back as the next observation.

WHAT IS KEPT, AND WHY IT IS THE POINT. `apply_agent_result` and the capability
boundary; `ui_engineer` and the compiler; every `services.smith.*_change`
writer; `pending_ask`, `plan`, `confirm`, `revert`; `reads`, `writes`,
`tools`. These are the platform's seams, not the old front door, and they are
what Claude Code does not have — its safety is git, tests and a person
watching; Smith's is a contract, a compiler and an observer. The loop goes
around choosing and looking. It does not go around the boundary.
"""
from services.smith4.outcome import Outcome  # noqa: F401
from services.smith4.handle import handle  # noqa: F401
