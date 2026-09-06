/**
 * Living Blueprint — identity, status and evidence primitives.
 *
 * PRD §12 (Stable Blueprint IDs), §14 (Requirement Evidence),
 * §17 (Confidence-Based Autonomy), §22 (Blueprint Artifact Status).
 *
 * These are the primitives every Blueprint section is built from. They exist
 * so that traceability (§18), the knowledge graph (§19), code mapping (§21)
 * and cross-agent verification (§75) are *structural* rather than conventional
 * — an artifact without an ID cannot be referenced, and therefore cannot be
 * silently orphaned.
 */
import { z } from "zod";

// ---------------------------------------------------------------------------
// §12 — Stable Blueprint IDs
// ---------------------------------------------------------------------------

/**
 * Every significant Blueprint object has an ID of the form `<PREFIX>-<NNN>`.
 *
 * IDs are allocated by the deterministic layer (§116) — never by an LLM — and
 * are immutable for the life of the artifact. Renaming an artifact does not
 * change its ID; that is what makes change history (§92) and impact analysis
 * (§71) able to follow an artifact across revisions.
 */
export const ID_PREFIXES = [
  "REQ", // requirement
  "ROLE", // role
  "PERM", // permission
  "MODULE", // module
  "PAGE", // page
  "CMP", // component
  "ENTITY", // data entity
  "FLOW", // workflow
  "RULE", // business rule
  "API", // api endpoint
  "TEST", // test
  "DEC", // decision
  // Not enumerated in §12 but required by sections that reference them:
  "INT", // integration (§11 integrations)
  "DEP", // deployment  (§90 shows DEP-001)
  "WIDGET", // a placed, data-bound display on a page (§35)
] as const;

export type IdPrefix = (typeof ID_PREFIXES)[number];

const idSchema = <P extends IdPrefix>(prefix: P) =>
  z
    .string()
    .regex(
      new RegExp(`^${prefix}-\\d{3,}$`),
      `must look like ${prefix}-001`,
    )
    .describe(`Stable ${prefix} identifier (§12)`);

export const RequirementId = idSchema("REQ");
export const RoleId = idSchema("ROLE");
export const PermissionId = idSchema("PERM");
export const ModuleId = idSchema("MODULE");
export const PageId = idSchema("PAGE");
export const ComponentId = idSchema("CMP");
export const EntityId = idSchema("ENTITY");
export const WorkflowId = idSchema("FLOW");
export const RuleId = idSchema("RULE");
export const ApiId = idSchema("API");
export const TestId = idSchema("TEST");
export const DecisionId = idSchema("DEC");
export const IntegrationId = idSchema("INT");
export const DeploymentId = idSchema("DEP");
export const WidgetId = idSchema("WIDGET");

/** Any Blueprint artifact reference — used by codeMap (§21) and the graph (§19). */
export const AnyArtifactId = z
  .string()
  .regex(new RegExp(`^(${ID_PREFIXES.join("|")})-\\d{3,}$`))
  .describe("Reference to any Blueprint artifact (§19)");

// ---------------------------------------------------------------------------
// §22 — Blueprint Artifact Status
// ---------------------------------------------------------------------------

/**
 * The lifecycle of a single artifact.
 *
 * `OUT_OF_SYNC` is the load-bearing one: §76 requires that Blueprint and source
 * code never *silently* diverge. When verification finds a mismatch the artifact
 * is marked OUT_OF_SYNC and surfaced — it is not quietly repaired. This is the
 * status that replaces the post-generation repair chain.
 */
export const ArtifactStatus = z.enum([
  "PROPOSED",
  "APPROVED",
  "PLANNED",
  "GENERATING",
  "IMPLEMENTED",
  "VERIFYING",
  "VERIFIED",
  "OUT_OF_SYNC",
  "FAILED",
  "DEPRECATED",
]);
export type ArtifactStatus = z.infer<typeof ArtifactStatus>;

// ---------------------------------------------------------------------------
// §14 — Requirement Evidence
// ---------------------------------------------------------------------------

/** Where a piece of knowledge came from. §14 enumerates these sources. */
export const EvidenceType = z.enum([
  "conversation",
  "document",
  "figma",
  "uxpilot",
  "screenshot",
  "spreadsheet",
  "existing_implementation",
  "smith_inference",
]);

export const Evidence = z.object({
  type: EvidenceType,
  /** Source artifact handle: document id, FIGMA-001, upload id, … */
  source: z.string().optional(),
  /** Figma node id, e.g. "220:144". */
  node: z.string().optional(),
  /** Conversation message id, e.g. "MSG-052". */
  message: z.string().optional(),
  /** Free-text locator (page number, cell range, selector). */
  locator: z.string().optional(),
});
export type Evidence = z.infer<typeof Evidence>;

// ---------------------------------------------------------------------------
// §17 — Confidence-Based Autonomy
// ---------------------------------------------------------------------------

export const Confidence = z
  .number()
  .min(0)
  .max(1)
  .describe("0..1 confidence in this artifact (§17)");

/**
 * §17 decision policy, expressed as data so the orchestrator can enforce it
 * rather than each agent re-implementing the thresholds.
 *
 *   > 0.90        → Smith may decide automatically
 *   0.70 – 0.90   → proceed, but record an assumption
 *   0.40 – 0.70   → ask the user where behaviour is materially affected
 *   < 0.40        → do not implement without clarification
 */
export const AUTONOMY_BANDS = {
  autoDecide: 0.9,
  recordAssumption: 0.7,
  askUser: 0.4,
} as const;

export const AutonomyAction = z.enum([
  "auto_decide",
  "record_assumption",
  "ask_user",
  "block",
]);

export function autonomyFor(confidence: number): z.infer<typeof AutonomyAction> {
  if (confidence > AUTONOMY_BANDS.autoDecide) return "auto_decide";
  if (confidence >= AUTONOMY_BANDS.recordAssumption) return "record_assumption";
  if (confidence >= AUTONOMY_BANDS.askUser) return "ask_user";
  return "block";
}

// ---------------------------------------------------------------------------
// Artifact base
// ---------------------------------------------------------------------------

/**
 * Fields every significant Blueprint artifact carries.
 *
 * `requirements` is the traceability edge (§18). Storing it once, at the
 * artifact, means the Application Knowledge Graph (§19) is *derived* rather
 * than maintained separately — there is no second structure to fall out of
 * sync with the first.
 */
export const artifactBase = {
  status: ArtifactStatus.default("PROPOSED"),
  /** Requirements this artifact exists to satisfy (§18). */
  requirements: z.array(RequirementId).default([]),
  /** Decisions that constrain this artifact (§20). */
  decisions: z.array(DecisionId).default([]),
  confidence: Confidence.optional(),
  /** Set when status is OUT_OF_SYNC or FAILED — what verification found (§76). */
  syncNote: z.string().optional(),
};
