// ── Virtual Office Type Definitions ──────────────────────────────────────────

export type Direction = "down" | "left" | "right" | "up";

export type AgentVisualState =
  | "idle"
  | "walking"
  | "working"
  | "reading"
  | "handoff"
  | "error"
  | "celebrating"
  | "waiting"
  | "protesting"
  // ── Blueprint DAG outcomes ───────────────────────────────────────────────
  // A DAG node ends one of five ways, and only two of them were drawable
  // before: it ran, it failed. The other three are the ones you actually need
  // to see, because they are the ones that explain a half-finished app.
  | "retrying" // a proposal was refused; the agent is going round again
  | "blocked" // it asked a question, or nothing here can do the job
  | "skipped"; // its inputs never arrived, so it never started

export interface Position {
  x: number;
  y: number;
}

export interface AgentCharacterState {
  id: string;
  name: string;
  spriteKey: string;
  room: string;
  state: AgentVisualState;
  position: Position;
  targetPosition?: Position;
  path?: Position[];
  direction: Direction;
  speechBubble?: string;
  speechBubbleType?: "normal" | "error" | "success";
  progress?: number;
  animFrame: number;
  onArrival?: () => void;
  /** The DAG node this agent is currently running, e.g. `page_layouts`. */
  node?: string;
  /** Fan-out position: `{ done, total }` while authoring one artifact per
   *  subject. Drawn as a stamp counter over the desk. */
  tally?: { done: number; total: number };
  /** Retry attempt, while `state === "retrying"`. */
  attempt?: { n: number; of: number };
}

export interface Room {
  id: string;
  label: string;
  x: number;
  y: number;
  w: number;
  h: number;
  floorTile: string;
  furniture: FurniturePlacement[];
  machines: MachinePlacement[];
  desks: DeskPosition[];
  color: string;
  description: string;
}

export interface DeskPosition {
  x: number;
  y: number;
  agentId: string;
  facing: Direction;
}

export interface FurniturePlacement {
  type: string;
  x: number;
  y: number;
}

/** An engine's machine, placed in its room (tile coords local to the room). */
export interface MachinePlacement {
  engine: string;
  x: number;
  y: number;
}

export interface OfficeLayout {
  width: number;
  height: number;
  tileSize: number;
  rooms: Room[];
  paths: Position[];
  lobby: Position;
}

export interface SpriteManifest {
  tiles: Record<string, string>;
  furniture: Record<string, string>;
  characters: Record<string, string>;
  characters_idle: Record<string, string>;
  characters_working: Record<string, string>;
  characters_walk: Record<string, string>;
  effects: Record<string, string>;
}

export interface Camera {
  x: number;
  y: number;
  zoom: number;
  targetX: number;
  targetY: number;
  targetZoom: number;
  following?: string; // agent id to auto-follow
}

// ── SSE Event Types ─────────────────────────────────────────────────────────
//
// Two producers write these. The Blueprint DAG
// (`services/blueprint/orchestrator.py`) narrates through
// `services/office_events.py`'s OfficeNarrator; the legacy relay in
// `routers/generate.py` emits the same vocabulary directly. Both name agents
// with the ids in AGENT_REGISTRY below — the backend aliases the relay's older
// names on the way out, so the office only ever has one cast.

export interface AgentStartEvent {
  type: "agent_start";
  agent: string;
  room: string;
  action?: string;
  node?: string;
}

export interface AgentStatusEvent {
  type: "agent_status";
  agent: string;
  status: string;
  progress?: number;
  /** The artifact this call is for, when the node fans out (e.g. `PAGE-009`). */
  subject?: string;
  node?: string;
}

export interface AgentHandoffEvent {
  type: "agent_handoff";
  from: string;
  to: string;
  artifact?: string;
}

/** A finished artifact travelling to whoever was waiting on it.
 *
 *  Deliberately not a handoff: a DAG node feeds several downstream nodes at
 *  once, and having the author walk each delivery over would leave everyone in
 *  the corridors and nobody at a desk. The office flies a parcel instead. */
export interface ArtifactDeliveryEvent {
  type: "artifact_delivery";
  from: string;
  to: string;
  artifact?: string;
}

export interface AgentErrorEvent {
  type: "agent_error";
  agent: string;
  message: string;
}

export interface AgentBlockedEvent {
  type: "agent_blocked";
  agent: string;
  reason?: string;
}

export interface AgentSkippedEvent {
  type: "agent_skipped";
  agent: string;
  reason?: string;
}

export interface AgentRetryEvent {
  type: "agent_retry";
  agent: string;
  attempt: number;
  of: number;
  reason?: string;
}

export interface AgentCompleteEvent {
  type: "agent_complete";
  agent: string;
  files_generated?: number;
  node?: string;
}

export interface ParallelStartEvent {
  type: "parallel_start";
  agents: string[];
}

/** The roster for this run. Everyone not on it is greyed out and stays at
 *  their desk, so a five-node incremental change reads as five people working
 *  rather than eighteen standing around for reasons the picture can't show. */
export interface RunPlanEvent {
  type: "run_plan";
  agents: string[];
  levels?: string[][];
}

export interface RunCompleteEvent {
  type: "run_complete";
  completed?: number;
  failed?: number;
  blocked?: number;
  skipped?: number;
}

export interface BuildSuccessEvent {
  type: "build_success";
  total_files?: number;
  total_lines?: number;
}

export interface PhaseStartEvent {
  type: "phase_start";
  phase: string;
  message?: string;
}

export interface PhaseCompleteEvent {
  type: "phase_complete";
  phase: string;
}

export interface CreditsExhaustedEvent {
  type: "credits_exhausted";
  message?: string;
}

/** The agents a question touches meet in the Huddle Room; the observer chairs
 *  (`backend/services/huddle/room.py`). */
export interface HuddleStartEvent {
  type: "huddle_start";
  huddleId: string;
  kind: "review" | "deadlock";
  topic: string;
  participants: string[];
  chair: string;
}

/** One agent's position, said at the table. */
export interface HuddleSayEvent {
  type: "huddle_say";
  huddleId: string;
  agent: string;
  text: string;
  participants: string[];
  chair: string;
}

/** The chair's decision — or the question for the person — and back to work. */
export interface HuddleEndEvent {
  type: "huddle_end";
  huddleId: string;
  status: "decided" | "deadlock";
  decision: string;
  participants: string[];
  chair: string;
}

/** Where the build is — the engineer's journal, read by the office
 *  (`backend/services/office_events.py`'s JournalNarrator). */
export interface PipelineStageEvent {
  type: "pipeline_stage";
  stage: string;
  label: string;
  feature?: string;
  name?: string;
  index?: number;
  total?: number;
  features?: string[];
  pages?: string[];
  done?: string[] | boolean;
  statements?: number;
  passed?: number;
  failing?: string[];
  missing?: string[];
  unbuilt?: string[];
  nodes?: string[];
  why?: string;
  [extra: string]: unknown;
}

/** Smith begins or ends a turn — a person waiting, or the engineer's fix. */
export interface SmithTurnEvent {
  type: "smith_turn";
  status: "start" | "end";
  mode: "conversation" | "unattended";
  text: string;
  outcome?: string;
}

/** One step of a Smith turn: where Smith goes to do it. */
export interface SmithStepEvent {
  type: "smith_step";
  tool: string;
  kind: "read" | "try" | "write" | "ask" | "report" | "end" | "other";
  status: string;
  said: string;
}

/** A statement tried on the Workbench as the person it is about. */
export interface TrialEvent {
  type: "trial";
  statement: string;
  says: string;
  verdict: "trying" | "passed" | "failed" | "not_tried";
  who: string;
}

/** An engine's light: busy while it works, on while it serves, off. */
export interface EngineEvent {
  type: "engine";
  engine: string;
  state: "busy" | "on" | "off";
  detail?: string;
}

export type OfficeEvent =
  | PipelineStageEvent
  | SmithTurnEvent
  | SmithStepEvent
  | TrialEvent
  | EngineEvent
  | HuddleStartEvent
  | HuddleSayEvent
  | HuddleEndEvent
  | AgentStartEvent
  | AgentStatusEvent
  | AgentHandoffEvent
  | ArtifactDeliveryEvent
  | AgentErrorEvent
  | AgentBlockedEvent
  | AgentSkippedEvent
  | AgentRetryEvent
  | AgentCompleteEvent
  | ParallelStartEvent
  | RunPlanEvent
  | RunCompleteEvent
  | BuildSuccessEvent
  | PhaseStartEvent
  | PhaseCompleteEvent
  | CreditsExhaustedEvent;

// ── Departments ─────────────────────────────────────────────────────────────
//
// The rooms, in the order §28's DAG walks them: what the app is for, then how
// it is shaped, then the two branches that build it (data down the left,
// experience down the right), then what checks and ships it. Mirrors
// `DEPARTMENTS` in `backend/services/office_events.py` — the two must agree on
// ids, because the backend puts agents in rooms by name.

export interface Department {
  id: string;
  label: string;
  color: string;
  description: string;
}

export const DEPARTMENTS: Department[] = [
  { id: "front_desk", label: "Front Desk", color: "#0EA5E9", description: "The person's door: Smith takes the ask, asks what is open, answers, and brings every change in here" },
  { id: "discovery", label: "Discovery", color: "#3B82F6", description: "What the application is for" },
  { id: "architecture", label: "Architecture", color: "#0369A1", description: "Modules, navigation and the seams outward" },
  { id: "design_studio", label: "Design Studio", color: "#8B5CF6", description: "The design language, before anything composes" },
  { id: "data", label: "Data", color: "#059669", description: "Entities, schema, and the endpoints they imply" },
  { id: "composition", label: "Composition", color: "#EC4899", description: "The page trees and the schemas projected from them" },
  { id: "logic", label: "Logic", color: "#4F46E5", description: "Workflows and business rules" },
  { id: "security", label: "Security", color: "#DC2626", description: "Roles and the permissions that guard entities" },
  { id: "qa", label: "Verification", color: "#0891B2", description: "The observer judging every step, the statements of what must happen, and what the run remembers" },
  { id: "engine_room", label: "Engine Room", color: "#475569", description: "The machines the application runs on: data, workflows, screens" },
  { id: "workbench", label: "Workbench", color: "#CA8A04", description: "The one door to a running app, where every statement is tried as the person it is about" },
  { id: "shipping", label: "Shipping", color: "#16A34A", description: "The runtime, the preview, and the deploy" },
  { id: "huddle", label: "Huddle Room", color: "#B45309", description: "Where the agents a question touches settle it together" },
];

export const DEPARTMENT_BY_ID: Record<string, Department> = Object.fromEntries(
  DEPARTMENTS.map((d) => [d.id, d]),
);

// ── Agent Registry ──────────────────────────────────────────────────────────

export interface AgentInfo {
  id: string;
  name: string;
  spriteKey: string;
  room: string;
  role: string;
  color: string;
}

// The cast is the Blueprint agent registry
// (`backend/services/blueprint/agent_contract.py`), seated in the department
// that owns its §30 capability. `spriteKey` still points at the older sprite
// filenames — those are pictures of people, not job titles, so renaming the
// job does not need new art.
//
// Two keys in `characters/idle/` are not usable: `auth_agent.png` is a machine
// rather than a person, and `indexer.png` is a character and a portal in one
// wide image, which the renderer squashes into a square. Neither is referenced
// here. `security` and `inspector` have no idle frame at all, which the
// renderer's sprite fallback covers from the working and base sheets.
export const AGENT_REGISTRY: AgentInfo[] = [
  // ── Discovery ─────────────────────────────────────────────────────────
  { id: "smith", name: "Smith", spriteKey: "contract_writer", room: "front_desk", role: "The one you talk to: takes the ask, reproduces what you report as you, and fixes it through the right desk", color: "#1E40AF" },
  { id: "requirement", name: "Requirements", spriteKey: "discovery", room: "discovery", role: "Writes down what the app is for", color: "#3B82F6" },
  { id: "product_analysis", name: "Product Analyst", spriteKey: "planner", room: "discovery", role: "Works out the product shape", color: "#6366F1" },
  { id: "domain_intelligence", name: "Domain Intel", spriteKey: "chat_refiner", room: "discovery", role: "Knows how this industry works", color: "#E11D48" },

  // ── Architecture ──────────────────────────────────────────────────────
  { id: "solution_architecture", name: "Solution Architect", spriteKey: "navigator", room: "architecture", role: "Maps modules and navigation", color: "#0369A1" },
  { id: "engineer", name: "Engineer", spriteKey: "farmer", room: "architecture", role: "Decides the facts every writer agrees on, then builds the app one feature at a time and proves each before the next", color: "#15803D" },
  { id: "integration", name: "Integrations", spriteKey: "portal_builder", room: "architecture", role: "Connects the outside services", color: "#0E7490" },

  // ── Design Studio ─────────────────────────────────────────────────────
  { id: "accessibility", name: "Design System", spriteKey: "ui_styler", room: "design_studio", role: "Owns the design language", color: "#DB2777" },
  { id: "page_design", name: "Page Designer", spriteKey: "page_assembler", room: "design_studio", role: "Drafts page contracts", color: "#F59E0B" },
  { id: "figma_intelligence", name: "Figma Intel", spriteKey: "figma_importer", room: "design_studio", role: "Reads evidence out of Figma and UX Pilot", color: "#A21CAF" },

  // ── Data ──────────────────────────────────────────────────────────────
  { id: "data_model", name: "Data Modeler", spriteKey: "schema_designer", room: "data", role: "Designs entities and the schema", color: "#059669" },
  { id: "api", name: "API Derivation", spriteKey: "api_generator", room: "data", role: "Derives endpoints from the model", color: "#EA580C" },
  { id: "backend", name: "Backend Projection", spriteKey: "data_modeler", room: "data", role: "Projects the data layer", color: "#B45309" },

  // ── Composition ───────────────────────────────────────────────────────
  { id: "ui_director", name: "Design Director", spriteKey: "detective", room: "design_studio", role: "Sets the whole app's look and conventions", color: "#BE185D" },
  { id: "testing", name: "Testing", spriteKey: "qa_tester", room: "qa", role: "Generates the tests", color: "#0891B2" },
  { id: "page_reviewer", name: "Page Reviewer", spriteKey: "scientist", room: "qa", role: "Looks at each page as it renders and sends weak ones back", color: "#0D9488" },
  { id: "ui_engineer", name: "UI Engineer", spriteKey: "artist", room: "composition", role: "Writes each page in React and compiles it", color: "#E11D48" },
  { id: "page_template", name: "Page Layout", spriteKey: "agent_builder", room: "composition", role: "Lays out each page from its contract", color: "#DB2777" },
  { id: "a2ui_pages", name: "Page Composer", spriteKey: "component_builder", room: "composition", role: "Recomposes a screen Smith is asked to change", color: "#EC4899" },
  { id: "frontend", name: "Frontend Projection", spriteKey: "seed_generator", room: "composition", role: "Projects the page schemas", color: "#16A34A" },

  // ── Logic ─────────────────────────────────────────────────────────────
  { id: "workflow", name: "Workflow", spriteKey: "workflow_agent", room: "logic", role: "Wires up the workflows", color: "#4F46E5" },
  { id: "analytics", name: "Analytics", spriteKey: "mechanic", room: "data", role: "Designs the numbers and charts each page carries", color: "#B45309" },
  { id: "business_rules", name: "Business Rules", spriteKey: "rules_writer", room: "logic", role: "Writes the business rules", color: "#6D28D9" },

  // ── Security ──────────────────────────────────────────────────────────
  { id: "security", name: "Security", spriteKey: "security", room: "security", role: "Sets roles and permissions", color: "#DC2626" },

  // ── Verification ──────────────────────────────────────────────────────
  { id: "observer", name: "Observer", spriteKey: "appmodel_manager", room: "qa", role: "Judges each step as it lands and chairs the huddles", color: "#0F766E" },
  { id: "verification", name: "Verification", spriteKey: "validator", room: "qa", role: "Checks the blueprint against itself", color: "#7C3AED" },
  { id: "memory", name: "Memory", spriteKey: "inspector", room: "qa", role: "Records decisions and coverage", color: "#92400E" },

  // ── Shipping ──────────────────────────────────────────────────────────
  { id: "build", name: "Build", spriteKey: "export_agent", room: "shipping", role: "Builds the preview", color: "#78716C" },
  { id: "deployment", name: "Deployment", spriteKey: "bizlogic_agent", room: "shipping", role: "Ships it", color: "#15803D" },
];

export const AGENT_BY_ID: Record<string, AgentInfo> = Object.fromEntries(
  AGENT_REGISTRY.map((a) => [a.id, a]),
);

// ── Legacy relay phase mapping ──────────────────────────────────────────────
//
// The relay still emits `phase_start` / `phase_complete` with the old
// pipeline's phase names. Both maps below translate those onto this cast, so
// one office serves both producers.

export const PHASE_ROOM_MAP: Record<string, string> = {
  planning: "discovery",
  discovery: "discovery",
  contract: "architecture",
  navigation: "architecture",
  schema: "data",
  data_model: "data",
  api: "data",
  seed: "data",
  styling: "design_studio",
  auth: "security",
  rbac: "security",
  business_logic: "logic",
  workflow: "logic",
  components: "composition",
  pages: "composition",
  qa: "qa",
  validation: "qa",
  indexing: "qa",
  export: "shipping",
};

export const AGENT_PHASE_MAP: Record<string, string> = {
  smith: "planning",
  requirement: "discovery",
  product_analysis: "planning",
  domain_intelligence: "discovery",
  solution_architecture: "contract",
  integration: "navigation",
  accessibility: "styling",
  page_design: "pages",
  figma_intelligence: "styling",
  data_model: "schema",
  api: "api",
  backend: "seed",
  a2ui_pages: "pages",
  frontend: "components",
  workflow: "workflow",
  business_rules: "business_logic",
  security: "auth",
  testing: "qa",
  verification: "validation",
  memory: "indexing",
  build: "export",
  deployment: "export",
};


// ── Engines ─────────────────────────────────────────────────────────────────
//
// The platform's machines, not people. Mirrors `ENGINES` in
// `backend/services/office_events.py`: the backend lights them by id.

export interface EngineInfo {
  id: string;
  label: string;
  room: string;
  does: string;
  color: string;
  kind: "engine" | "db" | "bench";
}

export const ENGINES: EngineInfo[] = [
  { id: "data_engine", label: "Data Engine", room: "engine_room", kind: "engine", color: "#059669",
    does: "Reads and writes every record through the schema the Data desk projected; resolves the analytics queries live." },
  { id: "workflow_engine", label: "Workflow Engine", room: "engine_room", kind: "engine", color: "#4F46E5",
    does: "Runs each process's steps — guards, writes, refusals, notifications — when a button is pressed or a schedule fires." },
  { id: "ui_engine", label: "UI Engine", room: "engine_room", kind: "engine", color: "#EC4899",
    does: "Renders every screen from its layout tree or its React code, against the SDK typed from the definition." },
  { id: "composer", label: "A2UI Composer", room: "engine_room", kind: "engine", color: "#8B5CF6",
    does: "Composes a screen's layout tree from its contract when Smith is asked to recompose one." },
  { id: "scaffold", label: "Render Scaffold", room: "engine_room", kind: "engine", color: "#F59E0B",
    does: "Renders a page as it is written, so the UI engineer sees what it made before it is accepted." },
  { id: "apps_db", label: "Apps Database", room: "workbench", kind: "db", color: "#0EA5E9",
    does: "Every application's own Postgres: pushed, seeded, and copied for each trial so nothing tried touches real rows." },
  { id: "workbench", label: "Workbench", room: "workbench", kind: "bench", color: "#CA8A04",
    does: "The one door to a running app: installed, schema, seeded, served, signed in — then the browser tries every statement as the person it is about." },
];

export const ENGINE_BY_ID: Record<string, EngineInfo> = Object.fromEntries(
  ENGINES.map((e) => [e.id, e]),
);

/** Which engines a DAG node runs, so they light while the node works. */
export const NODE_ENGINES: Record<string, string[]> = {
  backend: ["data_engine"],
  integration: ["workflow_engine"],
  frontend: ["ui_engine"],
  page_layouts: ["composer"],
  page_code: ["scaffold", "ui_engine"],
  assemble: ["data_engine", "workflow_engine", "ui_engine", "apps_db"],
};

// ── The pipeline ────────────────────────────────────────────────────────────
//
// The stages a build moves through, as the strip above the floor shows them.
// `proof` and `fix` happen inside a feature; `change` is Smith's after the
// handover.

export interface PipelineStep {
  id: string;
  label: string;
  stages: string[];
}

export const PIPELINE: PipelineStep[] = [
  { id: "define", label: "Define", stages: ["define"] },
  { id: "model", label: "Model", stages: ["model"] },
  { id: "opening", label: "Opening", stages: ["opening"] },
  { id: "features", label: "Features", stages: ["build", "feature", "proof", "fix"] },
  { id: "sweep", label: "Sweep", stages: ["sweep"] },
  { id: "whole", label: "Whole app", stages: ["whole"] },
  { id: "handover", label: "Handover", stages: ["handover"] },
];
