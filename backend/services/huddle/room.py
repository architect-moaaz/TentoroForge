"""A huddle: the owners of the parts a question touches, a chair, a decision.

ONE AGENT COULD NOT SETTLE IT. The observer sends a finding back to the node
that wrote it, and only to that node: across 258 local runs 220 findings were
still wrong after both rounds and shipped flagged, many because the fix lay in
another agent's part ("no data constraint exists" sent to the field author,
who cannot write constraints). An agent's request for a change to another
agent's part was collected and dropped. And the decisions everything else is
built on — the data model, the screens, the processes, the permissions — were
judged by one critic, never by the agents that must build on them.

A huddle puts the owners in one room. Each says, side by side and from its
own part of the definition, what it sees, what it would change in its own
part, and what it needs from another; the observer, chairing, decides — one
outcome, and for each owner that must act a brief saying what to change and
what to keep. The decision is written to the Blueprint's `decisions`, binding
on every later agent (§20), and each brief re-runs its owner through the seam
Smith re-decides a section with, so the owner's reply passes the same
contract as everything else. The person watches and may overrule afterwards;
nothing waits on them unless the owners truly conflict over something the
requirements do not settle — then the decision is a question.

Who takes part is read from the build itself — which agent owns which
section, which agents read what another writes — never listed by name.
"""
from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

#: The most agents in one huddle. More voices is more cost, not a better
#: decision: the chair has to read all of them.
MAX_PARTICIPANTS = 3
#: A decision made once for the application is a big one when at least this
#: many other agents read what it writes.
READERS_FOR_A_BIG_DECISION = 5
#: Who chairs: the agent that judges and writes nothing.
CHAIR = "observer"
#: How much of an agent's part of the definition it is shown.
CONTEXT_CHARS = 60_000

POSITION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["view", "change", "needs"],
    "properties": {
        "view": {"type": "string"},
        "change": {"type": "string"},
        "needs": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["agent", "what"],
            "properties": {"agent": {"type": "string"}, "what": {"type": "string"}}}},
    },
}

CHAIR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["settled", "decision", "reason", "briefs", "question"],
    "properties": {
        "settled": {"type": "boolean"},
        "decision": {"type": "string"},
        "reason": {"type": "string"},
        "briefs": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["agent", "changes", "brief"],
            "properties": {"agent": {"type": "string"}, "changes": {"type": "boolean"},
                           "brief": {"type": "string"}}}},
        "question": {"type": "string"},
    },
}


# --------------------------------------------------------------------------- #
# Who takes part — read from the build
# --------------------------------------------------------------------------- #

def owned_sections(agent: str) -> tuple[str, ...]:
    from services.blueprint.agent_contract import AGENT_REGISTRY
    cap = AGENT_REGISTRY.get(agent)
    return tuple(sorted(cap.writes)) if cap is not None else ()


def _running_agents() -> set[str]:
    from services.blueprint.orchestrator import DAG
    return {n.agent for n in DAG.values() if n.kind == "agent"}


def readers(node: str) -> list[str]:
    """The other agents of the build that read what `node` writes."""
    from services.blueprint.agent_contract import AGENT_REGISTRY
    from services.blueprint.orchestrator import DAG
    me = DAG[node]
    sections = {s.split(".")[0] for s in me.produces}
    out = []
    for agent in sorted(_running_agents() - {me.agent}):
        reads = set(AGENT_REGISTRY[agent].reads)
        if "*" in reads or sections & reads:
            out.append(agent)
    return out


def big_decisions() -> list[str]:
    """The nodes whose decision is made once for the whole application and
    built on by at least READERS_FOR_A_BIG_DECISION other agents — not a page
    or a record type at a time, and not one the observer is told to leave."""
    from services.blueprint.orchestrator import DAG, OBSERVER_ROUNDS_BY_NODE
    return [k for k, n in DAG.items()
            if n.kind == "agent" and not n.fanout and OBSERVER_ROUNDS_BY_NODE.get(k, 1) != 0
            and len(readers(k)) >= READERS_FOR_A_BIG_DECISION]


def _readers_of_section(section: str) -> int:
    from services.blueprint.agent_contract import AGENT_REGISTRY
    return sum(1 for a in _running_agents() if section in AGENT_REGISTRY[a].reads)


def _weight(agent: str) -> int:
    """How much of the build stands on this agent's work: the agents that
    read the sections it writes."""
    return max((_readers_of_section(s.split(".")[0]) for s in owned_sections(agent)), default=0)


def takes_part(agent: str, doc: dict | None = None) -> bool:
    """Whether the agent has work in this application: a node that decides
    once, or one that works per subject and has a subject here — the design
    reader has none when no design is connected."""
    from services.blueprint.orchestrator import DAG, subjects_for
    for n in DAG.values():
        if n.agent != agent or n.kind != "agent":
            continue
        if not n.fanout:
            return True
        if doc is not None:
            try:
                if subjects_for(n, doc):
                    return True
            except Exception:  # noqa: BLE001 — a subject list that cannot be read is no work
                continue
    return False


def builders_of(node: str, doc: dict | None = None) -> list[str]:
    """Who reviews a big decision: the agents that read what it writes by
    name (not the ones that read everything), the ones whose own work most
    of the build stands on first — they are the ones a wrong decision here
    costs most — at most MAX_PARTICIPANTS."""
    from services.blueprint.agent_contract import AGENT_REGISTRY
    from services.blueprint.orchestrator import DAG
    sections = {s.split(".")[0] for s in DAG[node].produces}
    named = [a for a in readers(node) if sections & set(AGENT_REGISTRY[a].reads) and takes_part(a, doc)]
    return sorted(named, key=lambda a: (-_weight(a), a))[:MAX_PARTICIPANTS]


_ID = re.compile(r"\b([A-Z]+)-\d{3,}\b")


def owners_named(text: str, *, also: str = "") -> list[str]:
    """The agents owning what `text` names — artifacts by id (`PAGE-004`,
    `PERM-012`) and sections by their dotted name (`data.constraints`) —
    with `also` first. At most MAX_PARTICIPANTS."""
    from services.blueprint.service import ARTIFACT_SECTIONS
    from services.blueprint.verification import SECTION_OWNER
    by_prefix = {prefix: section for section, prefix in ARTIFACT_SECTIONS.items()}
    out: list[str] = [also] if also else []
    for prefix in _ID.findall(text or ""):
        owner = SECTION_OWNER.get(by_prefix.get(prefix, ""), "")
        if owner and owner not in out:
            out.append(owner)
    for section, owner in SECTION_OWNER.items():
        if "." in section and re.search(rf"\b{re.escape(section)}\b", text or "") and owner not in out:
            out.append(owner)
    return [a for a in out if a and a != CHAIR][:MAX_PARTICIPANTS]


def node_for(agent: str, hint: str = "") -> str | None:
    """The node that re-decides `agent`'s part: `hint` when it is that
    agent's, else the agent's node that decides once for the application the
    part of its work most of the build reads."""
    from services.blueprint.orchestrator import DAG
    if hint in DAG and DAG[hint].agent == agent:
        return hint
    mine = [k for k, n in DAG.items() if n.agent == agent and n.kind == "agent"]
    once = [k for k in mine if not DAG[k].fanout] or mine
    if not once:
        return None
    return max(once, key=lambda k: (max((_readers_of_section(s.split(".")[0]) for s in DAG[k].produces),
                                        default=0), -mine.index(k)))


# --------------------------------------------------------------------------- #
# The record
# --------------------------------------------------------------------------- #

@dataclass
class Huddle:
    id: str
    kind: str                       # "review" | "deadlock"
    topic: str
    trigger: dict
    participants: list[str]
    chair: str = CHAIR
    positions: list[dict] = field(default_factory=list)
    decision: dict = field(default_factory=dict)
    #: open → decided | deadlock; decided → overruled
    status: str = "open"
    briefs: dict = field(default_factory=dict)
    outcome: list[str] = field(default_factory=list)
    at: str = ""
    decided_at: str = ""

    def summary(self) -> dict:
        return {"id": self.id, "kind": self.kind, "topic": self.topic, "participants": self.participants,
                "chair": self.chair, "status": self.status, "decision": self.decision.get("decision", ""),
                "reason": self.decision.get("reason", ""), "question": self.decision.get("question", ""),
                "briefed": sorted(self.briefs)}


def huddle_dir(output_dir: str | Path) -> Path:
    return Path(output_dir) / ".forge" / "huddles"


def save(output_dir: str | Path, h: Huddle) -> None:
    d = huddle_dir(output_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{h.id}.json").write_text(json.dumps(asdict(h), indent=1, default=str))


def load(output_dir: str | Path, hid: str) -> Huddle | None:
    try:
        return Huddle(**json.loads((huddle_dir(output_dir) / f"{hid}.json").read_text()))
    except (OSError, ValueError, TypeError):
        return None


def huddles(output_dir: str | Path) -> list[Huddle]:
    rows = [load(output_dir, p.stem) for p in sorted(huddle_dir(output_dir).glob("HUD-*.json"))]
    return [h for h in rows if h is not None]


def _next_id(output_dir: str | Path) -> str:
    nums = [int(m.group(1)) for p in huddle_dir(output_dir).glob("HUD-*.json")
            if (m := re.match(r"HUD-(\d+)$", p.stem))]
    return f"HUD-{(max(nums) + 1) if nums else 1:03d}"


# --------------------------------------------------------------------------- #
# The room
# --------------------------------------------------------------------------- #

POSITION_SYSTEM = (
    "You are Forge's {agent} agent. You own {sections} of this application's definition, and nothing else; "
    "other agents own the rest. You are in a huddle about one question with the agents named below, chaired "
    "by the observer, who will decide. Say what you see from your own part, concretely, naming artifacts by "
    "id. `view`: what is true about the question as your part shows it. `change`: what you would change in "
    "YOUR part to settle it — empty when your part needs nothing. `needs`: what you need another agent in the "
    "room to change in theirs, each with that agent's name. If your part is right and the fault is elsewhere, "
    "say so; do not defend or concede for its own sake. Keep each field short."
)

CHAIR_SYSTEM = (
    "You chair a huddle of Forge's agents, each the owner of one part of an application's definition. Read "
    "the question, the evidence and what each agent said, and decide. `decision`: one concrete outcome in a "
    "sentence or two, as the person who asked for the application would read it. `reason`: why, against "
    "their requirements. `briefs`: for each agent in the room that must change its part, `changes` true and "
    "what exactly to change, naming artifacts by id, and what to keep as it is; an agent whose part stays "
    "gets no brief, or `changes` false. If "
    "the question asks for something the definition already does, decide that nothing changes, and say why. "
    "`settled` is false ONLY when the agents' parts conflict over something the requirements do not decide; "
    "then `question` is what to ask the person, in their words, and `briefs` is empty. Otherwise `question` "
    "is empty."
)


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n] + "\n…(cut)"


class Room:
    """Convenes huddles for one application and keeps their records."""

    def __init__(self, output_dir: str | Path, client: Any, *, usage: Any = None,
                 emit: Callable[[str, dict], None] | None = None,
                 note: Callable[..., None] | None = None):
        self.output_dir = Path(output_dir)
        self.client = client
        self.usage = usage
        self.emit = emit
        self.note = note

    def _office(self, phase: str, h: Huddle, extra: dict) -> None:
        """The meeting room: the participants walk in, each position is a
        speech bubble, the decision is the chair's, and they walk back."""
        try:
            from services.office_bridge import office_for
            show = office_for(self.output_dir)
            if show is None:
                return
            base = {"huddleId": h.id, "kind": h.kind, "topic": h.topic[:200],
                    "participants": h.participants, "chair": h.chair}
            if phase == "start":
                show({"type": "huddle_start", **base})
            elif phase == "position":
                text = extra.get("change") or extra.get("view") or ""
                show({"type": "huddle_say", **base, "agent": extra.get("agent"), "text": str(text)[:160]})
            else:
                show({"type": "huddle_end", **base, "status": h.status,
                      "decision": (h.decision.get("decision") or h.decision.get("question") or "")[:200]})
        except Exception:  # noqa: BLE001 — the picture never fails the huddle
            logger.debug("[huddle] office event failed", exc_info=True)

    def _say(self, phase: str, h: Huddle, **extra: Any) -> None:
        self._office(phase, h, extra)
        if self.emit is not None:
            try:
                self.emit("huddle", {"phase": phase, **h.summary(), **extra})
            except Exception:  # noqa: BLE001 — telling never fails a huddle
                logger.debug("[huddle] emit failed", exc_info=True)
        if self.note is not None:
            try:
                self.note(f"huddle:{phase}", h.id, **extra)
            except Exception:  # noqa: BLE001
                pass

    def _call(self, h: Huddle, who: str, system: str, user: str, schema: dict) -> dict:
        t0 = time.monotonic()
        raw = self.client(system=system, user=user, schema=schema)
        used = getattr(raw, "usage", None)
        if self.usage is not None and used is not None:
            try:
                self.usage.record(node=f"huddle:{h.kind}", agent=who, usage=used,
                                  elapsed_s=time.monotonic() - t0)
            except Exception:  # noqa: BLE001 — the ledger never ends a huddle
                pass
        text = getattr(raw, "text", raw)
        out = json.loads(text if isinstance(text, str) else "{}")
        return out if isinstance(out, dict) else {}

    def _position(self, h: Huddle, doc: dict, agent: str, evidence: str) -> dict:
        from services.blueprint.executors import context_for
        others = ", ".join(a for a in h.participants if a != agent) or "none"
        system = POSITION_SYSTEM.format(agent=agent, sections=", ".join(owned_sections(agent)) or "no section")
        part = _clip(json.dumps(context_for(doc, agent), indent=1, default=str), CONTEXT_CHARS)
        user = (f"The question: {h.topic}\n\nWhat raised it:\n{evidence}\n\nAlso in the room: {others}.\n\n"
                f"The definition as you may read it:\n```json\n{part}\n```")
        try:
            got = self._call(h, agent, system, user, POSITION_SCHEMA)
        except Exception as exc:  # noqa: BLE001 — a silent agent is recorded, not invented
            return {"agent": agent, "view": "", "change": "", "needs": [],
                    "unavailable": f"{type(exc).__name__}: {str(exc)[:200]}"}
        return {"agent": agent, "view": str(got.get("view") or ""), "change": str(got.get("change") or ""),
                "needs": [n for n in got.get("needs") or [] if isinstance(n, dict)]}

    def convene(self, doc: dict, *, kind: str, topic: str, participants: list[str], evidence: str,
                trigger: dict | None = None, owner: str = "") -> Huddle:
        """Positions side by side, then the chair. Recorded at every step.

        `owner` is the agent whose decision a review huddle is about: not in
        the room — its decision speaks for it — but the one the chair briefs
        to change it."""
        people = [a for a in dict.fromkeys(participants) if a and a != CHAIR and a != owner][:MAX_PARTICIPANTS]
        h = Huddle(id=_next_id(self.output_dir), kind=kind, topic=topic, trigger=dict(trigger or {}),
                   participants=people, at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        save(self.output_dir, h)
        self._say("start", h, evidence=evidence[:600])
        with ThreadPoolExecutor(max_workers=max(1, len(people))) as pool:
            h.positions = list(pool.map(lambda a: self._position(h, doc, a, evidence), people))
        for p in h.positions:
            self._say("position", h, agent=p["agent"], view=p["view"][:400], change=p["change"][:400])
        save(self.output_dir, h)
        heard = [p for p in h.positions if not p.get("unavailable")]
        if not heard:
            h.status, h.decision = "deadlock", {"decision": "", "reason": "no agent in the room could answer",
                                               "question": ""}
            save(self.output_dir, h)
            self._say("deadlock", h)
            return h
        reqs = [{"id": r.get("id"), "says": str(r.get("description") or "")[:240]}
                for r in doc.get("requirements") or [] if isinstance(r, dict)
                and str(r.get("status") or "").upper() not in ("DEPRECATED", "SUPERSEDED")][:80]
        user = (f"The question: {topic}\n\nWhat raised it:\n{evidence}\n\nWhat each agent said:\n```json\n"
                f"{json.dumps(heard, indent=1)}\n```\n\nThe person's requirements:\n```json\n"
                f"{json.dumps(reqs, indent=1)}\n```")
        if owner:
            user += (f"\n\nThe {owner} agent made the decision under review and is not in the room; brief it "
                     f"(as `{owner}`) when its decision must change.")
        try:
            got = self._call(h, CHAIR, CHAIR_SYSTEM, user, CHAIR_SCHEMA)
        except Exception as exc:  # noqa: BLE001
            h.status = "deadlock"
            h.decision = {"decision": "", "reason": f"the chair could not decide: {type(exc).__name__}", "question": ""}
            save(self.output_dir, h)
            self._say("deadlock", h)
            return h
        h.decision = {"decision": str(got.get("decision") or "").strip(),
                      "reason": str(got.get("reason") or "").strip(),
                      "question": str(got.get("question") or "").strip()}
        answerable = set(people) | ({owner} if owner else set())
        # A BRIEF THAT CHANGES NOTHING IS NOT SENT. Told to brief only the
        # agents whose part must change, the chair still wrote "no changes
        # needed to PAGE-012" for two of three (TCommerce copy, 2026-10-08),
        # and each would have re-run its node for nothing. Whether a brief
        # changes anything is its own field, and only those that do are kept.
        h.briefs = {str(b.get("agent")): str(b.get("brief") or "").strip() for b in got.get("briefs") or []
                    if isinstance(b, dict) and b.get("changes") is not False
                    and str(b.get("agent")) in answerable and str(b.get("brief") or "").strip()}
        h.status = "decided" if got.get("settled") and h.decision["decision"] else "deadlock"
        if h.status == "deadlock":
            h.briefs = {}
        h.decided_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save(self.output_dir, h)
        self._say("decided" if h.status == "decided" else "deadlock", h)
        return h


# --------------------------------------------------------------------------- #
# The decision, carried out
# --------------------------------------------------------------------------- #

def record_decision(svc: Any, h: Huddle, *, by: str = "huddle") -> str:
    """The decision in the Blueprint's `decisions`, binding on later agents.
    The person's decision supersedes the huddle's (§20): a new row naming the
    one it replaces, which is retired (DEPRECATED) — the history reads as a
    change of mind, not as if the agents never decided. Its id is kept on the
    huddle (`decision.id`)."""
    body = {"decision": h.decision.get("decision", ""), "reason": h.decision.get("reason", ""),
            "source": "user" if by == "user" else "huddle",
            "approvedBy": "user" if by == "user" else "smith",
            "binding": True, "status": "APPROVED", "version": svc.doc.get("version", 1)}
    previous = str(h.decision.get("id") or "")
    if by == "user" and not previous:
        # A record kept before its decision's id was: the agents' row, by what it says.
        said = h.decision.get("overruled", "")
        previous = next((str(r.get("id")) for r in svc.doc.get("decisions") or [] if isinstance(r, dict)
                         and r.get("source") == "huddle" and r.get("decision") == said), "")
    if by == "user" and previous:
        body["supersedes"] = previous
        for row in svc.doc.get("decisions") or []:
            if isinstance(row, dict) and row.get("id") == previous:
                row["status"] = "DEPRECATED"
    # BIND FIRST, as the section seam does: a document whose ids the registry
    # has not seen (a copy, an old app) would otherwise be handed DEC-001
    # beside the DEC-001 it already has (`section_change.bind_ids`).
    from services.smith.section_change import bind_ids
    bind_ids(svc)
    written = svc.upsert("decisions", body, natural_key=f"{h.id}:{by}")
    svc.validate()
    svc.save()
    h.decision["id"] = str(written.get("id") or "")
    return h.decision["id"]


def carry_out(svc: Any, h: Huddle, *, app_root: str | None = None, reasoning: Any = None,
              executor: Any = None, hint: str = "") -> Huddle:
    """Write the decision down and brief each owner that must act, through
    `section_change.rerun`: the owner's reply is checked by the same contract
    as any other, and a refused one leaves its part as it was — said, not
    hidden. A deadlock is written down as the question it is and nobody is
    briefed."""
    from services.smith.section_change import SectionChangeError, rerun
    if h.status != "decided":
        return h
    try:
        dec = record_decision(svc, h)
        h.outcome.append(f"recorded as {dec}")
    except Exception as exc:  # noqa: BLE001 — the briefs still go
        h.outcome.append(f"the decision could not be recorded: {type(exc).__name__}: {str(exc)[:200]}")
    for agent, brief in h.briefs.items():
        node = node_for(agent, hint)
        if node is None:
            h.outcome.append(f"{agent}: no node re-decides its part")
            continue
        framed = (f"A huddle of the agents that own this application's parts decided: "
                  f"\"{h.decision.get('decision')}\" ({h.id}). Your part of it: {brief}\n\n"
                  "Change ONLY what this asks and keep everything else exactly as it is. Return the "
                  "artifacts that change, keyed as they are now.")
        try:
            props, _ = rerun(svc, node, brief=framed, request=h.topic,
                             interpretation=f"{h.id}: {h.decision.get('decision')}",
                             app_root=app_root, reasoning=reasoning, executor=executor,
                             say=f"Carrying out {h.id} for {agent}.")
            keys = sorted({str(getattr(p, 'natural_key', '') or '') for p in props} - {""})
            h.outcome.append(f"{agent} ({node}) changed {', '.join(keys[:8]) or 'its part'}")
        except SectionChangeError as exc:
            h.outcome.append(f"{agent} ({node}) was not changed: {exc}")
        except Exception as exc:  # noqa: BLE001 — one owner's failure is said, the others still act
            logger.exception("[huddle] %s: %s could not act", h.id, agent)
            h.outcome.append(f"{agent} ({node}) could not act: {type(exc).__name__}: {str(exc)[:200]}")
    # THE APP FOLLOWS ITS DEFINITION: what the owners changed is written out
    # to the built tree, every projection, the way a Smith turn catches up.
    changed = any(" changed " in line for line in h.outcome)
    if changed and app_root and (Path(app_root) / "package.json").is_file():
        try:
            from services.smith.sync_app import sync
            out = sync(svc, app_root)
            h.outcome.append(f"the app was brought in step: {len(out.get('changed') or [])} files changed, "
                             f"{len(out.get('added') or [])} added")
        except Exception as exc:  # noqa: BLE001 — the definition changed; the tree is reported, not fatal
            h.outcome.append(f"the app could not be brought in step: {type(exc).__name__}: {str(exc)[:200]}")
    save(svc.output_dir, h)
    return h


def overrule(svc: Any, hid: str, words: str) -> Huddle:
    """The person decides otherwise. Their words replace the huddle's decision
    in the Blueprint — the same row, now theirs (`approvedBy: user`) — and the
    huddle is marked overruled. Carrying their decision out is a Smith turn
    on their words (`ask`), which re-runs whichever owners it touches."""
    h = load(svc.output_dir, hid)
    if h is None:
        raise KeyError(hid)
    text = " ".join(str(words or "").split())
    if not text:
        raise ValueError("an overrule says what to decide instead")
    was = h.decision.get("decision") or h.decision.get("question") or ""
    h.decision = {**h.decision, "overruled": was, "decision": text,
                  "reason": "the person decided otherwise", "question": ""}
    record_decision(svc, h, by="user")
    h.status = "overruled"
    h.outcome.append(f"overruled by the person: {text}")
    save(svc.output_dir, h)
    return h


def ask(h: Huddle) -> str:
    """What Smith is told when the person overrules a huddle."""
    was = h.decision.get("overruled", "")
    return (f"I overrule {h.id} — the agents decided \"{was}\" about \"{h.topic}\". "
            f"Instead: {h.decision.get('decision', '')}")


__all__ = ["Huddle", "Room", "overrule", "ask", "huddles", "load", "save", "carry_out", "record_decision", "readers",
           "big_decisions", "builders_of", "takes_part", "owners_named", "node_for", "owned_sections",
           "MAX_PARTICIPANTS", "CHAIR", "POSITION_SCHEMA", "CHAIR_SCHEMA"]
