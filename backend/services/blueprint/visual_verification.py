"""Does the built page look like the application it came from — §73–§76.

:mod:`services.blueprint.verification` walks the §75 matrix over the Blueprint
and reads every edge off the document. That is the right scope for it and it
says so: ``UNVERIFIED_HERE`` states plainly that nothing here exercises what
was actually rendered. So a page can satisfy all fourteen edges — every widget
bound, every action backed by an endpoint, every permission declared — and
still come back as a grey wall of default components that looks nothing like
the design language the Blueprint spent a node establishing. Nothing in the
substrate was looking.

``services.vision_evaluator`` was already looking, and had been all along. It
takes a screenshot and an accessibility tree and returns a critique scored on
five axes. What it was not doing was talking to the Blueprint: it lived in the
legacy pipeline, and its output went into a repair chain.

What this module refuses to carry over
--------------------------------------
``Issue.patchOp`` — a JSON-patch operation the critique proposes applying to
the page. It is dropped here, deliberately and by name.

That field is the legacy pipeline in miniature: look at the result, compute a
patch, apply it, look again. §76 says out-of-sync artifacts must be *flagged*,
and the whole architecture is the claim that a divergence the platform quietly
fixes is a divergence nobody ever designs away — which is how 151 sequential
repair passes happen. A critique that edits the page it is judging is not a
verification, it is a second author with no §30 boundary.

So a critique becomes findings, and findings become ``OUT_OF_SYNC`` on a named
artifact plus a §74 repair task addressed to the agent that owns it. The agent
that owns ``pageLayouts`` composes the page again, knowing what was wrong with
the last one. Nothing here writes a layout.

Whose verdict decides
---------------------
The model's. ``Critique.pass_`` is what marks a page out of sync, rather than a
severity threshold chosen here. A cutoff — "high issues fail, medium do not" —
would be exactly the kind of local rule that accumulates exceptions until
nobody can say what the platform considers acceptable. Every issue is reported
whatever its severity; the pass verdict is a single judgement, made in one
place, by the thing that actually looked at the page.

Why this is not a DAG node
--------------------------
It needs a screenshot, and §28's graph has no way to produce one. Service
handlers receive a :class:`BlueprintService` and projections an ``app_root``;
capturing a rendered page needs the preview runtime running and a browser
driving it, which is the harness layer's job and arrives at §107 step 21 —
*after* the verification node at step 20. So the caller supplies the shots and
Smith invokes this against the preview it already has. §94 needs no new state:
a visual finding against a previewed application is PREVIEW → ITERATION →
IMPLEMENTATION, which is §114 maintenance and already legal.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from services.blueprint.service import BlueprintService
from services.blueprint.verification import Finding, VerificationReport

#: The relationship this module checks, named in §75's own style. Kept out of
#: ``verification.EDGES`` on purpose: everything in that tuple is checked by a
#: pure function of the document, and ``verify()`` would try to call this one
#: the same way and have no screenshot to give it.
EDGE = "Design↔Rendered"

#: The section a rendered page belongs to, and therefore — through
#: ``SECTION_OWNER`` — the agent a §74 repair task is addressed to. A page that
#: looks wrong is composed wrong, and ``pageLayouts`` is what composition
#: writes.
SECTION = "pageLayouts"


@dataclass(frozen=True)
class Shot:
    """One rendered page, as the critic needs to see it."""

    page_id: str
    route: str
    png: bytes
    a11y_tree: str = ""


#: What a critic must be: a shot in, a `vision_evaluator.Critique` out.
#: Injected rather than imported, for the same reason ``run`` takes an
#: ``executor``: this module then has no opinion about which model is used, no
#: network in its tests, and no dependency on the legacy package's async entry
#: point.
Critic = Callable[[Shot], Any]


def _issue_detail(issue: Any) -> str:
    """One issue as a sentence a person and an agent can both act on.

    Severity is carried in the text rather than in a field because
    :class:`Finding` has none, and adding one would widen a type the whole
    §75 matrix shares in order to describe a single edge.
    """
    severity = getattr(issue, "severity", "") or "?"
    axis = getattr(issue, "axis", "") or "?"
    what = (getattr(issue, "issue", "") or "").strip()
    fix = (getattr(issue, "suggestion", "") or "").strip()
    return f"{severity} / {axis}: {what}" + (f" — {fix}" if fix else "")


def findings_for(shot: Shot, critique: Any) -> list[Finding]:
    """A critique as §76 findings against one page.

    ``patchOp`` is not read. See the module docstring: the critique says what
    is wrong, and the agent that owns the artifact decides what to do about it.
    """
    return [
        Finding(edge=EDGE, detail=_issue_detail(issue),
                artifact_id=shot.page_id, section=SECTION)
        for issue in (getattr(critique, "topIssues", None) or [])
    ]


def verify_rendered(
    shots: Iterable[Shot], critic: Critic,
) -> tuple[VerificationReport, dict[str, bool]]:
    """Critique each shot. Returns the report and each page's pass verdict.

    The verdicts come back beside the report rather than inside it because
    :class:`VerificationReport` describes findings, and "this page passed with
    three low-severity notes" is not a finding — it is the answer to a
    different question, and folding it in would make ``passed`` mean two
    things.

    A critic that raises takes its own page down and nothing else. On a
    thirty-page application one unreachable render must not cost the other
    twenty-nine their critique — the same per-subject tolerance the page
    fan-out has.
    """
    findings: list[Finding] = []
    verdicts: dict[str, bool] = {}

    for shot in shots:
        try:
            critique = critic(shot)
        except Exception as exc:  # noqa: BLE001 — one page, never the pass
            findings.append(Finding(
                edge=EDGE,
                detail=f"could not be critiqued: {exc}",
                artifact_id=shot.page_id, section=SECTION,
            ))
            continue
        findings.extend(findings_for(shot, critique))
        verdicts[shot.page_id] = bool(
            getattr(critique, "pass_", getattr(critique, "pass", False))
        )

    return VerificationReport(findings=findings, checked_edges=(EDGE,)), verdicts


def apply_visual_findings(
    svc: BlueprintService,
    report: VerificationReport,
    verdicts: dict[str, bool],
) -> list[str]:
    """§76 — flag the pages the critic failed. Repairs nothing.

    Only the failed ones. ``verification.apply_findings`` marks every artifact
    a finding names, which is right for the structural matrix — an edge either
    holds or it does not. A critique is not like that: a page can pass and
    still carry three notes worth reading, and flagging it OUT_OF_SYNC for
    them would make the status mean "somebody had an opinion" rather than
    "this disagrees with the Blueprint".
    """
    from services.blueprint.agent_contract import capability_for

    cap = capability_for("verification")
    assert cap.may_set_status and not cap.writes, (
        "the verification agent must be able to flag and nothing else"
    )

    failed = {pid for pid, ok in verdicts.items() if not ok}
    grouped: dict[str, list[Finding]] = {}
    for f in report.findings:
        # A page that could not be critiqued at all has no verdict, and that is
        # a divergence in itself: the Blueprint says there is a page and
        # nothing could be rendered from it.
        if f.artifact_id and (f.artifact_id in failed
                              or f.artifact_id not in verdicts):
            grouped.setdefault(f.artifact_id, []).append(f)

    marked: list[str] = []
    for artifact_id, items in grouped.items():
        try:
            svc.mark_out_of_sync(
                artifact_id, "; ".join(f"{i.edge}: {i.detail}" for i in items))
            marked.append(artifact_id)
        except KeyError:
            # Named an artifact the Blueprint does not have. A defect, but not
            # one to fix by inventing the artifact.
            continue
    if marked:
        svc.save()
    return marked


def repair_brief(report: VerificationReport, page_id: str) -> str:
    """What the composing agent is told when it authors this page again.

    §103 makes retries meaningful only if the next attempt is told what was
    wrong with the last one. Without this the repair task is "compose PAGE-004
    again", which re-runs an identical prompt and reproduces the identical
    page.
    """
    mine = [f.detail for f in report.findings if f.artifact_id == page_id]
    if not mine:
        return ""
    return (
        "A previous rendering of this page was reviewed and did not pass:\n"
        + "\n".join(f"  - {d}" for d in mine)
        + "\n\nCompose it again addressing those. They describe what the page "
          "looked like, not what to type: decide yourself what change in the "
          "layout answers each one."
    )


def anthropic_critic(
    *, domain: str, app_name: str, description: str, tone: str = "",
    page_types: dict[str, str] | None = None,
) -> Critic:
    """A :data:`Critic` backed by ``services.vision_evaluator``.

    Separated from everything above so the bridge stays testable with a fake
    and the async entry point is adapted in exactly one place.
    """
    import asyncio

    from services.vision_evaluator import EvaluatorContext, evaluate_page

    types = page_types or {}

    def critic(shot: Shot) -> Any:
        ctx = EvaluatorContext(
            domain=domain, app_name=app_name, description=description,
            tone=tone, route=shot.route,
            page_type=types.get(shot.page_id, ""), page_role="",
        )
        return asyncio.run(evaluate_page(
            png_bytes=shot.png, a11y_tree=shot.a11y_tree, ctx=ctx))

    return critic


def shots_for(doc: dict, rendered: Sequence[tuple[str, bytes, str]]) -> list[Shot]:
    """Bind rendered routes to the pages they came from.

    A render knows its route; the Blueprint knows which artifact that route is.
    A shot whose route matches no page is dropped rather than critiqued — a
    critique against an id nobody can flag is spend with nowhere to land.
    """
    by_route = {
        (p.get("route") or "").strip(): p.get("id", "")
        for p in (doc.get("pages") or []) if isinstance(p, dict)
    }
    out: list[Shot] = []
    for route, png, tree in rendered:
        page_id = by_route.get((route or "").strip(), "")
        if page_id:
            out.append(Shot(page_id=page_id, route=route, png=png, a11y_tree=tree))
    return out
