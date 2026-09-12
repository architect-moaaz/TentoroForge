"""The observer — validates each node's outcome as it lands and drives the repair.

§73 draws one loop: generate → verify → passed? → repair → verify. The
substrate had the middle of it and neither end. :mod:`verification` walks the
§75 matrix and :mod:`functional_completeness` asks whether the described
application would do anything; both report findings, both route each one to
the agent that owns the section (§74) — and the routing stopped at
``VerificationReport.repair_tasks()``, which nothing ever read. A build ran
every node, verification flagged what was wrong at the very end, and the
flagged artifacts had already been consumed by every node downstream of them.

The observer closes the loop where it is cheapest to close: at the node. It
runs BESIDE the DAG rather than in it. When an agent node's subjects have all
been applied, the scheduler hands the observer a snapshot of the Blueprint
and carries on with the rest of the graph; the observer validates that node's
outcome on a worker — the deterministic edges first, then, when it has a
critic, a model's judgement of whether the outcome is complete against the
requirements it claims and the user's request. The node is *finished* but not
*done*: nothing that depends on it starts until the verdict is in and every
subject the observer failed has been re-authored and judged again. That is
not a limitation to work around: §28's rule is that work runs on complete
inputs, and a repair that lands after a dependent has consumed the defect is
the swarm it forbids.

What "repair" means here, exactly
---------------------------------
The observer decides what is wrong; the agent that owns the section authors
the fix. A finding becomes a *repair brief* — the same ``feedback`` field a
rejected proposal already travels back to its author in — and the owning node
is re-run for that subject with the brief attached. The proposal it returns
goes through :func:`apply_agent_result` like any other, so it is bounded by the
same §30 capability, validated by the same contract and allocated the same ids
(natural keys make the re-authoring an update, not a duplicate). The observer
itself is registered with ``writes = ∅``: a version of it that "fixed" a page
directly would be a second author with no boundary, which is the 151-pass
repair chain this rebuild replaced.

A node the observer cannot bring round in :data:`OBSERVER_ROUNDS` is left as
its author last wrote it and flagged ``OUT_OF_SYNC`` with the findings (§76).
Nothing is silently patched; the report says what stayed wrong.

Whose findings are the node's
-----------------------------
Only findings on sections the node's agent owns are the node's to repair — a
Page↔Workflow finding surfaced while observing ``workflows`` but naming a page
belongs to ``page_design``, whose node has already run and been consumed.
Those are *deferred*: recorded here, and flagged by the terminal
``verification`` node as they always were. Holding a node to another agent's
domain would either mis-route the brief or re-order the DAG.

An edge is judged only once every section it relates is settled — produced
by a node that has completed, or already present and produced by nothing in
this plan (:data:`verification.EDGE_SECTIONS`). Otherwise the observer would
tell the requirements author that nothing implements a requirement before a
single page exists.

The critic
----------
The model half is optional and injected — ``Observer()`` with no critic is
the deterministic checks alone, which is what every test runs. The critic is
handed the node's output, the requirements in force and the user's request,
and returns findings in a closed shape: a section it may only choose from the
sections this node's agent owns, an artifact id, a requirement id, and what
is missing. There is no field in which to propose a fix. A ``fail`` with no
findings is not a verdict, it is an opinion, and is recorded as a pass. When
the critic is unavailable — no key, a refusal, a malformed reply — the
observation says so and the deterministic verdict stands; a verdict is never
invented for it.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from services.blueprint.agent_contract import capability_for
from services.blueprint.verification import (
    EDGE_SECTIONS,
    EDGES,
    SECTION_OWNER,
    Finding,
    verify,
)

logger = logging.getLogger(__name__)

#: verify → repair → verify, how many times per node before the observer stops
#: and flags. Two: the first repair carries the brief, the second carries the
#: brief plus what the first repair still missed. A third round on a node that
#: has ignored the same brief twice is the same failure at higher cost — the
#: same argument as ``ATTEMPTS_BY_NODE``.
OBSERVER_ROUNDS = 2

#: Which agent the observer is. Registered with no writable section — its
#: capability is to flag, never to author.
OBSERVER_AGENT = "observer"

#: The critic's reply, closed. No ``fix``, ``patch`` or ``proposal`` field
#: exists to fill. Structured-output safe: no ``pattern``, no numeric bounds.
VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "findings"],
    "properties": {
        "verdict": {"type": "string", "enum": ["pass", "fail"]},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["section", "artifact", "requirement", "detail"],
                "properties": {
                    "section": {"type": "string"},
                    "artifact": {"type": "string"},
                    "requirement": {"type": "string"},
                    "detail": {"type": "string"},
                },
            },
        },
    },
}

#: The edge name the critic's findings carry, so a report can tell a model's
#: judgement from a matrix check.
CRITIC_EDGE = "Observer↔Requirement"


# ---------------------------------------------------------------------------
# verdicts
# ---------------------------------------------------------------------------

@dataclass
class Observation:
    """One node's outcome, judged."""

    node: str
    agent: str
    #: The subjects that were applied; ``[""]`` for a node that writes once.
    subjects: list[str]
    #: Findings this node's agent owns, grouped by the subject to re-author.
    findings: dict[str, list[Finding]] = field(default_factory=dict)
    #: Findings on sections another agent owns. Not this node's to repair;
    #: the terminal verification node flags them (§76).
    deferred: list[Finding] = field(default_factory=list)
    #: ``pass`` | ``fail`` | ``not consulted`` | ``unavailable: <why>``.
    critic: str = "not consulted"
    #: Edges that were judged, for the record.
    edges: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.findings

    def brief(self, subject: str) -> str:
        """§103 — what the re-run is told. A repair not told what was wrong is
        the same request again."""
        lines = [
            f"- [{f.edge}] {f.artifact_id or f.section}: {f.detail}"
            for f in self.findings.get(subject, [])
        ]
        return (
            "The observer reviewed your output against the Blueprint and the "
            "requirements it claims, and found it incomplete. Author it again "
            "so that every point below is addressed. Your reply REPLACES what "
            "you wrote before for this subject: include everything that "
            "should remain, under the same names and keys it already has, "
            "and correct what is wrong in place. Anything you leave out is "
            "retired. Do not rename what you are not asked to change.\n\n"
            + "\n".join(lines)
        )

    def summary(self) -> dict[str, Any]:
        return {
            "node": self.node,
            "ok": self.ok,
            "findings": sum(len(v) for v in self.findings.values()),
            "deferred": len(self.deferred),
            "critic": self.critic,
            "subjects": sorted(s for s in self.findings if self.findings[s]),
        }


@dataclass(frozen=True)
class RepairTask:
    """What the orchestrator re-runs: the owning node, for one subject, with
    the brief as feedback. The observer never runs it — the orchestrator does,
    through the same executor and the same apply as the original."""

    node: str
    agent: str
    subject: str
    feedback: str

    @property
    def label(self) -> str:
        return f"{self.node}:{self.subject}" if self.subject else self.node


# ---------------------------------------------------------------------------
# readiness
# ---------------------------------------------------------------------------

def _section(doc: Mapping[str, Any], path: str) -> Any:
    cur: Any = doc
    for part in path.split("."):
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(part)
    return cur


def ready_edges(
    doc: Mapping[str, Any],
    *,
    pending: Iterable[str],
    planned: Iterable[str],
    edges: Sequence[str] = EDGES,
) -> tuple[str, ...]:
    """The edges whose every side is settled.

    A section is settled when it is not produced by a node still pending in
    this plan, and either some node in the plan produced it (and has
    completed, since it is not pending) or nothing in the plan produces it
    and it already has content. A section nothing will write and nothing has
    written is not a side to judge against.
    """
    pending_set = set(pending)
    planned_set = set(planned)

    def settled(section: str) -> bool:
        if section in pending_set:
            return False
        if section in planned_set:
            return True
        return bool(_section(doc, section))

    return tuple(
        edge for edge in edges
        if all(settled(s) for s in EDGE_SECTIONS.get(edge, ()))
    )


# ---------------------------------------------------------------------------
# the critic's view
# ---------------------------------------------------------------------------

def _live(items: Any) -> list[dict]:
    return [i for i in (items or []) if isinstance(i, dict)
            and i.get("status") != "DEPRECATED"]


def owned_sections(agent: str) -> tuple[str, ...]:
    """The sections §74 routes to this agent — what the critic may name."""
    return tuple(sorted(s for s, owner in SECTION_OWNER.items() if owner == agent))


#: Where an artifact came from, not what it says. `syncNote` is what the
#: LAST verdict wrote on it; shown to the next critic it reads as a claim the
#: artifact makes — measured: the database critic reported the Member entity
#: "internally contradictory" because its syncNote said a relationship was
#: missing after the relationship had been added. Same fields
#: `executors.PROVENANCE_FIELDS` withholds from every non-owning agent.
_PROVENANCE = ("syncNote", "evidence")


def _without_provenance(row: Any) -> Any:
    if isinstance(row, dict):
        return {k: v for k, v in row.items() if k not in _PROVENANCE}
    return row


def _rows(doc: Mapping[str, Any], section: str, subject: str) -> Any:
    value = _section(doc, section)
    if isinstance(value, list):
        # Retired rows are not the node's answer. Shown to the critic they
        # read as duplicates left lying around — measured: a repaired module
        # was flagged for the DEPRECATED one it had replaced, and the next
        # round churned on that instead of the real finding.
        value = [_without_provenance(row) for row in _live(value)]
    elif isinstance(value, dict):
        value = _without_provenance(value)
    if not subject or not isinstance(value, list):
        return value
    # A fan-out subject is an artifact id (a page); its own row, and any row
    # in another owned section that points at it (a page's layout, widgets).
    return [
        row for row in value if isinstance(row, dict)
        and subject in (row.get("id"), row.get("page"),
                        (row.get("data") or {}).get("primaryEntity")
                        if isinstance(row.get("data"), dict) else None)
    ]


def observation_context(
    doc: Mapping[str, Any], *, agent: str, subject: str = "",
    user_request: str = "",
) -> dict[str, Any]:
    """What the critic is shown: the node's output, the requirements in force,
    and the request. Not the whole Blueprint — a page's judgement does not
    need forty other pages, and the slice is what keeps the call affordable
    enough to make per node."""
    sections = owned_sections(agent)
    produced = {s: _rows(doc, s, subject) for s in sections}
    produced = {s: v for s, v in produced.items() if v}

    cited: set[str] = set()
    for value in produced.values():
        for row in (value if isinstance(value, list) else [value]):
            if isinstance(row, dict):
                cited.update(row.get("requirements") or [])

    requirements = [
        {k: r.get(k) for k in ("id", "title", "statement", "description",
                               "priority", "status") if r.get(k) is not None}
        for r in _live(doc.get("requirements"))
    ]
    if subject:
        # A page's contract is the promise its layout is judged against.
        page = next((p for p in _live(doc.get("pages")) if p.get("id") == subject), None)
        if page is not None and "pages" not in produced:
            produced["pages"] = [page]

    return {
        "userRequest": user_request,
        "application": {
            k: v for k, v in (doc.get("application") or {}).items()
            if k in ("name", "domain", "description")
        },
        "agent": agent,
        "sectionsYouMayName": list(sections),
        "subject": subject,
        "output": produced,
        "requirementsCited": sorted(cited),
        "requirements": requirements,
    }


def critic_prompt(context: dict[str, Any]) -> tuple[str, str]:
    """(system, user). The system half is the contract; the user half is the
    slice."""
    system = (
        "You are the observer for a Prompt-to-App build. A specialist agent "
        "has just finished its task and you are judging its outcome.\n\n"
        "Decide whether the output is COMPLETE against the requirements it "
        "claims, the requirements that fall in its domain, and the user's "
        "request. Report a finding for each thing that is genuinely missing, "
        "contradicts a requirement, or claims a requirement it does not "
        "actually satisfy. Each finding names: the section (one of "
        "sectionsYouMayName), the artifact id it concerns (empty if none "
        "exists yet), the requirement id it fails (empty if none), and in one "
        "or two sentences what is missing.\n\n"
        "You cannot edit anything and you must not propose alternatives, "
        "restyle, rename, or comment on quality. Do not report preferences. "
        "If the output is complete, the verdict is pass and findings is "
        "empty. A fail verdict requires at least one finding."
    )
    user = json.dumps(context, ensure_ascii=False, indent=1)
    return system, user


# ---------------------------------------------------------------------------
# the observer
# ---------------------------------------------------------------------------

class Observer:
    """Watches agent nodes complete, judges each, and hands back repair tasks.

    ``critic`` is a :class:`executors.ModelClient` or nothing. ``usage`` is a
    :class:`executors.RunUsage` the critic's spend is recorded into under
    ``observer:<node>``, so a run's cost says what the watching cost.
    """

    def __init__(
        self,
        critic: Any = None,
        *,
        rounds: int = OBSERVER_ROUNDS,
        usage: Any = None,
    ) -> None:
        cap = capability_for(OBSERVER_AGENT)
        assert not cap.writes and cap.may_set_status, (
            "the observer must be able to flag and nothing else"
        )
        self.critic = critic
        self.rounds = max(1, int(rounds))
        self.usage = usage
        self._lock = threading.Lock()
        #: Every observation made, in order — the account of what was judged.
        self.history: list[Observation] = []

    # -- judging -----------------------------------------------------------

    def observe(
        self,
        key: str,
        *,
        agent: str,
        subjects: Sequence[str],
        doc: Mapping[str, Any],
        pending: Iterable[str] = (),
        planned: Iterable[str] = (),
        user_request: str = "",
        subject_of: Callable[[str], str | None] | None = None,
    ) -> Observation:
        """Judge one node's outcome. Pure with respect to the Blueprint: reads
        ``doc``, writes nothing. Safe to run on any thread — the scheduler
        hands it a snapshot and runs it on a worker beside the calls.

        ``subject_of`` maps an artifact id to the subject that authored it,
        for a fan-out whose subjects are not artifact ids (a feature's pages).
        """
        subjects = list(subjects) or [""]
        edges = ready_edges(doc, pending=pending, planned=planned)
        obs = Observation(node=key, agent=agent, subjects=subjects, edges=edges)

        for f in verify(dict(doc), edges=edges).findings:
            self._file(obs, f, subject_of)

        if self.critic is not None:
            self._consult(obs, doc, user_request=user_request,
                          subject_of=subject_of)

        with self._lock:
            self.history.append(obs)
        return obs

    def _file(self, obs: Observation, f: Finding,
              subject_of: Callable[[str], str | None] | None = None) -> None:
        """Route one finding: this node's, per subject — or deferred."""
        if SECTION_OWNER.get(f.section or "") != obs.agent:
            obs.deferred.append(f)
            return
        if obs.subjects == [""]:
            obs.findings.setdefault("", []).append(f)
            return
        subject = f.artifact_id
        if subject not in obs.subjects and subject_of is not None and subject:
            subject = subject_of(subject)
        if subject in obs.subjects:
            obs.findings.setdefault(subject, []).append(f)
            return
        # A fan-out node, and a finding that names no subject of it: nothing
        # to re-author, so nothing to repair. The terminal verification node
        # still flags it.
        obs.deferred.append(f)

    def _consult(self, obs: Observation, doc: Mapping[str, Any], *,
                 user_request: str,
                 subject_of: Callable[[str], str | None] | None = None) -> None:
        """Ask the critic, once per subject. Its findings are filed like any
        other; its verdict is recorded as it was given."""
        verdicts: list[str] = []
        for subject in obs.subjects:
            context = observation_context(
                doc, agent=obs.agent, subject=subject, user_request=user_request,
            )
            if not context["output"]:
                # The node wrote nothing this subject can be judged on. A
                # critique of an empty output is a critique of the prompt.
                continue
            system, user = critic_prompt(context)
            t0 = time.monotonic()
            try:
                raw = self.critic(system=system, user=user, schema=VERDICT_SCHEMA)
            except Exception as exc:  # noqa: BLE001 — recorded, never invented
                obs.critic = f"unavailable: {type(exc).__name__}: {str(exc)[:200]}"
                return
            text = getattr(raw, "text", raw)
            usage = getattr(raw, "usage", None)
            if self.usage is not None and usage is not None:
                try:
                    self.usage.record(node=f"observer:{obs.node}",
                                      agent=OBSERVER_AGENT, usage=usage,
                                      elapsed_s=time.monotonic() - t0, project="")
                except Exception:  # noqa: BLE001 — the ledger never ends a run
                    pass
            try:
                reply = json.loads(text if isinstance(text, str) else "")
                verdict = str(reply["verdict"])
                items = list(reply.get("findings") or [])
            except (ValueError, KeyError, TypeError) as exc:
                obs.critic = f"unavailable: malformed reply: {str(exc)[:200]}"
                return

            filed = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                section = str(item.get("section") or "")
                artifact = str(item.get("artifact") or "") or None
                req = str(item.get("requirement") or "")
                detail = str(item.get("detail") or "").strip()
                if not detail:
                    continue
                if req:
                    detail = f"{req}: {detail}"
                finding = Finding(CRITIC_EDGE, detail=detail,
                                  artifact_id=artifact or (subject or None),
                                  section=section or None)
                self._file(obs, finding, subject_of)
                filed += 1
            # A fail that names nothing is an opinion; recorded as what it is.
            verdicts.append("fail" if verdict == "fail" and filed else "pass")
        obs.critic = "fail" if "fail" in verdicts else "pass"

    # -- repair --------------------------------------------------------------

    def repairs(self, obs: Observation) -> list[RepairTask]:
        """The repair tasks a failed observation implies — one per subject
        with findings, addressed to the node that authored it."""
        return [
            RepairTask(node=obs.node, agent=obs.agent, subject=subject,
                       feedback=obs.brief(subject))
            for subject in obs.subjects
            if obs.findings.get(subject)
        ]


def flag_unrepaired(svc: Any, obs: Observation, subject: str) -> list[str]:
    """§76 — a subject that stayed wrong after every round is flagged with
    what the observer found. Repairs nothing."""
    marked: list[str] = []
    seen: set[str] = set()
    for f in obs.findings.get(subject, []):
        art = f.artifact_id or subject
        if not art or art in seen:
            continue
        seen.add(art)
        try:
            _, row = svc.find(art)
            if row.get("status") == "DEPRECATED":
                # Retired is retired. A finding that still names it does not
                # revive it as a live divergence.
                continue
            svc.mark_out_of_sync(
                art, "; ".join(f"{i.edge}: {i.detail}" for i in
                               obs.findings.get(subject, [])
                               if (i.artifact_id or subject) == art),
            )
            marked.append(art)
        except Exception:  # noqa: BLE001 — a finding naming nothing real
            continue
    if marked:
        svc.save()
    return marked


#: Names the model the observer's critic runs on, when set. The critic reads
#: and judges; it does not author — so it is the one call in a build where a
#: cheaper model is a defensible default, and the first place to point one
#: while measuring. Any current model id works with the request shape
#: `AnthropicModel` sends (`output_config.effort` + a JSON schema, adaptive
#: thinking by default): `claude-sonnet-5` is the cheap choice. Pre-4.6 ids
#: such as `claude-sonnet-4-0` reject `effort` with a 400 and are deprecated.
OBSERVER_MODEL_ENV = "FORGE_OBSERVER_MODEL"


def anthropic_observer(model: Any = None, *, effort: str = "medium",
                       usage: Any = None, rounds: int = OBSERVER_ROUNDS,
                       model_id: str | None = None) -> Observer:
    """An observer whose critic is a model.

    ``model_id`` (or :data:`OBSERVER_MODEL_ENV` in the environment) names the
    critic's model and wins over ``model``. Otherwise ``model`` may be a
    :class:`executors.ModelRouter` (the critic is whatever it assigns to the
    ``observer`` agent), a client, or nothing, in which case an
    :class:`executors.AnthropicModel` at ``effort`` is built.

    ``medium`` because judging is reading, not authoring: the effort sweep on
    `data_model` showed effort buys completeness of *output*, and the
    observer's output is a short list.
    """
    import os

    from services.blueprint.executors import AnthropicModel, ModelRouter

    chosen = model_id or os.environ.get(OBSERVER_MODEL_ENV, "").strip()
    if chosen:
        client = AnthropicModel(model=chosen, effort=effort)
    elif isinstance(model, ModelRouter):
        client = model.for_task(OBSERVER_AGENT, OBSERVER_AGENT)
    elif model is not None:
        client = model
    else:
        client = AnthropicModel(effort=effort)
    return Observer(critic=client, usage=usage, rounds=rounds)


__all__ = [
    "CRITIC_EDGE", "OBSERVER_AGENT", "OBSERVER_MODEL_ENV", "OBSERVER_ROUNDS",
    "VERDICT_SCHEMA",
    "Observation", "Observer", "RepairTask", "anthropic_observer",
    "critic_prompt", "flag_unrepaired", "observation_context",
    "owned_sections", "ready_edges",
]
