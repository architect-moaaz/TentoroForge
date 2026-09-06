import type { LucideIcon } from "lucide-react";
import {
  ScrollText,
  Landmark,
  Shield,
  Blocks,
  Layout,
  Sprout,
  SearchCheck,
  ShieldCheck,
  BookOpen,
  PenTool,
} from "lucide-react";

export interface QuestPhase {
  id: string;
  questName: string;
  statusPattern: string;
  xp: number;
  icon: LucideIcon;
}

export const QUEST_PHASES: QuestPhase[] = [
  { id: "contracts", questName: "Forge the Contracts", statusPattern: "Generating contracts", xp: 100, icon: ScrollText },
  { id: "foundation", questName: "Lay the Foundation", statusPattern: "Building foundation", xp: 150, icon: Landmark },
  { id: "backend", questName: "Conjure the Backend", statusPattern: "Generating auth", xp: 200, icon: Shield },
  { id: "components", questName: "Craft the Components", statusPattern: "Creating UI components", xp: 250, icon: Blocks },
  { id: "pages", questName: "Assemble the Pages", statusPattern: "Building pages", xp: 200, icon: Layout },
  { id: "seed", questName: "Plant the Seeds", statusPattern: "Generating seed data", xp: 100, icon: Sprout },
  { id: "qa", questName: "Trial by QA", statusPattern: "Running QA", xp: 150, icon: SearchCheck },
  { id: "validate", questName: "Validate the Build", statusPattern: "Validating build", xp: 100, icon: ShieldCheck },
  { id: "index", questName: "Chronicle the Knowledge", statusPattern: "Indexing application", xp: 50, icon: BookOpen },
];

/** Replaces the components + pages phases when the app is built from an
 *  imported design (Figma or UX Pilot): the design supplies the UI. */
export const DESIGN_UI_PHASE: QuestPhase = {
  id: "design-ui",
  questName: "Channel the Design",
  statusPattern: "",
  xp: 450,
  icon: PenTool,
};
/** @deprecated use DESIGN_UI_PHASE */
export const FIGMA_UI_PHASE = DESIGN_UI_PHASE;

export const MAX_XP = QUEST_PHASES.reduce((sum, p) => sum + p.xp, 0);

/**
 * Detect which phase index a status message corresponds to.
 * Uses String.includes() for resilient matching.
 * Returns -1 if no phase matches.
 */
export function detectPhaseIndex(statusMsg: string): number {
  return QUEST_PHASES.findIndex((phase) =>
    statusMsg.includes(phase.statusPattern),
  );
}

/**
 * Get the display phases, replacing components+pages with the design phase
 * when the app is built from an imported design.
 */
export function getDisplayPhases(isDesign: boolean): QuestPhase[] {
  if (!isDesign) return QUEST_PHASES;
  return QUEST_PHASES.filter(
    (p) => p.id !== "components" && p.id !== "pages",
  ).flatMap((p) =>
    p.id === "backend" ? [p, DESIGN_UI_PHASE] : [p],
  );
}
