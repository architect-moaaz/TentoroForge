"""V&F 2.0 M3 — cross-round Smith dispatch de-dup ledger.

Keeps an in-memory count of ``(interaction_id, class_name)`` pairs
Smith has been asked to fix within the current run. Callers instantiate
one ledger per verify run and hand it to
:func:`services.journey_verifier.smith_autofix.dispatch_all`. Faults
that hit the ledger's ``already_tried`` gate are surfaced as
``already-attempted-this-run`` residuals instead of being re-dispatched.

Not persisted across runs — a fresh verify session gets a fresh ledger.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from services.journey_verifier.fault_classifier import ClassifiedFault


@dataclass
class FaultAttemptLedger:
    """Tracks Smith dispatch attempts per (interaction_id, class_name).

    Simple defaultdict[tuple[str,str], int]. ``already_tried`` returns
    True once a pair's count reaches ``max_attempts`` (default 1);
    ``record_attempt`` bumps the count.
    """
    _attempts: dict[tuple[str, str], int] = field(
        default_factory=lambda: defaultdict(int),
    )

    def already_tried(
        self, fault: ClassifiedFault, max_attempts: int = 1,
    ) -> bool:
        """Return True when Smith has already spent ``max_attempts``
        attempts on this fault's (interaction_id, class_name) pair."""
        key = _key(fault)
        return self._attempts.get(key, 0) >= max_attempts

    def record_attempt(self, fault: ClassifiedFault) -> None:
        self._attempts[_key(fault)] += 1

    def attempt_count(self, fault: ClassifiedFault) -> int:
        return self._attempts.get(_key(fault), 0)


def _key(fault: ClassifiedFault) -> tuple[str, str]:
    return (fault.interaction_id or "?", fault.class_name or "?")
