"""What went wrong in the running application, on disk, beside the run ledger.

An owner is the only telemetry this platform has. They can say "it crashed"
and "it's really slow", and until now both sentences reached nothing: no
signal left the running app that Smith could read, so the answer to the two
most common complaints a business owner types was a paraphrase of the
complaint.

`services.blueprint.run_ledger` records what a BUILD did, one JSON object per
line under ``.forge/runs``. This is the same account for what the built
application does afterwards, one file, append-only, beside it:

    <output_dir>/.forge/incidents.jsonl

ONE FILE, NOT A TABLE. There is a ``runtime_exceptions`` table and it stays —
the self-heal loop dedups and counts on it. But a table answers "how many
open", and the question here is "what happened to me on Tuesday", asked of a
project by a person holding a project directory. A run ledger is readable with
`cat` on a host with no database, and so is this.

WHAT IS IN A RECORD, AND WHAT IS DELIBERATELY NOT
=================================================
A crash payload can carry a customer's data — an order, a diagnosis, a name —
and that data belongs to the owner of the application, not to the platform
that generated it. Two rules, both structural. Neither is a filter that
inspects content and decides, because a filter is a list of exceptions waiting
to be wrong.

1. VALUES NEVER LEAVE THE APPLICATION. A record carries the NAMES of the
   things involved — the route pattern, the control's label, the workflow, the
   step, the KEYS of the payload a control sent — and never their values.
   Nothing on the reporting path reads a value: see
   ``templates/runtime/error_reporter.ts``, where the payload is reduced to
   ``Object.keys`` at the call site and the object itself is never carried.

2. THE ROUTE IS A PATTERN, NOT A URL. ``/cases/8f2a…`` is a record id and
   ``?q=jane@…`` is a customer. The reporter matches the browser's path
   against the routes the application itself declares and sends the pattern it
   matched — ``/cases/[id]`` — or nothing. A path that matches no declared
   route is not sent at all.

The one thing that cannot be made structural is the exception MESSAGE, because
a database driver writes the offending value into its own text
(``duplicate key … (email)=(…)``) and no rule about our code can stop it. It
is carried, because without it a crash is unactionable — and it is the whole
reason for rule three:

3. IT LANDS IN ONE PLACE. The project's own directory, deleted with the
   project, never aggregated across owners.

MESSAGE SHAPE
=============
`services.blueprint.assembly.verify_dispatches` dry-runs every control through
the app's own engine at build time and fails naming the control, the workflow
and the step::

    /cases: Table.rowActions[0] 'Approve' runs approve-case — step 'notify'
    (send_email): recipient is empty

That is the same information, at build time, that this records at run time —
so :func:`describe` writes it the same way. An owner who saw that sentence
when the app was built sees the sentence in the same shape when it breaks in
front of a customer.
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator

#: Beside `.forge/runs`, not inside it: a run ledger is one file per run and
#: this is one file for the life of the application.
LEDGER_RELATIVE = Path(".forge") / "incidents.jsonl"

#: The two kinds. `crash` is an exception that reached a person; `slow` is a
#: server handler that took longer than the application was told to expect.
KIND_CRASH = "crash"
KIND_SLOW = "slow"
KINDS = (KIND_CRASH, KIND_SLOW)

#: Fields a record may carry, and nothing else. An unknown key is dropped
#: rather than written: the reporter is code we ship, so a key we do not know
#: is a caller we did not write, and the safe reading of that is that it is
#: carrying something we promised not to keep.
CRASH_FIELDS = (
    "kind", "at", "where", "route", "control", "label", "actionType",
    "workflow", "step", "message", "errorName", "stack", "payloadKeys",
    "role", "occurrences",
)
SLOW_FIELDS = (
    "kind", "at", "where", "route", "control", "label", "workflow",
    "operation", "entity", "ms", "thresholdMs", "role",
)

#: How many lines a reader will take off the end. A ledger is append-only and
#: never rotated — the question is always "lately", and the answer stops being
#: useful long before this.
READ_LIMIT = 2000


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def path_for(output_dir: str | Path) -> Path:
    return Path(output_dir) / LEDGER_RELATIVE


def _clean(record: dict[str, Any], allowed: tuple[str, ...]) -> dict[str, Any]:
    """The record reduced to the fields this kind declares, in that order."""
    out: dict[str, Any] = {}
    for key in allowed:
        value = record.get(key)
        if value is None or value == "" or value == []:
            continue
        out[key] = value
    return out


def record(output_dir: str | Path, incident: dict[str, Any]) -> dict[str, Any] | None:
    """Append one incident. Returns what was written, or None if it was not.

    Best-effort in the same sense as the run ledger: an account of a failure
    that can itself fail the thing it is describing is worse than no account.
    Every write is swallowed. The one thing that is NOT swallowed is the
    field reduction — a record with an unexpected key is written without it,
    never with it.
    """
    kind = str(incident.get("kind") or "").strip().lower()
    if kind not in KINDS:
        return None
    allowed = CRASH_FIELDS if kind == KIND_CRASH else SLOW_FIELDS
    line = _clean({**incident, "kind": kind, "at": incident.get("at") or _now()}, allowed)
    target = path_for(output_dir)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    except Exception:  # noqa: BLE001 — never break the app being described
        return None
    return line


def read(output_dir: str | Path, *, kind: str = "", limit: int = READ_LIMIT) -> list[dict]:
    """The ledger, newest last. A truncated final line is skipped in silence —
    it means the process died mid-write, which the line before it already
    says better."""
    target = path_for(output_dir)
    out: list[dict] = []
    try:
        with target.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return []
    for raw in lines[-limit:]:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        if kind and obj.get("kind") != kind:
            continue
        out.append(obj)
    return out


def _crash_key(inc: dict) -> tuple:
    """What makes two crashes the same crash.

    The locators, and the first line of the message — never the stack, which
    carries a request id on some drivers and would split one crash into every
    time it happened. Same rule as `routers.runtime_exceptions._compute_dedup_key`,
    stated here because this side has no database to agree with.
    """
    return (
        str(inc.get("where") or ""),
        str(inc.get("route") or ""),
        str(inc.get("workflow") or ""),
        str(inc.get("step") or ""),
        str(inc.get("message") or "").split("\n")[0][:200],
    )


class Crash(dict):
    """One distinct crash and every time it was seen."""

    @property
    def count(self) -> int:
        return int(self.get("count") or 0)


def crashes(output_dir: str | Path) -> list[Crash]:
    """Distinct crashes, most recently seen first, each with how often.

    Repeats are collapsed because an owner saying "it crashed" is asking what
    broke, not for a list of four hundred identical lines.
    """
    grouped: dict[tuple, Crash] = {}
    for inc in read(output_dir, kind=KIND_CRASH):
        key = _crash_key(inc)
        seen = int(inc.get("occurrences") or 1)
        found = grouped.get(key)
        if found is None:
            grouped[key] = Crash({**inc, "count": seen,
                                  "firstSeen": inc.get("at"), "lastSeen": inc.get("at")})
            continue
        found["count"] = found.count + seen
        found["lastSeen"] = inc.get("at") or found.get("lastSeen")
        # Keep the fullest locator seen: the same crash reported from the
        # browser has no workflow, the same one from the server has no route.
        for field in ("route", "control", "label", "workflow", "step", "stack", "payloadKeys"):
            if not found.get(field) and inc.get(field):
                found[field] = inc[field]
    return sorted(grouped.values(), key=lambda c: str(c.get("lastSeen") or ""), reverse=True)


def _slow_key(inc: dict) -> tuple:
    return (str(inc.get("workflow") or ""), str(inc.get("operation") or ""),
            str(inc.get("entity") or ""), str(inc.get("route") or ""))


def slow(output_dir: str | Path) -> list[dict]:
    """Slow responses, grouped by what was being done, slowest average first.

    Every observation over the threshold is one line — repeats ARE the data
    here, in a way they are not for a crash, so nothing is collapsed on the
    way in and the averages below are over real observations.
    """
    times: dict[tuple, list[int]] = defaultdict(list)
    meta: dict[tuple, dict] = {}
    for inc in read(output_dir, kind=KIND_SLOW):
        try:
            ms = int(inc.get("ms"))
        except (TypeError, ValueError):
            continue
        key = _slow_key(inc)
        times[key].append(ms)
        held = meta.setdefault(key, {})
        for field in ("workflow", "operation", "entity", "route", "control",
                      "label", "thresholdMs"):
            if not held.get(field) and inc.get(field):
                held[field] = inc[field]
        held["lastSeen"] = inc.get("at") or held.get("lastSeen")
        held.setdefault("firstSeen", inc.get("at"))
    out = []
    for key, observed in times.items():
        out.append({**meta[key], "count": len(observed),
                    "worstMs": max(observed),
                    "averageMs": int(sum(observed) / len(observed))})
    return sorted(out, key=lambda s: (-int(s.get("averageMs") or 0), str(s.get("operation") or "")))


def describe(crash: dict) -> str:
    """One crash in the shape `verify_dispatches` writes a build failure.

    The build-time sentence names the route, the control, the workflow and the
    step; so does this one, for the same reason — it is the sentence that lets
    somebody go and look at the right thing.
    """
    where = str(crash.get("route") or crash.get("where") or "the application")
    head = where
    control = str(crash.get("control") or "")
    label = str(crash.get("label") or "")
    if control:
        head += f": {control}" + (f" {label!r}" if label else "")
    elif label:
        head += f": {label!r}"
    workflow = str(crash.get("workflow") or "")
    if workflow:
        head += f" runs {workflow}"
        step = str(crash.get("step") or "")
        if step:
            action = str(crash.get("actionType") or "")
            head += f" — step {step!r}" + (f" ({action})" if action else "")
    message = " ".join(str(crash.get("message") or "").split())[:300]
    return f"{head}: {message}" if message else head


def stack_frames(crash: dict, limit: int = 3) -> list[str]:
    """The first frames of the stack that name the application's own files.

    A stack is mostly framework. The frames worth showing are the ones under
    `src/`, because those are the ones a change could move.
    """
    out: list[str] = []
    for line in str(crash.get("stack") or "").splitlines():
        line = line.strip()
        if "src/" not in line and "/src" not in line:
            continue
        out.append(line)
        if len(out) >= limit:
            break
    return out


def iter_records(output_dir: str | Path) -> Iterator[dict]:
    yield from read(output_dir)


__all__ = ["LEDGER_RELATIVE", "KIND_CRASH", "KIND_SLOW", "KINDS",
           "CRASH_FIELDS", "SLOW_FIELDS", "path_for", "record", "read",
           "crashes", "slow", "describe", "stack_frames", "iter_records"]
