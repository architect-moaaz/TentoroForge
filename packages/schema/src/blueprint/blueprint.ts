/**
 * The Living Application Blueprint.
 *
 * PRD §9–25, §33, §37–38, §90–94. This is the canonical representation of what
 * an application *is* — not generated documentation (§9). Per §115 the source of
 * truth runs:
 *
 *     Approved User Intent  →  Living Blueprint  →  Generated Implementation
 *
 * and per §120 anything that mutates application behaviour without passing
 * through this document is architecturally incorrect. That is the rule this
 * schema exists to make enforceable.
 */
import { z } from "zod";
import {
  ApiId,
  AnyArtifactId,
  ComponentId,
  Confidence,
  DecisionId,
  DeploymentId,
  EntityId,
  Evidence,
  IntegrationId,
  ModuleId,
  PageId,
  PermissionId,
  RequirementId,
  RoleId,
  RuleId,
  TestId,
  WidgetId,
  WorkflowId,
  artifactBase,
  ArtifactStatus,
} from "./ids";

// ===========================================================================
// §11 · application — identity
// ===========================================================================

export const ApplicationMeta = z.object({
  id: z.string(),
  name: z.string(),
  domain: z.string().describe("CRM | HRMS | ATS | Banking | … (§96)"),
  description: z.string().default(""),
});

// ===========================================================================
// §11 · product — purpose, personas, language
// ===========================================================================

export const Persona = z.object({
  name: z.string(),
  description: z.string().default(""),
  goals: z.array(z.string()).default([]),
});

export const Capability = z.object({
  name: z.string(),
  description: z.string().default(""),
  ...artifactBase,
});

export const Product = z.object({
  objectives: z.array(z.string()).default([]),
  personas: z.array(Persona).default([]),
  /** Domain vocabulary. Drives generated copy so labels match the business. */
  terminology: z.record(z.string(), z.string()).default({}),
  capabilities: z.array(Capability).default([]),
});

// ===========================================================================
// §11 · roles + permissions
// ===========================================================================

export const Role = z.object({
  id: RoleId,
  name: z.string(),
  description: z.string().default(""),
  permissions: z.array(PermissionId).default([]),
  ...artifactBase,
});

export const Permission = z.object({
  id: PermissionId,
  name: z.string(),
  /** What it guards: an entity, a page, an API, or a workflow. */
  subject: AnyArtifactId.optional(),
  action: z.enum(["create", "read", "update", "delete", "execute", "approve"]),
  /** Optional ownership/row-level condition, e.g. `record.ownerId == user.id`. */
  condition: z.string().optional(),
  ...artifactBase,
});

// ===========================================================================
// §11 · modules
// ===========================================================================

export const Module = z.object({
  id: ModuleId,
  name: z.string(),
  description: z.string().default(""),
  pages: z.array(PageId).default([]),
  ...artifactBase,
});

// ===========================================================================
// §33 · Page Contract — the page section of the Blueprint
// ===========================================================================

/** §39 — standardised page patterns. Constrains generation without preventing customisation. */
export const PagePattern = z.enum([
  "dashboard",
  "entity_list",
  "master_detail",
  "record_workspace",
  "wizard",
  "approval_inbox",
  "kanban",
  "calendar",
  "scheduler",
  "timeline",
  "analytics",
  "search_results",
  "configuration",
  "settings",
  "data_explorer",
  "command_center",
  "split_view",
  "document_workspace",
]);

/** §33 — every page has a structured contract *before* implementation. */
export const PageContract = z.object({
  id: PageId,
  name: z.string(),
  route: z.string().describe("URL path, e.g. /candidates or /candidates/[id]"),
  purpose: z.string().describe("Why this page exists, in business terms"),
  pattern: PagePattern.optional(),
  module: ModuleId.optional(),

  /** Roles for whom this page is meaningful. */
  /**
   * §100 — who may reach this page at all.
   *
   * Auth is a property of a page, not of an application. Some apps are
   * entirely gated (an internal tracker), some are entirely open (a marketing
   * site or a calculator), and the common case is neither: a storefront browses
   * publicly and gates checkout, a SaaS product markets publicly and gates the
   * product. The scaffold's middleware assumed "gate everything" with one
   * hardcoded matcher, which quietly makes the third case impossible.
   *
   * Defaults to `authenticated`, and the default matters: a page that is
   * accidentally public leaks data, while a page that is accidentally gated is
   * a visible annoyance someone reports. Being open has to be stated.
   */
  access: z
    .enum(["public", "authenticated", "role_restricted"])
    .default("authenticated"),

  /** Roles for whom this page is meaningful; required by `role_restricted`. */
  users: z.array(RoleId).default([]),
  /** The jobs a user comes here to do — drives composition, not decoration. */
  primaryTasks: z.array(z.string()).default([]),

  data: z
    .object({
      primaryEntity: EntityId.optional(),
      supportingEntities: z.array(EntityId).default([]),
    })
    .default({ supportingEntities: [] }),

  actions: z.array(z.string()).default([]),

  /**
   * §33 — the states a page must handle. Declaring them here is what stops
   * "empty state" and "permission denied" from being discovered later and
   * patched in by a post-generation pass.
   */
  states: z
    .array(
      z.enum(["loading", "empty", "populated", "error", "permission_denied"]),
    )
    .default(["loading", "empty", "populated", "error"]),

  responsive: z
    .object({
      desktop: z.enum(["primary", "supported", "adaptive", "unsupported"]),
      tablet: z.enum(["primary", "supported", "adaptive", "unsupported"]),
      mobile: z.enum(["primary", "supported", "adaptive", "unsupported"]),
    })
    .default({ desktop: "primary", tablet: "supported", mobile: "adaptive" }),

  /** §45 — provenance when the page came from a Figma frame. */
  figmaFrame: z.string().optional(),

  components: z.array(ComponentId).default([]),
  ...artifactBase,
});

// ===========================================================================
// §11 · navigation
// ===========================================================================

export type NavNodeT = {
  label: string;
  page?: string;
  icon?: string;
  roles?: string[];
  children?: NavNodeT[];
};

export const NavNode: z.ZodType<NavNodeT> = z.lazy(() =>
  z.object({
    label: z.string(),
    page: PageId.optional(),
    icon: z.string().optional(),
    /** Visible only to these roles; empty means all authenticated roles. */
    roles: z.array(RoleId).default([]).optional(),
    children: z.array(NavNode).default([]).optional(),
  }),
);

export const Navigation = z.object({
  style: z.enum(["sidebar", "topbar", "hybrid"]).default("sidebar"),
  tree: z.array(NavNode).default([]),
  /** Landing route per role — resolved deterministically, never guessed. */
  initialRoute: z.record(z.string(), z.string()).default({}),
});

// ===========================================================================
// §11 · components + §38 UI Registry
// ===========================================================================

export const ComponentDef = z.object({
  id: ComponentId,
  name: z.string(),
  /** Library component this maps onto (§38 registry key). */
  registryKey: z.string().optional(),
  purpose: z.string().default(""),
  /** §46 — Figma component this was derived from. */
  figmaComponent: z.string().optional(),
  ...artifactBase,
});

/** §38 — reusable UI elements available to A2UI. Reuse before invention. */
export const UiRegistry = z.object({
  components: z.array(z.string()).default([]),
  patterns: z.array(z.string()).default([]),
});


// ===========================================================================
// §34 · pattern templates — the structure A2UI authors, once per pattern
// ===========================================================================

/**
 * The closed set of holes a template may leave for the planner to fill.
 *
 * A PageContract states intent; a page schema is a node tree. Something has to
 * bridge them, and the choice is where to put the model. Composing every page
 * with an LLM is what the old platform did: cost scaled with page count, two
 * pages of the same kind came out structurally different, and the component
 * prop schemas had to be loosened to absorb the misses — `columns` arriving
 * null, `rows` being stripped, all recorded in the library's own comments.
 *
 * So the model authors *structure* (one template per pattern the app uses) and
 * a deterministic planner instantiates it per page. That only works if the
 * holes are a fixed vocabulary: an unrecognised `$whatever` is a hard failure,
 * because a placeholder the planner cannot resolve would otherwise reach the
 * renderer as a literal string.
 *
 * `{{…}}` bindings are *not* placeholders — those are the engine's own runtime
 * interpolation and pass through untouched.
 */
export const PLACEHOLDERS = [
  /** From the PageContract. */
  "$page.name",
  "$page.purpose",
  /** From the page's primary entity. */
  "$entity.name",
  "$entity.plural",
  /** Field selections the planner derives from the entity. */
  "$titleField",
  "$subtitleField",
  "$summaryFields",
  "$formFields",
  "$columns",
  /** Inside a `repeat`, the current element. */
  "$item.label",
  "$item.value",
  "$item.id",
] as const;

/** What a `repeat` may iterate. Each maps to a list the planner can build. */
export const RepeatSource = z.enum([
  /** Every action the page declares, in contract order. */
  "actions",
  /**
   * Only the actions that mutate something. A Page Contract's `actions` mixes
   * intents of different kinds — `create_role` needs a button, but
   * `filter_by_status` and `sort_by_created_at` are affordances the table
   * already provides. Repeating a toolbar over all of them yields six buttons
   * where the page wanted one.
   */
  "primaryActions",
  "widgets",
  "relatedCollections",
  "columns",
  "formFields",
  "states",
]);

/**
 * A node in a pattern template.
 *
 * Deliberately the same shape the engine renders (`type` / `props` /
 * `children`) plus `repeat`, so instantiating a template is substitution
 * rather than translation — and so a template can be validated against the
 * real component catalog before any page exists.
 */
export interface TemplateNodeShape {
  type: string;
  props?: Record<string, unknown>;
  children?: TemplateNodeShape[];
  repeat?: z.infer<typeof RepeatSource>;
  visibleIf?: string;
}

export const TemplateNode: z.ZodType<TemplateNodeShape> = z.lazy(() =>
  z.object({
    /** Must name a component in the emitted component catalog. */
    type: z.string(),
    props: z.record(z.string(), z.unknown()).default({}),
    /** Positional — the library composes with children, not named slots. */
    children: z.array(TemplateNode).default([]),
    /**
     * Emit this subtree once per element of the named list, with `$item.*`
     * bound to the element. Absent means emit exactly once.
     *
     * A bare name rather than `{ over: … }`. The wrapper carried exactly one
     * field and bought nothing, and the first author handed the contract
     * reached straight past it and wrote `repeat: "actions"` — which is the
     * shape a reader would expect. The schema was the thing that was wrong.
     */
    repeat: RepeatSource.optional(),
    /** Engine-native conditional; passed through unresolved. */
    visibleIf: z.string().optional(),
  }),
);

/**
 * One §39 page pattern, expressed against the component catalog.
 *
 * Per-app: A2UI authors a template for each distinct pattern the app's pages
 * actually use, so an ATS and a banking app can differ structurally. What they
 * cannot do is differ *within* an app — every `entity_list` page instantiates
 * the same template, which is where the consistency comes from.
 */
export const PatternTemplate = z.object({
  /** Natural key — the §39 pattern this template realises. */
  pattern: PagePattern,
  /** Why this structure, in terms of the jobs the pattern serves. */
  rationale: z.string().default(""),
  /**
   * What a page must supply for this template to instantiate. A page whose
   * contract cannot satisfy these is a planner error, not a silent empty pane.
   */
  requires: z
    .object({
      primaryEntity: z.boolean().default(false),
      widgets: z.boolean().default(false),
      relatedCollections: z.boolean().default(false),
    })
    .default({}),
  root: TemplateNode,
  ...artifactBase,
});

/**
 * A page authored in full, rather than instantiated from a pattern.
 *
 * The pattern route buys consistency and determinism: one template, every page
 * of that kind identical, a rebuild byte-for-byte the same. It pays for that
 * with fit. `record_workspace` ended up covering nine pages that were really
 * two jobs — five create/edit forms and four read-heavy workspaces — and the
 * single template it produced carried a `Form` that suited only half of them.
 *
 * So a page may instead carry its own authored tree. The trade is explicit:
 * per-page authoring costs a model call per page and gives up byte-identical
 * re-projection, and in exchange nothing is forced through a shape it does not
 * fit. What it does *not* give up is the gate — an authored tree is validated
 * against the same component catalog, the same child contracts and the same
 * prop schemas as a template. That gate is what makes this safe now and its
 * absence is what made per-page composition fail before.
 *
 * The placeholder vocabulary stays available. An author that writes
 * `$columns` gets the entity's real columns rather than its recollection of
 * them, so the mechanical parts stay correct by construction even here.
 */
export const PageLayout = z.object({
  /** Natural key — the page this tree renders. */
  page: PageId,
  /** Why this structure, for this page, in terms of what the user asked for. */
  rationale: z.string().default(""),
  root: TemplateNode,
  ...artifactBase,
});

// ===========================================================================
// §35 · widgets — the data contract behind a displayed number
// ===========================================================================

/**
 * How a widget gets its data.
 *
 * A discriminated union on ``op`` rather than a bag of optional fields, so the
 * shapes that used to need repairing cannot be written down: an ``aggregate``
 * without an aggregation, or a ``series`` without a grouping, simply fails to
 * parse. Those were `aggregate_metrics_guard` and `chart_data_source_guard`.
 */
export const Aggregation = z.enum(["count", "sum", "avg", "min", "max", "ratio"]);

/** Aggregations producing a magnitude. A magnitude shown as a percent is a
 *  fabricated number — the 1,000%-utilisation bug. */
export const MAGNITUDE_AGGREGATIONS = ["count", "sum", "min", "max"] as const;

export const ListSource = z.object({
  op: z.literal("list"),
  entity: EntityId,
  fields: z.array(z.string()).default([]),
  filter: z.record(z.string(), z.unknown()).default({}),
  sort: z.string().optional(),
  limit: z.number().int().positive().optional(),
});

export const SingleSource = z.object({
  op: z.literal("single"),
  entity: EntityId,
  filter: z.record(z.string(), z.unknown()).default({}),
});

export const AggregateSource = z.object({
  op: z.literal("aggregate"),
  entity: EntityId,
  aggregation: Aggregation,
  /** Column the aggregation runs over. Required for everything but `count`. */
  field: z.string().optional(),
  filter: z.record(z.string(), z.unknown()).default({}),
});

export const SeriesSource = z.object({
  op: z.literal("series"),
  entity: EntityId,
  aggregation: Aggregation,
  field: z.string().optional(),
  /** A series without a grouping is a single number pretending to be a chart. */
  groupBy: z.string(),
  filter: z.record(z.string(), z.unknown()).default({}),
});

export const DataSource = z.discriminatedUnion("op", [
  ListSource,
  SingleSource,
  AggregateSource,
  SeriesSource,
]);

export const WidgetKind = z.enum([
  "metric", "chart", "list", "table", "feed", "gauge", "text",
]);

/** How a value is displayed. `percent` is only honest over a ratio-producing
 *  aggregation — enforced by the Widget↔DataSource verification edge, since
 *  JSON Schema cannot express the cross-field rule. */
export const DisplayUnit = z.enum([
  "number", "currency", "percent", "duration", "date", "text",
]);

export const Widget = z.object({
  id: WidgetId,
  page: PageId,
  kind: WidgetKind,
  label: z.string(),
  /**
   * Required, deliberately. `widget_data_source_guard` existed to rebind
   * hardcoded stat and list widgets to real sources; a widget that cannot be
   * written without a source has nothing to rebind.
   */
  dataSource: DataSource,
  unit: DisplayUnit.default("number"),
  ...artifactBase,
});

// ===========================================================================
// §11 · data — entities, relationships, constraints
// ===========================================================================

export const Field = z.object({
  name: z.string(),
  type: z.string(),
  required: z.boolean().default(false),
  primaryKey: z.boolean().default(false),
  unique: z.boolean().default(false),
  enumValues: z.array(z.string()).optional(),
  /** Marks PII / financial data so security rules can act on it structurally. */
  sensitive: z.boolean().default(false),
  description: z.string().default(""),
});

export const Entity = z.object({
  id: EntityId,
  name: z.string(),
  table: z.string(),
  description: z.string().default(""),
  fields: z.array(Field).default([]),
  /** Field used as the human label in pickers, FK columns and breadcrumbs. */
  labelField: z.string().optional(),
  ...artifactBase,
});

export const Relationship = z.object({
  from: EntityId,
  to: EntityId,
  kind: z.enum(["one_to_one", "one_to_many", "many_to_many"]),
  fromField: z.string().optional(),
  toField: z.string().optional(),
  onDelete: z.enum(["cascade", "restrict", "set_null"]).default("restrict"),
});

export const Constraint = z.object({
  entity: EntityId,
  kind: z.enum(["check", "unique", "index", "foreign_key"]),
  expression: z.string(),
  description: z.string().default(""),
});

export const DataModel = z.object({
  entities: z.array(Entity).default([]),
  relationships: z.array(Relationship).default([]),
  constraints: z.array(Constraint).default([]),
});

// ===========================================================================
// §11 · workflows + business rules
// ===========================================================================

export const WorkflowStep = z.object({
  key: z.string(),
  name: z.string(),
  type: z.enum([
    "start",
    "action",
    "condition",
    "approval",
    "human_task",
    "notification",
    "timer",
    "integration",
    "end",
  ]),
  /** Entity mutation performed, if any. */
  entity: EntityId.optional(),
  next: z.array(z.string()).default([]),
  config: z.record(z.string(), z.unknown()).default({}),
});

export const Workflow = z.object({
  id: WorkflowId,
  name: z.string(),
  purpose: z.string().default(""),
  trigger: z.object({
    kind: z.enum(["manual", "event", "schedule", "condition"]),
    detail: z.string().default(""),
  }),
  steps: z.array(WorkflowStep).default([]),
  /** Pages that can launch this workflow — the wiring, declared not inferred. */
  launchedFrom: z.array(PageId).default([]),
  ...artifactBase,
});

export const BusinessRule = z.object({
  id: RuleId,
  name: z.string(),
  /** Human statement of the rule, e.g. "Expenses above ₹50,000 need approval". */
  statement: z.string(),
  /** Machine-evaluable form. */
  expression: z.string().optional(),
  appliesTo: z.array(AnyArtifactId).default([]),
  ...artifactBase,
});

// ===========================================================================
// §11 · apis + integrations
// ===========================================================================

export const ApiEndpoint = z.object({
  id: ApiId,
  method: z.enum(["GET", "POST", "PUT", "PATCH", "DELETE"]),
  path: z.string(),
  purpose: z.string().default(""),
  entity: EntityId.optional(),
  /** Permission required to call it — the §75 API↔Permission edge. */
  permission: PermissionId.optional(),
  ...artifactBase,
});

export const Integration = z.object({
  id: IntegrationId,
  name: z.string(),
  kind: z.enum(["email", "storage", "payment", "auth", "webhook", "mcp", "other"]),
  provider: z.string().default(""),
  /** Names only. §42/§99 — raw credentials never live in the Blueprint. */
  secretRefs: z.array(z.string()).default([]),
  ...artifactBase,
});

// ===========================================================================
// §11 · security  (§100)
// ===========================================================================

export const Security = z.object({
  authentication: z
    .enum(["none", "email_password", "sso", "oauth", "magic_link"])
    .default("email_password"),
  rbac: z.boolean().default(true),
  ownershipRules: z.array(z.string()).default([]),
  protectedRoutes: z.array(z.string()).default([]),
  auditLogging: z.boolean().default(false),
});

// ===========================================================================
// §37 · design system
// ===========================================================================

export const DesignSystem = z.object({
  visualPersonality: z.string().default(""),
  colors: z.record(z.string(), z.string()).default({}),
  typography: z.record(z.string(), z.string()).default({}),
  spacing: z.record(z.string(), z.string()).default({}),
  radius: z.record(z.string(), z.string()).default({}),
  borders: z.record(z.string(), z.string()).default({}),
  elevation: z.record(z.string(), z.string()).default({}),
  navigationApproach: z.string().default(""),
  informationDensity: z.enum(["compact", "comfortable", "spacious"]).default("comfortable"),
  responsiveRules: z.array(z.string()).default([]),
  accessibilityRules: z.array(z.string()).default([]),
  interactionConventions: z.array(z.string()).default([]),
  /** §47 — set when the design system was extracted from a Figma file. */
  derivedFromFigma: z.boolean().default(false),
});

// ===========================================================================
// §14–15 · requirements
// ===========================================================================

export const Requirement = z.object({
  ...artifactBase,
  id: RequirementId,
  description: z.string(),
  /** §14 — where this requirement came from. Never empty for an approved req. */
  evidence: z.array(Evidence).default([]),
  /** Overrides the optional base confidence: a requirement always has one (§15). */
  confidence: Confidence.default(0.5),
  acceptanceCriteria: z.array(z.string()).default([]),
  /** Recorded when confidence sat in the 0.70–0.90 band (§17). */
  assumption: z.string().optional(),
});

/** §15 — per-area completeness, 0..1. Drives which questions Smith asks. */
export const Completeness = z.object({
  applicationPurpose: Confidence.default(0),
  domain: Confidence.default(0),
  roles: Confidence.default(0),
  capabilities: Confidence.default(0),
  data: Confidence.default(0),
  pages: Confidence.default(0),
  workflows: Confidence.default(0),
  businessRules: Confidence.default(0),
  integrations: Confidence.default(0),
  security: Confidence.default(0),
  reporting: Confidence.default(0),
});

// ===========================================================================
// §20 · decision memory
// ===========================================================================

export const Decision = z.object({
  id: DecisionId,
  decision: z.string(),
  reason: z.string().default(""),
  source: z.enum(["user", "smith_recommendation", "domain_default", "figma"]),
  approvedBy: z.enum(["user", "smith"]).default("smith"),
  version: z.number().default(1),
  supersedes: DecisionId.optional(),
  /** §20 — future agents must respect this unless deliberately changed. */
  binding: z.boolean().default(true),
  /**
   * §22 — a decision has a lifecycle like any other artifact; `supersedes`
   * above only makes sense if it does. Every ID-bearing section carries a
   * status and the allocator stamps one on write, so omitting it here made
   * decisions the one artifact the Blueprint could not actually store.
   */
  status: ArtifactStatus.default("PROPOSED"),
});

// ===========================================================================
// §11 · tests  (§77)
// ===========================================================================

export const Test = z.object({
  id: TestId,
  name: z.string(),
  kind: z.enum([
    "unit",
    "api",
    "database",
    "integration",
    "business_rule",
    "workflow",
    "permission",
    "component",
    "smoke",
    "build",
  ]),
  /** §75 Requirement↔Test edge. */
  verifies: z.array(AnyArtifactId).default([]),
  file: z.string().optional(),
  ...artifactBase,
});

// ===========================================================================
// §11 · runtime, database, deployment  (§63, §57, §90)
// ===========================================================================

export const Runtime = z.object({
  framework: z.literal("nextjs").default("nextjs"),
  language: z.literal("typescript").default("typescript"),
  packageManager: z.string().default("npm"),
  nodeVersion: z.string().default(">=20.19"),
});

export const Database = z.object({
  engine: z.literal("postgres").default("postgres"),
  /** §89 — provider abstraction so hosting can change without a rewrite. */
  provider: z.string().default("neon"),
  migrationsApplied: z.array(z.string()).default([]),
  seeded: z.boolean().default(false),
});

export const Deployment = z.object({
  provider: z.enum(["vercel"]).default("vercel"),
  preview: z
    .object({
      status: z.enum(["stopped", "starting", "running", "failed"]).default("stopped"),
      url: z.string().optional(),
    })
    .default({ status: "stopped" }),
  production: z
    .object({
      status: z.enum(["none", "deploying", "deployed", "failed"]).default("none"),
      deploymentId: DeploymentId.optional(),
      url: z.string().optional(),
    })
    .default({ status: "none" }),
});

// ===========================================================================
// §21 · code mapping
// ===========================================================================

/**
 * Where a Blueprint concept lives in the generated source.
 *
 * This is Smith's Layer-4 memory (§8) and the substrate for impact analysis
 * (§71): given a changed requirement, the set of files to regenerate is a
 * lookup rather than a search.
 */
export const CodeMapEntry = z.object({
  artifact: AnyArtifactId,
  frontend: z.array(z.string()).default([]),
  api: z.array(z.string()).default([]),
  service: z.array(z.string()).default([]),
  test: z.array(z.string()).default([]),
  entity: EntityId.optional(),
});

// ===========================================================================
// §92 · change history
// ===========================================================================

export const ChangeRecord = z.object({
  version: z.number(),
  at: z.string().describe("ISO-8601 timestamp"),
  userRequest: z.string(),
  smithInterpretation: z.string().default(""),
  /** JSON-Patch style diff against the previous Blueprint version. */
  blueprintDiff: z.array(z.record(z.string(), z.unknown())).default([]),
  affectedArtifacts: z.array(AnyArtifactId).default([]),
  migrations: z.array(z.string()).default([]),
  tests: z.array(TestId).default([]),
  verification: z.enum(["passed", "failed", "skipped"]).default("skipped"),
  deploymentStatus: z.string().optional(),
});

// ===========================================================================
// §94 · application state machine
// ===========================================================================

export const ApplicationState = z.enum([
  "DISCOVERY",
  "CLARIFICATION",
  "DEFINITION",
  "BLUEPRINT_REVIEW",
  "PLANNING",
  "PLAN_REVIEW",
  "IMPLEMENTATION",
  "DATABASE_PROVISIONING",
  "BUILD",
  "VERIFICATION",
  "PREVIEW",
  "ITERATION",
  "READY",
  "EXPORT_DEPLOY",
  "MAINTENANCE",
]);

// ===========================================================================
// The Blueprint
// ===========================================================================

export const BLUEPRINT_SCHEMA_VERSION = "1" as const;

export const Blueprint = z.object({
  schemaVersion: z.literal(BLUEPRINT_SCHEMA_VERSION),
  /** Bumped on every accepted change (§91). Indexes into changeHistory. */
  version: z.number().int().min(1).default(1),
  state: ApplicationState.default("DISCOVERY"),

  application: ApplicationMeta,
  product: Product.default({}),

  roles: z.array(Role).default([]),
  permissions: z.array(Permission).default([]),
  modules: z.array(Module).default([]),
  pages: z.array(PageContract).default([]),
  navigation: Navigation.default({}),
  components: z.array(ComponentDef).default([]),
  widgets: z.array(Widget).default([]),

  data: DataModel.default({}),
  workflows: z.array(Workflow).default([]),
  businessRules: z.array(BusinessRule).default([]),
  apis: z.array(ApiEndpoint).default([]),
  integrations: z.array(Integration).default([]),
  security: Security.default({}),

  designSystem: DesignSystem.default({}),
  uiRegistry: UiRegistry.default({}),
  /** §34 — one per distinct page pattern the app uses. Authored by A2UI. */
  patternTemplates: z.array(PatternTemplate).default([]),
  /** §34 — pages authored individually. Takes precedence over the
   *  pattern template when both exist for a page. */
  pageLayouts: z.array(PageLayout).default([]),

  requirements: z.array(Requirement).default([]),
  completeness: Completeness.default({}),
  decisions: z.array(Decision).default([]),
  tests: z.array(Test).default([]),

  runtime: Runtime.default({}),
  database: Database.default({}),
  deployment: Deployment.default({}),
  dependencies: z.array(z.string()).default([]),

  codeMap: z.array(CodeMapEntry).default([]),
  changeHistory: z.array(ChangeRecord).default([]),
});

export type Blueprint = z.infer<typeof Blueprint>;
export type PageContract = z.infer<typeof PageContract>;
export type Requirement = z.infer<typeof Requirement>;
export type Decision = z.infer<typeof Decision>;
export type Entity = z.infer<typeof Entity>;
export type Workflow = z.infer<typeof Workflow>;
export type Widget = z.infer<typeof Widget>;
export type DataSource = z.infer<typeof DataSource>;
export type PatternTemplate = z.infer<typeof PatternTemplate>;
export type PageLayout = z.infer<typeof PageLayout>;
