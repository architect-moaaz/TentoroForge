"""Structured result from the post-generate guard suite.

The guard suite (:func:`services.post_generate_fixes.apply_post_generate_fixes`)
runs ~20 guards over a generated app — every one logs its outcome, but
the runner returned nothing to callers. That's fine when the caller is
a human reading terminal output; it's useless when the caller is Smith's
orchestrator loop, which needs a machine-readable ``{green, failures}``
to decide "retry" vs "commit".

This module provides:

* :class:`GuardFailure` — one guard's problem, with enough shape to
  render into Smith's next-turn corrective prompt.
* :class:`GuardResult` — the whole-suite verdict.
* :func:`capture_guard_logs` — a context manager that hooks the
  services.* logger, captures every WARNING/ERROR record for the
  duration of a guard-suite run, and returns a `GuardResult`.

The parser is intentionally tolerant. Guards log free-form messages;
we don't try to classify every line into rich structure. What matters
is: it happened, which guard, what it said. Smith reads the corrective
prompt and decides what to do.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from typing import Any, Iterator


# --------------------------------------------------------------------------- #
# Data types
# --------------------------------------------------------------------------- #

@dataclass
class GuardFailure:
    """One guard's report. `guard` names WHERE, `message` names WHAT."""
    guard: str                              # e.g. "workflow_mutation_guard"
    kind: str                               # "warning" | "error"
    message: str                            # human-readable
    artifact: str | None = None             # optional file path if the guard scoped one
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GuardResult:
    """Whole-suite verdict. ``green`` iff no failures were captured.

    ``raw_lines`` keeps the un-parsed log records (level + name +
    message) for provenance — orchestrator callers may want them for
    debug logs, tests may want them for assertions."""
    green: bool
    failures: list[GuardFailure]
    raw_lines: list[dict[str, Any]] = field(default_factory=list)
    #: Workflow content the guard pass REWROTE, keyed by workflow file.
    #:
    #: S22-2: the suite reported only what guards happened to log. A guard
    #: that quietly rewrote authored workflow content — the case that matters,
    #: because Smith is pushed to run this pass right after an edit — surfaced
    #: nothing, and a silent rewrite is indistinguishable to the user from
    #: their edit never having been saved.
    #:
    #: Filled by diffing the workflow JSON before and after the run rather
    #: than by asking each guard to remember to log, so a guard added later
    #: is covered without touching it.
    rewrites: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    @classmethod
    def from_log_records(cls, records: list[dict[str, Any]]) -> "GuardResult":
        """Build from a list of ``{name, level, message}`` records.

        Only WARNING and ERROR level entries become failures. INFO is
        preserved in ``raw_lines`` but does not affect the green verdict —
        a guard that ran + succeeded is not a failure."""
        failures: list[GuardFailure] = []
        for r in records:
            lvl = str(r.get("level", "info")).lower()
            if lvl not in {"warning", "error"}:
                continue
            failures.append(GuardFailure(
                guard=_extract_guard_name(r),
                kind=lvl,
                message=str(r.get("message", "")).strip(),
                artifact=r.get("artifact"),
                evidence=r.get("evidence", {}) if isinstance(r.get("evidence"), dict) else {},
            ))
        return cls(green=len(failures) == 0, failures=failures, raw_lines=list(records))

    def to_prompt(self) -> str:
        """Render for Smith's next-turn corrective context."""
        if self.green:
            return "GUARD SUITE: all green — every guard passed."
        head = (f"GUARD SUITE: {len(self.failures)} failure(s) — you must fix "
                f"EACH one before answering:")
        lines = [head]
        for i, f in enumerate(self.failures, 1):
            loc = f" in {f.artifact}" if f.artifact else ""
            lines.append(f"  {i}. [{f.guard}]{loc}: {f.message}")
        lines.append("")
        lines.append("Read impact_analysis output + the failure message + "
                     "the specialist seams catalog. Route each failure to "
                     "the correct specialist and re-run guards. Do not "
                     "answer until this list is empty.")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "green": self.green,
            "failures": [f.to_dict() for f in self.failures],
            "raw_lines_count": len(self.raw_lines),
        }

    def diff_against(self, baseline: "GuardResult | None") -> "GuardResult":
        """Return a new GuardResult carrying only failures NOT present in
        ``baseline``. Used by the orchestrator so pre-existing app-level
        warnings do not force Smith into an unwinnable retry loop —
        Smith is only responsible for regressions introduced this turn.

        Failures are matched by ``(guard, message)`` with digit runs
        normalized out of the message: several guards embed volatile
        counts ("24 workflow(s) still orphaned") that drift between
        runs because the suite itself repairs as it checks, and an
        exact-text match would resurrect every pre-existing failure
        as "new" on each turn. Passing ``None`` or
        an empty baseline is a no-op (returns ``self`` unchanged)."""
        if baseline is None or not baseline.failures:
            return self
        import re as _re

        def _nums(msg: str) -> list[int]:
            return [int(x) for x in _re.findall(r"\d+", msg)]

        baseline_map: dict[tuple[str, str], list[list[int]]] = {}
        for bf in baseline.failures:
            baseline_map.setdefault(_failure_key(bf), []).append(_nums(bf.message))

        def _pre_existing(f: "GuardFailure") -> bool:
            cands = baseline_map.get(_failure_key(f))
            if cands is None:
                return False
            f_nums = _nums(f.message)
            # Same shape + no count grew ⇒ the failure existed before
            # (counts only drifted down as the suite repaired). A count
            # that INCREASED means Smith made it worse — surface it.
            return any(
                len(b) == len(f_nums)
                and all(fv <= bv for fv, bv in zip(f_nums, b))
                for b in cands
            )

        delta = [f for f in self.failures if not _pre_existing(f)]
        return GuardResult(
            green=len(delta) == 0,
            failures=delta,
            raw_lines=self.raw_lines,
        )


def _failure_key(f: "GuardFailure") -> tuple[str, str]:
    """Stable identity for baseline diffing: guard name + message with
    digit runs collapsed, so run-to-run count drift doesn't defeat the
    pre-existing-failure filter."""
    import re
    return (f.guard, re.sub(r"\d+", "#", f.message))


# --------------------------------------------------------------------------- #
# Log capture context manager
# --------------------------------------------------------------------------- #

@contextmanager
def capture_guard_logs(
    *,
    logger_prefix: str = "services.",
    min_level: int = logging.WARNING,
) -> Iterator[list[dict[str, Any]]]:
    """Hook the root logger for the duration of the block; every
    LogRecord whose name starts with ``logger_prefix`` and whose level
    is ``>= min_level`` is captured into the yielded list as
    ``{name, level, message}``.

    Restores the original handler set on exit — the capture is
    strictly scoped to the ``with`` block."""
    captured: list[dict[str, Any]] = []

    class _Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
            if not record.name.startswith(logger_prefix):
                return
            if record.levelno < min_level:
                return
            captured.append({
                "name": record.name,
                "level": record.levelname.lower(),
                "message": record.getMessage(),
            })

    handler = _Handler(level=min_level)
    root = logging.getLogger()
    prev_level = root.level
    if prev_level > min_level:
        root.setLevel(min_level)
    root.addHandler(handler)
    try:
        yield captured
    finally:
        root.removeHandler(handler)
        root.setLevel(prev_level)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _extract_guard_name(record: dict[str, Any]) -> str:
    """Derive a short guard identifier from the logger name.

    Records come in as e.g. ``services.post_generate_fixes`` — but the
    guards emit messages tagged with their own name in a bracketed prefix
    (``"workflow_mutation_guard: ..."``) or by simply calling
    ``logger.warning(...)`` from their function. The cheap heuristic:
    take the last dot segment of the logger name; if the message starts
    with an identifier followed by ``:``, prefer that."""
    msg = str(record.get("message") or "")
    # "workflow_mutation_guard: 11 mutation values still need ..."
    if ":" in msg[:64]:
        head = msg.split(":", 1)[0].strip()
        if head and " " not in head and len(head) <= 64:
            return head
    name = record.get("name") or ""
    if "." in name:
        return name.rsplit(".", 1)[-1]
    return name or "unknown"
