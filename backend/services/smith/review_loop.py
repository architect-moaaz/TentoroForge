"""Smith's post-build review loop — the OUTER critique-and-developer loop.

Smith owns the application's lifecycle (define → build → settle). This is the
step after the build: look at the app as it actually rendered, decide what is
worth fixing, dispatch a re-compose to the pages that need it, rebuild, and look
again — bounded, and narrated, the way a lead runs a review→fix cycle.

The observer already closes the loop PER NODE inside a build (cheapest at the
node). This is the whole-app loop ACROSS builds, which needs the app rendered —
so it lives here, orchestrated by Smith, not inside the DAG.

Dependency-injected on purpose: the critique (screenshots + the vision critic),
the re-compose-and-rebuild, the document read and the narration are all passed
in, so the loop's control flow — bound, converge, degrade — is what this module
owns and what its tests pin. Every failure resolves to a clean stop, never a
broken build: an app that cannot be screenshotted is reviewed zero times and
ships as built.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from services.blueprint.visual_repair import repair_briefs_from_visual_qa

#: Rebuilds a review may spend before it stops and reports what is left. Two,
#: for the same reason the observer stops at two: the first fix carries the
#: brief, the second carries what the first still missed; a third on a page that
#: resisted two is a loop, not a repair.
DEFAULT_MAX_ROUNDS = 2


@dataclass
class ReviewOutcome:
    """What the review did, for the record and for what Smith tells the user."""
    #: Rebuilds spent (0 when the first look was already clean, or was skipped).
    rounds: int = 0
    #: Page ids re-composed at least once, in the order first flagged.
    recomposed: list[str] = field(default_factory=list)
    #: Page id -> the brief still open when the loop stopped (cap reached).
    remaining: dict[str, str] = field(default_factory=dict)
    #: Set when the loop could not run at all (no screenshots) — not a failure,
    #: a degradation: the build still shipped.
    skipped: str | None = None

    @property
    def converged(self) -> bool:
        return self.skipped is None and not self.remaining

    def summary(self) -> dict[str, Any]:
        return {"rounds": self.rounds, "recomposed": list(self.recomposed),
                "remaining": sorted(self.remaining), "skipped": self.skipped,
                "converged": self.converged}


def _narrate(briefs: Mapping[str, str], doc: Mapping[str, Any],
             round_no: int, max_rounds: int) -> str:
    """One line Smith says before a re-compose round — plain, page-named."""
    id_to_route = {str(p.get("id")): str(p.get("route") or p.get("id"))
                   for p in (doc.get("pages") or []) if isinstance(p, dict)}
    routes = ", ".join(sorted(id_to_route.get(pid, pid) for pid in briefs))
    n = len(briefs)
    page_word = "page" if n == 1 else "pages"
    return (f"I reviewed the built app and {n} {page_word} need work "
            f"({routes}). Re-composing "
            f"{'it' if n == 1 else 'them'} and rebuilding "
            f"(round {round_no} of {max_rounds}).")


def run_review_loop(
    *,
    read_doc: Callable[[], Mapping[str, Any]],
    critique: Callable[[], Mapping[str, Any] | None],
    recompose_and_rebuild: Callable[[dict[str, str]], None],
    emit: Callable[[str, dict], None] | None = None,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
) -> ReviewOutcome:
    """Run the review→fix→rebuild loop and return what it did.

    ``critique`` returns a visual-QA report (``{findings: [...]}``), or ``None``
    when the app could not be rendered/reviewed — in which case the loop stops
    cleanly having done nothing. ``recompose_and_rebuild`` takes ``{page_id:
    brief}`` and must re-compose exactly those pages against their briefs and
    rebuild the app; the next ``critique`` then sees the result.
    """
    outcome = ReviewOutcome()
    seen: set[str] = set()

    report = critique()                       # look at the app as first built
    while outcome.rounds < max_rounds:
        if report is None:
            outcome.skipped = "the app could not be rendered for review"
            return outcome
        briefs = repair_briefs_from_visual_qa(report, read_doc())
        if not briefs:
            return outcome                    # nothing worth fixing — done
        if emit is not None:
            emit("message", {"text": _narrate(briefs, read_doc(),
                                              outcome.rounds + 1, max_rounds)})
        for pid in briefs:
            if pid not in seen:
                seen.add(pid)
                outcome.recomposed.append(pid)
        recompose_and_rebuild(dict(briefs))
        outcome.rounds += 1
        report = critique()                   # re-review the rebuilt app

    # Cap reached: report what the last review still flags, if anything.
    if report is not None:
        outcome.remaining = dict(repair_briefs_from_visual_qa(report, read_doc()))
    return outcome


__all__ = ["run_review_loop", "ReviewOutcome", "DEFAULT_MAX_ROUNDS"]
