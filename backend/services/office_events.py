"""Virtual office visualization — the office's cast, and who narrates to it.

The office on screen is a picture of a build. For the picture to be worth
looking at, the people in it have to be the people who actually do the work,
standing in the department that owns their job. So the cast here is the
Blueprint agent registry (``services.blueprint.agent_contract.AGENT_REGISTRY``,
PRD §27/§30), grouped into the departments §28's DAG already implies —
requirements flow left to right, data down the left wall, experience down the
right, verification and shipping along the bottom.

Two producers narrate into it:

* the **Blueprint DAG** (``services.blueprint.orchestrator.run``), through
  :class:`OfficeNarrator`, which turns node lifecycle events into office
  events. This is the live one.
* the **legacy relay** in ``routers/generate.py``, through the
  ``*_event`` factories below. It names its agents with the old pipeline's
  vocabulary, so the factories alias those names onto this cast rather than
  making the office carry two sets of characters for one job.

Every factory returns a plain dict ready for ``sse_event("office", ...)``.
"""

from __future__ import annotations

from typing import Iterable, Optional


# ---------------------------------------------------------------------------
# Departments — the rooms of the office
# ---------------------------------------------------------------------------

#: Room id -> human label. The frontend layout mirrors this list in order; a
#: room added here needs a desk block there.
DEPARTMENTS: dict[str, str] = {
    # The person's door: Smith takes the ask, asks the open questions, and
    # comes back here to answer. Every change after the build starts here.
    "front_desk": "Front Desk",
    "discovery": "Discovery",
    "architecture": "Architecture",
    "design_studio": "Design Studio",
    "data": "Data",
    "composition": "Composition",
    "logic": "Logic",
    "security": "Security",
    "qa": "Verification",
    # The machines the application runs on, and the bench it is tried on.
    "engine_room": "Engine Room",
    "workbench": "Workbench",
    "shipping": "Shipping",
    # Where the agents a question touches meet; nobody's desk is here.
    "huddle": "Huddle Room",
}

#: Rooms people come to rather than sit in. Nobody is seated here; the agents
#: of a huddle walk in and back (`services.huddle.room`); the engine room and
#: the workbench hold machines, and Smith walks to the bench to try things.
MEETING_ROOMS: frozenset[str] = frozenset({"huddle", "engine_room", "workbench"})


#: The engines — the platform's machines, not people: what each one is for
#: and which room it stands in. The office lights one up while it is in use
#: (`engine_event`), so a build reads as agents writing AND the platform
#: running what they wrote.
ENGINES: dict[str, dict] = {
    "data_engine": {"label": "Data Engine", "room": "engine_room",
                    "does": "Reads and writes every record through the schema the Data desk projected; "
                            "resolves the analytics queries live."},
    "workflow_engine": {"label": "Workflow Engine", "room": "engine_room",
                        "does": "Runs each process's steps — guards, writes, refusals, notifications — "
                                "when a button is pressed or a schedule fires."},
    "ui_engine": {"label": "UI Engine", "room": "engine_room",
                  "does": "Renders every screen from its layout tree or its React code, against the SDK "
                          "typed from the definition."},
    "composer": {"label": "A2UI Composer", "room": "engine_room",
                 "does": "Composes a screen's layout tree from its contract when Smith is asked to recompose one."},
    "scaffold": {"label": "Render Scaffold", "room": "engine_room",
                 "does": "Renders a page as it is written, so the UI engineer sees what it made before it is accepted."},
    "apps_db": {"label": "Apps Database", "room": "workbench",
                "does": "Every application's own Postgres: pushed, seeded, and copied for each trial so "
                        "nothing tried touches real rows."},
    "workbench": {"label": "Workbench", "room": "workbench",
                  "does": "The one door to a running app: installed, schema, seeded, served, signed in — "
                          "then the browser tries every statement as the person it is about."},
}


#: Which department each Blueprint agent sits in. Keys are agent names from
#: ``blueprint.agent_contract.AGENT_REGISTRY`` — the office cast is that
#: registry, not a parallel list that can drift from it.
ROOM_OF: dict[str, str] = {
    # Discovery — what the application is for (§16, §17, §21)
    "requirement": "discovery",
    "domain_intelligence": "discovery",
    "product_analysis": "discovery",
    "smith": "front_desk",
    # Architecture — modules, navigation, the seams to the outside (§28, §60)
    "solution_architecture": "architecture",
    "integration": "architecture",
    # The engineer decides the business facts every writer reads, and owns
    # the build feature by feature: an architect's desk.
    "engineer": "architecture",
    # Design Studio — the design language, before anything composes (§37)
    "accessibility": "design_studio",
    "figma_intelligence": "design_studio",
    "page_design": "design_studio",
    "analytics": "design_studio",
    # Data — entities, the schema they become, the endpoints they imply (§28)
    "data_model": "data",
    "api": "data",
    "backend": "data",
    # Composition — the page trees A2UI authors, and the projection that turns
    # them into what the engine renders (§34)
    "page_template": "composition",
    "ui_engineer": "composition",
    "ui_director": "design_studio",
    "page_reviewer": "qa",
    "testing": "qa",
    "a2ui_pages": "composition",
    "frontend": "composition",
    # Logic — what the business does (§107 step 16)
    "workflow": "logic",
    "business_rules": "logic",
    # Security — permissions guard entities, so this sits next to Data (§100)
    "security": "security",
    # Verification — the §75 matrix, the tests, and what the run remembers
    "verification": "qa",
    # The observer (§73) sits with verification: it judges each node as it
    # lands and sends the incomplete ones back to their author.
    "observer": "qa",
    "memory": "qa",
    # Shipping — the runtime and the deploy (§56–§62)
    "build": "shipping",
    "deployment": "shipping",
}


#: What each DAG node is doing, said the way a person would say it. Used for
#: the speech bubble, so it is a sentence about the work rather than a node id.
NODE_LABEL: dict[str, str] = {
    "requirements": "Writing down what this app is for",
    "application_model": "Working out the product shape",
    "data_model": "Naming the entities",
    "entity_fields": "Detailing each entity's fields",
    "database": "Laying out the schema",
    "apis": "Deriving the endpoints",
    "backend": "Projecting the data layer",
    "ux_architecture": "Mapping modules and navigation",
    "design_system": "Setting the design language",
    "page_contracts": "Deciding the page set",
    "page_details": "Writing each feature's page contracts",
    "analytics": "Designing each page's analytics",
    "page_layouts": "Laying out each page",
    "ui_direction": "Setting the app's look and conventions",
    "page_code": "Writing each page in React",
    "figma_intelligence": "Reading the design out of Figma",
    "figma_design_system": "Turning Figma into design tokens",
    "frontend": "Projecting the page schemas",
    "workflows": "Declaring the workflows",
    "workflow_steps": "Authoring each workflow's steps",
    "app_flows": "Mapping the paths people take",
    "business_rules": "Writing the business rules",
    "security": "Setting roles and permissions",
    "integrations": "Connecting the outside services",
    "integration": "Assembling the application",
    "memory": "Recording decisions and coverage",
    "verification": "Checking the blueprint against itself",
    "assemble": "Assembling and starting the application",
    "install": "Installing the toolchain",
    "decisions": "Deciding the facts every writer must agree on",
    "content_fields": "Adding the fields the screens need",
    "auth_pages": "Declaring the sign-in screens",
    "imagery": "Finding the photographs",
    "brand_design_system": "Applying the brand",
    "expectations": "Writing what must happen, to be tried as the person",
}


#: The old relay's agent names, mapped onto this cast. Same job, older word for
#: it — so both producers move the same character instead of the office holding
#: two staffs for one office.
LEGACY_AGENT_ALIAS: dict[str, str] = {
    "planner": "product_analysis",
    "discovery": "requirement",
    "chat_refiner": "smith",
    "contract_writer": "solution_architecture",
    "navigator": "solution_architecture",
    "portal_builder": "integration",
    "schema_designer": "data_model",
    "data_modeler": "data_model",
    "seed_generator": "backend",
    "api_generator": "api",
    "auth_agent": "security",
    "rules_writer": "business_rules",
    "bizlogic_agent": "business_rules",
    "workflow_agent": "workflow",
    "component_builder": "a2ui_pages",
    "page_assembler": "a2ui_pages",
    "ui_styler": "accessibility",
    "figma_importer": "figma_intelligence",
    "qa_tester": "testing",
    "validator": "verification",
    "indexer": "memory",
    "appmodel_manager": "memory",
    "agent_builder": "memory",
    "export_agent": "deployment",
}


def office_agent(agent_id: str) -> str:
    """The office character for an agent name from either producer."""
    return LEGACY_AGENT_ALIAS.get(agent_id, agent_id)


def room_for(agent_id: str, fallback: str = "discovery") -> str:
    """The department an agent works in."""
    return ROOM_OF.get(office_agent(agent_id), fallback)


# ---------------------------------------------------------------------------
# Legacy relay phase mappings (still read by routers/generate.py)
# ---------------------------------------------------------------------------

PHASE_TO_AGENTS: dict[str, list[str]] = {
    "planning": ["planner"],
    "contract": ["contract_writer"],
    "schema": ["schema_designer"],
    "auth": ["auth_agent"],
    "api": ["api_generator"],
    "business_logic": ["bizlogic_agent"],
    "components": ["component_builder", "ui_styler"],
    "pages": ["page_assembler", "navigator"],
    "seed": ["seed_generator"],
    "qa": ["qa_tester"],
    "validation": ["validator"],
    "indexing": ["indexer"],
}

#: Kept keyed by the relay's phase names, but resolving to this office's
#: departments — the relay passes these straight into ``agent_start_event``.
PHASE_TO_ROOM: dict[str, str] = {
    phase: room_for(agents[0]) for phase, agents in PHASE_TO_AGENTS.items()
}


# ---------------------------------------------------------------------------
# Event factory helpers — each returns a plain dict ready for sse_event()
# ---------------------------------------------------------------------------

def agent_start_event(agent_id: str, room: str = "", node: str = "") -> dict:
    """An agent has started working in a room."""
    who = office_agent(agent_id)
    evt = {"type": "agent_start", "agent": who, "room": ROOM_OF.get(who, room)}
    if node:
        evt["node"] = node
    return evt


def agent_status_event(agent_id: str, status: str, progress: Optional[float] = None,
                       subject: str = "", node: str = "") -> dict:
    """Progress update for a running agent."""
    evt: dict = {"type": "agent_status", "agent": office_agent(agent_id),
                 "status": status}
    if progress is not None:
        evt["progress"] = progress
    if subject:
        evt["subject"] = subject
    if node:
        evt["node"] = node
    return evt


def agent_handoff_event(from_agent: str, to_agent: str, artifact: Optional[str] = None) -> dict:
    """One agent walks work over to another."""
    evt: dict = {"type": "agent_handoff", "from": office_agent(from_agent),
                 "to": office_agent(to_agent)}
    if artifact is not None:
        evt["artifact"] = artifact
    return evt


def artifact_delivery_event(from_agent: str, to_agent: str, artifact: str = "") -> dict:
    """A finished artifact travels to whoever is waiting on it.

    Distinct from a handoff on purpose: the office animates this as a parcel
    crossing the floor, not as the author walking it over. A DAG node feeds
    several downstream nodes at once, and having one character walk each
    delivery would leave everyone in the corridors and nobody at a desk.
    """
    return {"type": "artifact_delivery", "from": office_agent(from_agent),
            "to": office_agent(to_agent), "artifact": artifact}


def agent_error_event(agent_id: str, message: str) -> dict:
    """An agent's work failed."""
    return {"type": "agent_error", "agent": office_agent(agent_id), "message": message}


def agent_blocked_event(agent_id: str, reason: str = "") -> dict:
    """An agent cannot proceed — a missing handler, or a question it asked."""
    return {"type": "agent_blocked", "agent": office_agent(agent_id), "reason": reason}


def agent_skipped_event(agent_id: str, reason: str = "") -> dict:
    """An agent's node never ran because its inputs never arrived."""
    return {"type": "agent_skipped", "agent": office_agent(agent_id), "reason": reason}


def agent_retry_event(agent_id: str, attempt: int, of: int, reason: str = "") -> dict:
    """A rejected proposal is going round again."""
    return {"type": "agent_retry", "agent": office_agent(agent_id),
            "attempt": attempt, "of": of, "reason": reason}


def agent_complete_event(agent_id: str, files_generated: int = 0,
                         node: str = "") -> dict:
    """An agent has finished its work."""
    evt = {"type": "agent_complete", "agent": office_agent(agent_id),
           "files_generated": files_generated}
    if node:
        evt["node"] = node
    return evt


def parallel_start_event(agent_ids: list[str]) -> dict:
    """Multiple agents are starting work in parallel."""
    return {"type": "parallel_start",
            "agents": [office_agent(a) for a in agent_ids]}


def run_plan_event(agents: Iterable[str]) -> dict:
    """The roster for this run: who is on the schedule.

    The office greys out everyone who is not on it, so a five-node incremental
    run reads as five people working rather than twenty-three standing idle for
    reasons the picture cannot explain.

    No waves. The orchestrator recomputes them per round — a node that failed
    must not let its dependents into a later wave — so a schedule declared up
    front would be a claim the run does not keep.
    """
    return {"type": "run_plan",
            "agents": sorted({office_agent(a) for a in agents})}


# ---------------------------------------------------------------------------
# The pipeline, Smith and the engines — what the DAG's lines do not say
# ---------------------------------------------------------------------------

#: The stages a build moves through, in order, as the office's pipeline strip
#: shows them. `change` is Smith's after the handover.
PIPELINE_STAGES: tuple[str, ...] = (
    "define", "model", "opening", "build", "feature", "proof", "fix", "sweep", "whole", "handover",
    "stopped", "change",
)


def pipeline_stage_event(stage: str, label: str = "", **extra) -> dict:
    """Where the build is: one of `PIPELINE_STAGES`, said in a sentence, with
    whatever names it (the feature, its place in the plan, what is missing)."""
    evt = {"type": "pipeline_stage", "stage": stage, "label": label}
    evt.update({k: v for k, v in extra.items() if v is not None})
    return evt


def smith_turn_event(status: str, text: str = "", *, mode: str = "conversation", outcome: str = "") -> dict:
    """Smith begins or ends a turn: `status` is `start` or `end`; `mode` says
    whether a person is waiting (`conversation`) or the engineer sent it
    (`unattended`); `outcome` is the turn's status at the end."""
    evt = {"type": "smith_turn", "status": status, "mode": mode, "text": _short(text, 160)}
    if outcome:
        evt["outcome"] = outcome
    return evt


#: What a Smith tool is, for the office: where Smith goes to do it.
STEP_KINDS = ("read", "try", "write", "ask", "report", "end", "other")


def step_kind(tool: str) -> str:
    """`read` at the desk, `try` at the Workbench, `write` at the author's
    desk, `ask` at the front desk, `report` on the board, `end`."""
    name = (tool or "").strip()
    if name in ("ask_user", "propose_plan"):
        return "ask"
    if name in ("done", "answer"):
        return "end"
    if name == "report_platform_fault":
        return "report"
    try:
        from services.smith import tools as _tools
    except Exception:  # noqa: BLE001 — the office needs no tool registry to draw a step
        return "other"
    if _tools.is_trial(name):
        return "try"
    if _tools.is_write(name) or _tools.is_definition(name):
        return "write"
    if _tools.is_read(name) or _tools.is_web(name):
        return "read"
    return "other"


def smith_step_event(tool: str, said: str = "", status: str = "") -> dict:
    """One step of a Smith turn, with where it happens."""
    return {"type": "smith_step", "tool": tool, "kind": step_kind(tool), "status": status,
            "said": _short(said, 120)}


def trial_event(statement: str, says: str, verdict: str, who: str = "") -> dict:
    """A statement tried on the Workbench as the person it is about:
    `verdict` is `trying`, `passed`, `failed` or `not_tried`."""
    return {"type": "trial", "statement": statement, "says": _short(says, 120), "verdict": verdict, "who": who}


def engine_event(engine: str, state: str, detail: str = "") -> dict:
    """An engine's light: `busy` while it works, `on` while it serves, `off`."""
    return {"type": "engine", "engine": engine, "state": state, "detail": _short(detail, 120)}


class JournalNarrator:
    """Turn the engineer's journal into office events.

    The engineer and Smith write their work down as they go
    (`services.engineer.journal`): a turn begun, each step taken, a feature
    started and proven, a fix turn, the sweep, the whole-app check, the end.
    The office reads that account — one call site per event, as with the
    run ledger — rather than a second narration beside it."""

    def __init__(self, emit) -> None:
        self._emit = emit
        self._features: list[str] = []
        self._names: dict[str, str] = {}
        self._mode = "conversation"

    def __call__(self, row: dict) -> None:
        for evt in self.translate(row):
            self._emit(evt)

    def translate(self, row: dict) -> list[dict]:
        ev = str(row.get("event") or "")
        if ev == "turn:start":
            self._mode = "unattended" if row.get("unattended") else "conversation"
            return [smith_turn_event("start", str(row.get("message") or ""), mode=self._mode)]
        if ev == "turn:step":
            return [smith_step_event(str(row.get("tool") or ""), str(row.get("said") or ""),
                                     str(row.get("status") or ""))]
        if ev == "turn:end":
            return [smith_turn_event("end", str(row.get("said") or ""), mode=self._mode,
                                     outcome=str(row.get("status") or ""))]
        if ev == "first:start":
            nodes = [str(n) for n in row.get("nodes") or []]
            return [pipeline_stage_event("opening", "Finishing what comes before the first feature: "
                                         + ", ".join(NODE_LABEL.get(n, n).lower() for n in nodes[:4])
                                         + ("…" if len(nodes) > 4 else ""), nodes=nodes)]
        if ev == "first:failed":
            return [pipeline_stage_event("stopped", "The product model could not be finished: "
                                         + _short(row.get("why"), 120), why=_short(row.get("why"), 300))]
        if ev == "run:start":
            self._features = [str(f) for f in row.get("features") or []]
            done = [str(f) for f in row.get("done_before") or []]
            left = [f for f in self._features if f not in done]
            return [pipeline_stage_event("build", f"Building {len(left)} feature{'s' if len(left) != 1 else ''}, "
                                         f"each proven before the next", features=self._features, done=done)]
        if ev == "land:start":
            return [pipeline_stage_event("build", "Writing every screen and building the application",
                                         nodes=[str(n) for n in row.get("nodes") or []])]
        if ev == "feature:start":
            fid = str(row.get("feature") or "")
            self._names[fid] = str(row.get("name") or fid)
            index = self._features.index(fid) + 1 if fid in self._features else 0
            return [pipeline_stage_event("feature", f"Building {self._names[fid]}", feature=fid,
                                         name=self._names[fid], index=index, total=len(self._features),
                                         pages=list(row.get("pages") or []))]
        if ev == "feature:done":
            fid = str(row.get("feature") or "")
            name = self._names.get(fid, fid)
            unbuilt = list(row.get("unbuilt") or [])
            if unbuilt:
                return [pipeline_stage_event("stopped", f"{name} is not built: " + _short(unbuilt[0], 100),
                                             feature=fid, name=name, unbuilt=unbuilt)]
            n, held = int(row.get("statements") or 0), int(row.get("passed") or 0)
            said = f"{name}: {held} of {n} statements hold" if n else f"{name} is built"
            return [pipeline_stage_event("proof", said, feature=fid, name=name, statements=n, passed=held,
                                         failing=list(row.get("failing") or []), done=True)]
        if ev == "prove:start":
            feats = [str(f) for f in row.get("features") or []]
            return [pipeline_stage_event("prove", f"Trying the whole application as the people it is for "
                                         f"({len(feats)} feature{'s' if len(feats) != 1 else ''} at once)",
                                         features=feats)]
        if ev == "fix:start":
            fid = str(row.get("feature") or "")
            name = self._names.get(fid, "the whole application" if fid == "APP" else fid)
            n = len(row.get("statements") or [])
            turn = int(row.get("turn") or row.get("round") or 1)
            return [pipeline_stage_event("fix", f"{name}: {n} statement{'s' if n != 1 else ''} not holding — "
                                         f"Smith is finding the cause (turn {turn})", feature=fid, name=name,
                                         round=turn, ids=list(row.get("statements") or []))]
        if ev == "fix:stopped":
            return [pipeline_stage_event("fix", f"The fix turns stopped after {int(row.get('turns') or 0)}: "
                                         f"{row.get('why') or 'nothing more was fixed'}",
                                         turns=int(row.get("turns") or 0))]
        if ev == "mend:start":
            fid = str(row.get("feature") or "")
            name = self._names.get(fid, fid)
            nodes = [str(n) for n in row.get("nodes") or []]
            return [pipeline_stage_event("fix", f"{name}: {', '.join(NODE_LABEL.get(n, n).lower() for n in nodes)} "
                                         f"did not finish — Smith is mending it", feature=fid, name=name, nodes=nodes)]
        if ev == "sweep:start":
            return [pipeline_stage_event("sweep", "Writing what no feature claimed",
                                         nodes=[str(n) for n in row.get("nodes") or []])]
        if ev == "whole:unbuilt":
            missing = [str(m) for m in row.get("missing") or []]
            return [pipeline_stage_event("whole", "Not whole yet: " + _short("; ".join(missing), 110),
                                         missing=missing)]
        if ev == "whole:done":
            n, held = int(row.get("statements") or 0), int(row.get("passed") or 0)
            return [pipeline_stage_event("whole", f"The whole application: {held} of {n} statements hold",
                                         statements=n, passed=held, failing=list(row.get("failing") or []))]
        if ev == "run:end":
            stopped = str(row.get("stopped") or "")
            if stopped:
                return [pipeline_stage_event("stopped", _short(stopped, 140), why=stopped[:400])]
            return [pipeline_stage_event("handover", "Built, tried and handed over",
                                         state=str(row.get("state") or ""))]
        if ev in ("run:out_of_time", "run:paused"):
            return [pipeline_stage_event("stopped", "Paused: " + _short(row.get("why") or "out of time", 120))]
        return []


def build_success_event(total_files: int = 0, total_lines: int = 0) -> dict:
    """The entire build completed successfully."""
    return {"type": "build_success", "total_files": total_files, "total_lines": total_lines}


# ---------------------------------------------------------------------------
# The Blueprint DAG narrator
# ---------------------------------------------------------------------------

class OfficeNarrator:
    """Turn a run ledger's lines into office events.

    The office is a second reader of ``services.blueprint.run_ledger`` — the
    same account the run writes to disk — rather than a second narration
    threaded through the orchestrator beside it. One call site per event is
    what keeps the picture honest: a node outcome recorded by the run cannot
    be missing from the screen because somebody forgot to emit it twice.

    Stateful for one reason: a node's completion is only interesting to the
    office if somebody downstream is waiting for it, and "who is waiting" is
    the run's plan — which arrives once, in the ``plan`` line. Everything else
    is a direct translation.

    Attach it to a run::

        narrator = OfficeNarrator(emit=lambda evt: publish(pid, evt))
        run(svc, executor, observer=narrator)
    """

    def __init__(self, emit) -> None:
        self._emit = emit
        self._plan: list[str] = []
        #: node key -> the agent that owns it, from the DAG.
        self._agent_of: dict[str, str] = {}
        #: node key -> the nodes that depend on it, restricted to this plan.
        self._waiting_on: dict[str, list[str]] = {}
        #: node key -> how many artifacts it fans out over.
        self._subjects: dict[str, int] = {}

    # -- the sink ----------------------------------------------------------

    def __call__(self, line: dict) -> None:
        for office_evt in self.translate(line):
            self._emit(office_evt)

    # -- translation -------------------------------------------------------

    #: Ledger event name -> handler suffix. The ledger namespaces with a colon
    #: (``node:start``), which is not a Python identifier.
    _HANDLERS = {
        "plan": "plan",
        "node:start": "node_start",
        "node:subject": "node_subject",
        "node:retry": "node_retry",
        "node:done": "node_done",
        "node:failed": "node_failed",
        "node:blocked": "node_blocked",
        "node:skipped": "node_skipped",
        "run:end": "run_end",
        "run:crashed": "run_crashed",
    }

    def translate(self, line: dict) -> list[dict]:
        name = self._HANDLERS.get(str(line.get("event") or ""))
        if name is None:
            # `run:start` and anything the ledger grows later. The office does
            # not need to know about every line to stay correct.
            return []
        return getattr(self, f"_on_{name}")(line)

    def _agent(self, line: dict) -> str:
        """The agent that owns the node this line is about."""
        return self._agent_of.get(str(line.get("node") or ""), "")

    def _on_plan(self, line: dict) -> list[dict]:
        from services.blueprint.orchestrator import DAG

        self._plan = [k for k in (line.get("nodes") or []) if k in DAG]
        self._agent_of = {k: DAG[k].agent for k in self._plan}
        planned = set(self._plan)
        self._waiting_on = {
            k: [d for d in self._plan if k in DAG[d].depends_on and d in planned]
            for k in self._plan
        }
        self._subjects = {}
        return [run_plan_event(self._agent_of.values())]

    def _on_node_start(self, line: dict) -> list[dict]:
        node, agent = str(line.get("node") or ""), self._agent(line)
        if not agent:
            return []
        subjects = int(line.get("subjects") or 1)
        self._subjects[node] = subjects
        label = NODE_LABEL.get(node, f"Working on {node}")
        if subjects > 1:
            label = f"{label} — {subjects} to go"
        return [agent_start_event(agent, node=node),
                agent_status_event(agent, label, progress=0.0, node=node)]

    def _on_node_subject(self, line: dict) -> list[dict]:
        node, agent = str(line.get("node") or ""), self._agent(line)
        if not agent:
            return []
        index, total = int(line.get("index") or 1), int(line.get("total") or 1)
        subject = str(line.get("subject") or "")
        if total <= 1:
            # A node that authors one artifact has no progress to show through
            # it; its start and its completion say everything.
            return []
        label = NODE_LABEL.get(node, node)
        ok = bool(line.get("ok", True))
        text = f"{subject} ✓" if ok else f"{subject} ✗"
        return [agent_status_event(
            agent, f"{label} ({index}/{total}) · {text}",
            progress=index / total, subject=subject, node=node)]

    def _on_node_retry(self, line: dict) -> list[dict]:
        agent = self._agent(line)
        if not agent:
            return []
        return [agent_retry_event(
            agent, int(line.get("attempt") or 2), int(line.get("of") or 2),
            _short(line.get("reason")))]

    def _on_node_done(self, line: dict) -> list[dict]:
        node, agent = str(line.get("node") or ""), self._agent(line)
        if not agent:
            return []
        out: list[dict] = [agent_complete_event(
            agent, files_generated=int(line.get("artifacts") or 0), node=node)]
        # Everyone downstream who is on this run's plan gets a parcel.
        for downstream in self._waiting_on.get(node, []):
            to_agent = self._agent_of.get(downstream, "")
            if to_agent and to_agent != agent:
                out.append(artifact_delivery_event(agent, to_agent, node))
        return out

    def _on_node_failed(self, line: dict) -> list[dict]:
        agent = self._agent(line)
        return [agent_error_event(agent, _short(line.get("reason")))] if agent else []

    def _on_node_blocked(self, line: dict) -> list[dict]:
        agent = self._agent(line)
        return [agent_blocked_event(agent, _short(line.get("reason")))] if agent else []

    def _on_node_skipped(self, line: dict) -> list[dict]:
        agent = self._agent(line)
        if not agent:
            return []
        unmet = str(line.get("unmet") or "") or "an upstream step"
        job = NODE_LABEL.get(str(line.get("node") or ""), "that step")
        return [agent_skipped_event(agent, f"{job} — still waiting on {unmet}")]

    def _on_run_end(self, line: dict) -> list[dict]:
        if line.get("failed") or line.get("blocked"):
            # Not a shipping party. The office holds its position and the
            # failed/blocked characters keep the state they were left in.
            return [{"type": "run_complete",
                     "completed": len(line.get("completed") or []),
                     "failed": len(line.get("failed") or []),
                     "blocked": len(line.get("blocked") or []),
                     "skipped": len(line.get("skipped") or [])}]
        return [build_success_event(
            total_files=len(line.get("completed") or []))]

    def _on_run_crashed(self, line: dict) -> list[dict]:
        """The run raised out of the orchestrator. Nothing more is coming, so
        say so — otherwise the office waits for a finish that never lands."""
        return [{"type": "run_complete", "completed": 0, "failed": 1,
                 "blocked": 0, "skipped": 0,
                 "error": _short(line.get("error"))}]


def _short(text, limit: int = 90) -> str:
    """One line, short enough for a speech bubble."""
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[: limit - 1] + "…"
