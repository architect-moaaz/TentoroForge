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
    #: Pages a re-compose REFUSED (the composer could not produce a tree the
    #: contract accepts) — ``{page_id: reason}``. Not retried: a second round
    #: against the same brief is the same refusal, so the loop reports why
    #: instead of spending it. A refused page is not "remaining" — remaining
    #: is what the last review still saw; refused is what could not be redone.
    refused: dict[str, str] = field(default_factory=dict)
    #: Pages the observer flagged UNREPAIRED in a round — a tree landed, the
    #: observer spent its repairs, a requirement still fails. Not sent round
    #: again either: DC5's /master-data cost a seven-minute second round to
    #: reach the verdict the first round had already reached.
    unrepaired: dict[str, str] = field(default_factory=dict)
    #: Set when the loop could not run at all (no screenshots) — not a failure,
    #: a degradation: the build still shipped.
    skipped: str | None = None

    @property
    def converged(self) -> bool:
        return (self.skipped is None and not self.remaining
                and not self.refused and not self.unrepaired)

    def summary(self) -> dict[str, Any]:
        return {"rounds": self.rounds, "recomposed": list(self.recomposed),
                "remaining": sorted(self.remaining), "refused": sorted(self.refused),
                "unrepaired": sorted(self.unrepaired), "skipped": self.skipped,
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
    recompose_and_rebuild: Callable[[dict[str, str]], Any],
    emit: Callable[[str, dict], None] | None = None,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    settle: Callable[[set[str] | None], Mapping[str, str]] | None = None,
) -> ReviewOutcome:
    """Run the review→fix→rebuild loop and return what it did.

    ``critique`` returns a visual-QA report (``{findings: [...]}``), or ``None``
    when the app could not be rendered/reviewed — in which case the loop stops
    cleanly having done nothing. ``recompose_and_rebuild`` takes ``{page_id:
    brief}`` and must re-compose exactly those pages against their briefs and
    rebuild the app; the next ``critique`` then sees the result. It may return
    ``{page_id: reason}`` for pages whose re-compose was REFUSED, or a
    ``review_wiring.Rebuilt`` carrying both the refused and the pages the
    observer flagged UNREPAIRED — none of those are sent round again (see
    ``ReviewOutcome.refused`` / ``.unrepaired``).

    ``settle`` is what the review fixes in the Blueprint itself before any page
    is re-composed — a page's declared action with no workflow to run — and
    returns ``{page_id: note}`` for the pages that must now be re-composed
    because of it, whether or not the critique flagged them. Called once, on
    the first round: what it settles stays settled.
    """
    outcome = ReviewOutcome()
    seen: set[str] = set()

    report = critique()                       # look at the app as first built
    # THE BLUEPRINT'S OWN GAPS COME FIRST. A page whose Delete has no delete
    # workflow cannot be composed right however many times the composer tries;
    # the review declares the workflow, then re-composes the page against it.
    # Settled on the first round only, and even when the app could not be
    # screenshotted — a gap in the Blueprint needs no screenshot to see.
    settled: dict[str, str] = dict(settle(None) or {}) if settle is not None else {}
    while outcome.rounds < max_rounds:
        if report is None and not settled:
            # Nothing to look at. Before any round that is a review that could
            # not happen; after one it is a rebuild that could not be checked
            # — said differently, because one did nothing and one did work.
            outcome.skipped = ("the app could not be rendered for review"
                               if outcome.rounds == 0 else
                               "the rebuilt app could not be rendered to check it")
            return outcome
        briefs = dict(repair_briefs_from_visual_qa(report, read_doc())) if report else {}
        for pid, note in settled.items():
            briefs[pid] = f"{briefs[pid]}\n\n{note}" if briefs.get(pid) else note
        settled = {}
        for pid in (*outcome.refused, *outcome.unrepaired):
            briefs.pop(pid, None)             # refused once is refused; say so, don't spin
        if not briefs:
            break                             # nothing worth fixing — done
        if emit is not None:
            emit("message", {"text": _narrate(briefs, read_doc(),
                                              outcome.rounds + 1, max_rounds)})
        for pid in briefs:
            if pid not in seen:
                seen.add(pid)
                outcome.recomposed.append(pid)
        rebuilt = recompose_and_rebuild(dict(briefs))
        refused = getattr(rebuilt, "refused", None)
        if refused is None:
            refused = rebuilt or {}
        outcome.refused.update({str(k): str(v) for k, v in refused.items()})
        outcome.unrepaired.update({str(k): str(v) for k, v in
                                   (getattr(rebuilt, "unrepaired", None) or {}).items()})
        outcome.rounds += 1
        report = critique()                   # re-review the rebuilt app

    # Done or capped: report what the last review still flags, if anything —
    # a refused page is reported as refused, not as still-flagged.
    if report is not None:
        outcome.remaining = {
            pid: brief for pid, brief in repair_briefs_from_visual_qa(report, read_doc()).items()
            if pid not in outcome.refused and pid not in outcome.unrepaired}
    return outcome


__all__ = ["run_review_loop", "ReviewOutcome", "DEFAULT_MAX_ROUNDS"]
