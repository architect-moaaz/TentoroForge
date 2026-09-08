"""The run's progress, read off the ledger rather than counted beside it.

The Smith panel's stream wrapped the executor and counted its calls: a node
was "done" the first time any call for it returned, so a fan-out over fifteen
pages ticked complete at its first page; the nodes that are services rather
than agent calls (`apis`, `figma_design_system`, `verification`) never passed
through the wrapper, so they never ticked and the count could not reach the
total; and the registry a reloaded page reads added one per call, so a run
that was 12 of 19 reported 23 of 19 and a percentage past a hundred.

The orchestrator already keeps the one true account — the run ledger — and
hands every line to an ``observer`` as it is written. The virtual office reads
that; so does this. One reader per audience, one source.

EVENTS EMITTED, the panel's vocabulary:

- ``node:start``   {node, subjects}
- ``node:subject`` {node, subject, index, total, ok, nodesDone, nodesTotal, callsDone}
- ``node:done``    {node, nodesDone, nodesTotal, callsDone}
- ``node:retry`` / ``node:failed`` / ``node:blocked`` / ``node:skipped``
  are forwarded as the ledger wrote them.

The ledger's own ``plan`` line is not forwarded: the router emits the plan
itself, because only it knows whether the run stops at the approval gate.
"""
from __future__ import annotations

import threading
from typing import Any, Callable

#: Ledger events passed through untouched, for the activity list.
_FORWARDED = ("node:retry", "node:failed", "node:blocked", "node:skipped")


class Progress:
    """Translate ledger lines into stream events and keep the counts.

    Called from the orchestrator's worker threads — a wave of independent
    nodes has several in flight — so the account is updated under a lock and
    every event carries the counts as they were at that moment.
    """

    def __init__(self, emit: Callable[[str, dict[str, Any]], None],
                 *, total: int) -> None:
        self._emit = emit
        self._total = total
        self._lock = threading.Lock()
        self.nodes_done = 0
        self.calls_done = 0
        #: node key -> how many subject lines it has produced.
        self._subjects_seen: dict[str, int] = {}

    def __call__(self, line: dict[str, Any]) -> None:
        event = str(line.get("event") or "")
        node = str(line.get("node") or "")

        if event == "node:start":
            self._emit("node:start", {"node": node,
                                      "subjects": int(line.get("subjects") or 1)})
            return

        if event == "node:subject":
            with self._lock:
                self.calls_done += 1
                self._subjects_seen[node] = self._subjects_seen.get(node, 0) + 1
                counts = self._counts()
            self._emit("node:subject", {
                "node": node, "subject": line.get("subject"),
                "index": line.get("index"), "total": line.get("total"),
                "ok": bool(line.get("ok")), **counts})
            return

        if event == "node:done":
            with self._lock:
                self.nodes_done += 1
                # A node that fanned out already counted a call per subject;
                # a plain node's one call is its completion.
                if not self._subjects_seen.get(node):
                    self.calls_done += 1
                counts = self._counts()
            self._emit("node:done", {"node": node, **counts})
            return

        if event in _FORWARDED:
            self._emit(event, {k: v for k, v in line.items() if k != "at"})

    def _counts(self) -> dict[str, int]:
        return {"nodesDone": self.nodes_done, "nodesTotal": self._total,
                "callsDone": self.calls_done}
