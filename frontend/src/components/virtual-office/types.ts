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

export type OfficeEvent =
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
  { id: "discovery", label: "Discovery", color: "#3B82F6", description: "What the application is for" },
  { id: "architecture", label: "Architecture", color: "#0369A1", description: "Modules, navigation and the seams outward" },
  { id: "design_studio", label: "Design Studio", color: "#8B5CF6", description: "The design language, before anything composes" },
  { id: "data", label: "Data", color: "#059669", description: "Entities, schema, and the endpoints they imply" },
  { id: "composition", label: "Composition", color: "#EC4899", description: "A2UI patterns and the page trees built from them" },
  { id: "logic", label: "Logic", color: "#4F46E5", description: "Workflows and business rules" },
  { id: "security", label: "Security", color: "#DC2626", description: "Roles and the permissions that guard entities" },
  { id: "qa", label: "Verification", color: "#0891B2", description: "Tests, the verification matrix, and what the run remembers" },
  { id: "shipping", label: "Shipping", color: "#16A34A", description: "The runtime, the preview, and the deploy" },
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
  { id: "smith", name: "Smith", spriteKey: "contract_writer", room: "discovery", role: "The architect you talk to", color: "#1E40AF" },
  { id: "requirement", name: "Requirements", spriteKey: "discovery", room: "discovery", role: "Writes down what the app is for", color: "#3B82F6" },
  { id: "product_analysis", name: "Product Analyst", spriteKey: "planner", room: "discovery", role: "Works out the product shape", color: "#6366F1" },
  { id: "domain_intelligence", name: "Domain Intel", spriteKey: "chat_refiner", room: "discovery", role: "Knows how this industry works", color: "#E11D48" },

  // ── Architecture ──────────────────────────────────────────────────────
  { id: "solution_architecture", name: "Solution Architect", spriteKey: "navigator", room: "architecture", role: "Maps modules and navigation", color: "#0369A1" },
  { id: "integration", name: "Integrations", spriteKey: "portal_builder", room: "architecture", role: "Connects the outside services", color: "#0E7490" },

  // ── Design Studio ─────────────────────────────────────────────────────
  { id: "accessibility", name: "Design System", spriteKey: "ui_styler", room: "design_studio", role: "Owns the design language", color: "#DB2777" },
  { id: "page_design", name: "Page Designer", spriteKey: "page_assembler", room: "design_studio", role: "Drafts page contracts", color: "#F59E0B" },
  { id: "figma_intelligence", name: "Figma Intel", spriteKey: "figma_importer", room: "design_studio", role: "Reads evidence out of Figma", color: "#A21CAF" },

  // ── Data ──────────────────────────────────────────────────────────────
  { id: "data_model", name: "Data Modeler", spriteKey: "schema_designer", room: "data", role: "Designs entities and the schema", color: "#059669" },
  { id: "api", name: "API Derivation", spriteKey: "api_generator", room: "data", role: "Derives endpoints from the model", color: "#EA580C" },
  { id: "backend", name: "Backend Projection", spriteKey: "data_modeler", room: "data", role: "Projects the data layer", color: "#B45309" },

  // ── Composition ───────────────────────────────────────────────────────
  { id: "a2ui_pages", name: "Page Composer", spriteKey: "component_builder", room: "composition", role: "Composes a tree per page", color: "#EC4899" },
  { id: "frontend", name: "Frontend Projection", spriteKey: "seed_generator", room: "composition", role: "Projects the page schemas", color: "#16A34A" },

  // ── Logic ─────────────────────────────────────────────────────────────
  { id: "workflow", name: "Workflow", spriteKey: "workflow_agent", room: "logic", role: "Wires up the workflows", color: "#4F46E5" },
  { id: "business_rules", name: "Business Rules", spriteKey: "rules_writer", room: "logic", role: "Writes the business rules", color: "#6D28D9" },

  // ── Security ──────────────────────────────────────────────────────────
  { id: "security", name: "Security", spriteKey: "security", room: "security", role: "Sets roles and permissions", color: "#DC2626" },

  // ── Verification ──────────────────────────────────────────────────────
  { id: "testing", name: "Testing", spriteKey: "qa_tester", room: "qa", role: "Generates the tests", color: "#0891B2" },
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
