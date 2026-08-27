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
  | "protesting";

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

export interface AgentStartEvent {
  type: "agent_start";
  agent: string;
  room: string;
  action?: string;
}

export interface AgentStatusEvent {
  type: "agent_status";
  agent: string;
  status: string;
  progress?: number;
}

export interface AgentHandoffEvent {
  type: "agent_handoff";
  from: string;
  to: string;
  artifact?: string;
}

export interface AgentErrorEvent {
  type: "agent_error";
  agent: string;
  message: string;
}

export interface AgentCompleteEvent {
  type: "agent_complete";
  agent: string;
  files_generated?: number;
}

export interface ParallelStartEvent {
  type: "parallel_start";
  agents: string[];
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
  | AgentErrorEvent
  | AgentCompleteEvent
  | ParallelStartEvent
  | BuildSuccessEvent
  | PhaseStartEvent
  | PhaseCompleteEvent
  | CreditsExhaustedEvent;

// ── Agent Registry ──────────────────────────────────────────────────────────

export interface AgentInfo {
  id: string;
  name: string;
  spriteKey: string;
  room: string;
  role: string;
  color: string;
}

export const AGENT_REGISTRY: AgentInfo[] = [
  { id: "planner", name: "Planner", spriteKey: "planner", room: "planning", role: "Designs app architecture", color: "#3B82F6" },
  { id: "discovery", name: "Discovery", spriteKey: "discovery", room: "planning", role: "Explores requirements", color: "#8B5CF6" },
  { id: "contract_writer", name: "Contract Writer", spriteKey: "contract_writer", room: "planning", role: "Writes specifications", color: "#1E40AF" },
  { id: "schema_designer", name: "Schema Designer", spriteKey: "schema_designer", room: "design_studio", role: "Designs database schema", color: "#059669" },
  { id: "data_modeler", name: "Data Modeler", spriteKey: "data_modeler", room: "design_studio", role: "Models data relationships", color: "#B45309" },
  { id: "auth_agent", name: "Auth Agent", spriteKey: "auth_agent", room: "security", role: "Sets up authentication", color: "#DC2626" },
  { id: "rules_writer", name: "Rules Writer", spriteKey: "rules_writer", room: "security", role: "Writes business rules", color: "#6D28D9" },
  { id: "api_generator", name: "API Generator", spriteKey: "api_generator", room: "dev_api", role: "Generates API routes", color: "#EA580C" },
  { id: "bizlogic_agent", name: "BizLogic Agent", spriteKey: "bizlogic_agent", room: "dev_logic", role: "Implements business logic", color: "#4F46E5" },
  { id: "workflow_agent", name: "Workflow Agent", spriteKey: "workflow_agent", room: "dev_logic", role: "Builds workflow engine", color: "#0369A1" },
  { id: "component_builder", name: "Component Builder", spriteKey: "component_builder", room: "dev_ui", role: "Creates UI components", color: "#EC4899" },
  { id: "page_assembler", name: "Page Assembler", spriteKey: "page_assembler", room: "dev_ui", role: "Assembles page layouts", color: "#F59E0B" },
  { id: "ui_styler", name: "UI Styler", spriteKey: "ui_styler", room: "dev_ui", role: "Styles the interface", color: "#DB2777" },
  { id: "navigator", name: "Navigator", spriteKey: "navigator", room: "dev_ui", role: "Configures navigation", color: "#15803D" },
  { id: "seed_generator", name: "Seed Generator", spriteKey: "seed_generator", room: "shipping", role: "Generates sample data", color: "#16A34A" },
  { id: "export_agent", name: "Export Agent", spriteKey: "export_agent", room: "shipping", role: "Packages for deployment", color: "#78716C" },
  { id: "qa_tester", name: "QA Tester", spriteKey: "qa_tester", room: "qa_lab", role: "Tests generated code", color: "#0891B2" },
  { id: "validator", name: "Validator", spriteKey: "validator", room: "qa_lab", role: "Validates build output", color: "#7C3AED" },
  { id: "indexer", name: "Indexer", spriteKey: "indexer", room: "library", role: "Indexes app model", color: "#92400E" },
  { id: "agent_builder", name: "Agent Builder", spriteKey: "agent_builder", room: "library", role: "Builds AI agents", color: "#BE185D" },
  { id: "portal_builder", name: "Portal Builder", spriteKey: "portal_builder", room: "dev_api", role: "Builds portal features", color: "#0E7490" },
  { id: "figma_importer", name: "Figma Importer", spriteKey: "figma_importer", room: "design_studio", role: "Imports Figma designs", color: "#A21CAF" },
  { id: "chat_refiner", name: "Chat Refiner", spriteKey: "chat_refiner", room: "planning", role: "Refines via chat", color: "#E11D48" },
  { id: "appmodel_manager", name: "AppModel Manager", spriteKey: "appmodel_manager", room: "library", role: "Manages app model index", color: "#475569" },
];

// Map phase names to room ids
export const PHASE_ROOM_MAP: Record<string, string> = {
  planning: "planning",
  discovery: "planning",
  contract: "planning",
  schema: "design_studio",
  data_model: "design_studio",
  auth: "security",
  rbac: "security",
  api: "dev_api",
  business_logic: "dev_logic",
  workflow: "dev_logic",
  components: "dev_ui",
  pages: "dev_ui",
  styling: "dev_ui",
  navigation: "dev_ui",
  seed: "shipping",
  export: "shipping",
  qa: "qa_lab",
  validation: "qa_lab",
  indexing: "library",
};

// Map agent ids to phase names
export const AGENT_PHASE_MAP: Record<string, string> = {
  planner: "planning",
  discovery: "discovery",
  contract_writer: "contract",
  schema_designer: "schema",
  data_modeler: "data_model",
  auth_agent: "auth",
  rules_writer: "rbac",
  api_generator: "api",
  bizlogic_agent: "business_logic",
  workflow_agent: "workflow",
  component_builder: "components",
  page_assembler: "pages",
  ui_styler: "styling",
  navigator: "navigation",
  seed_generator: "seed",
  export_agent: "export",
  qa_tester: "qa",
  validator: "validation",
  indexer: "indexing",
  agent_builder: "indexing",
  portal_builder: "api",
  figma_importer: "schema",
  chat_refiner: "planning",
  appmodel_manager: "indexing",
};
