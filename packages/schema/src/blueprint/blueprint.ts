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
  /**
   * The language this application is written in, as a BCP-47 tag.
   *
   * §11 has always listed language beside purpose and personas and nothing
   * carried it: `<html lang="en">` is hardcoded in the scaffold, the composer
   * is called with `locale=en`, and every generated label is English. A brief
   * asking for an Arabic-first platform produced an English one and said
   * nothing about it.
   *
   * Defaults to "en" because that is what every existing application is, and
   * a default of "unknown" would make each of them look like a question.
   */
  locale: z
    .string()
    .describe(
      "BCP-47 tag for the language the INTERFACE is written in — 'ar', " +
      "'ar-PS', 'fr'. Set it when the request says what language the UI " +
      "should be in; every string a reader sees is then authored in it and " +
      "the document is laid out right-to-left where the script requires. A " +
      "country, currency or market is not a language. Defaults to 'en'.",
    )
    .default("en"),
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
  // A CREATE OR EDIT SCREEN, which this enum could not name. The note below on
  // per-page authoring already records the cost: `record_workspace` covered
  // nine pages that were really two jobs, five of them create/edit forms.
  // `page_planner.ENTITY_SLOTS` has always called the create slot `form`, so
  // the deterministic planner emitted a pattern the contract rejected, and the
  // authoring agent — which can only pick from this list — labelled every
  // create page `record_workspace` and was then handed the record job:
  // "This screen shows ONE record in detail", for a page that exists to
  // collect one. `wizard` is the multi-step case and is not the same thing.
  "form",
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

  /**
   * Whether this page is where its audience arrives.
   *
   * An application has as many front doors as it has audiences, and `access`
   * already says which audience a page serves — so the entry is per-access,
   * not one global landing page. A survey tool has two: the author signs in
   * and lands on a dashboard, while a respondent follows a link straight to
   * `/survey/[slug]` and must never meet a login screen or an app shell for a
   * product they cannot reach.
   *
   * Nothing recorded this, so every consumer guessed. `nav-flow.json` had no
   * entry at all; the error page's "back to the application" link took the
   * first route in the list and produced `/survey/[slug]` — a route PATTERN,
   * which Next refuses as an href and which threw at runtime. That was fixed
   * by refusing to link a pattern, which treated the symptom: the real fault
   * is that the gated entry was never stated, and a gated entry is by
   * definition a concrete URL.
   */
  entry: z
    .boolean()
    .default(false)
    .describe("This page is where its audience (see `access`) arrives"),

  /**
   * The pages this page leads to — the arrows, not the list.
   *
   * `nav-flow.json` has carried a `transitions` field since it was written and
   * the projection has always emitted `[]`, so navigation was an index of six
   * pages with no statement of how anyone moves between them. A list of pages
   * is not a flow: it cannot answer "where does Add Survey go", cannot render
   * a breadcrumb, and gives §113's Blueprint↔Preview linking nothing to link
   * along.
   *
   * Page ids rather than routes, so a route rename does not silently break
   * every arrow pointing at it.
   */
  navigatesTo: z
    .array(PageId)
    .default([])
    .describe("Pages reachable from this one, by id"),

  /**
   * What must already be true for this page to mean anything.
   *
   * An approval screen is not a page you can look at; it is a page you can
   * look at once something has been submitted. Against an empty or freshly
   * seeded application it renders its empty state, and every reviewer of it —
   * a person, a screenshot, a vision critique — sees a correct rendering of
   * nothing and has no way to tell that from the page being broken.
   *
   * The contract had no way to say this. `states` is the render states
   * (loading, empty, populated, error) and `dispatches` is the workflow this
   * page *launches*, not one it waits on. So a page could not declare its own
   * precondition, and anything wanting to satisfy one had to guess: run
   * workflows until something looked right, or infer a state from a field
   * being called `status`. Both are the guessing this architecture exists to
   * refuse, and neither is checkable.
   *
   * Said here, it is checkable. Verification can ask whether the state is one
   * the entity actually declares and whether `producedBy` is a workflow that
   * exists; the preview sweep can open the page against a record in that state
   * rather than whichever row came back first, and say precisely what is
   * missing when there is none.
   *
   * Only for a page that genuinely has one. Most pages do not: a list is a
   * list whether or not anything has happened yet, and declaring a
   * precondition it does not have makes it unreviewable for no reason.
   */
  requires: z
    .object({
      entity: EntityId.describe("The entity a record must exist of"),
      state: z
        .string()
        .describe(
          "The value that record must hold — one of the entity's own " +
            "enumValues, not a state invented here",
        ),
      producedBy: WorkflowId.optional().describe(
        "The workflow that puts a record into that state, when one does. " +
          "Without it the precondition can be checked and waited on but not " +
          "satisfied.",
      ),
    })
    .optional()
    .describe(
      "A precondition this page needs before it shows anything (§107). " +
        "Omit unless the page genuinely has one.",
    ),

  /**
   * How this page is shown when something opens it.
   *
   * A detail view is not always a route. "Click the row, see the record in a
   * side panel" and "click the row, go to a page" are different applications,
   * and the contract could only express the second — so every detail became a
   * route with its own schema, its own URL and a full navigation away from the
   * list the user was reading.
   *
   * `page` stays the default because a URL is shareable and a drawer is not;
   * being modal has to be chosen.
   */
  presentation: z
    .enum(["page", "drawer", "modal"])
    .default("page")
    .describe("page = its own route; drawer/modal = opened over the caller"),

  /**
   * Saved views over this page's data — the same list, filtered differently.
   *
   * Without this a filtered variant has nowhere to live, so the only way to
   * express "recruiters need to see overdue jobs" is another page. A workshop
   * tracker came back with `/jobs`, `/jobs/mine`, `/jobs/unassigned`,
   * `/jobs/overdue`, `/jobs/ready-for-collection` and
   * `/jobs/awaiting-decision` — six routes, one list, six page authorings.
   * The component library could always do this: `FilterBar.savedViews` and
   * `SavedViewsPicker` exist and went unused because the contract had no way
   * to ask for them.
   *
   * A page earns its route when it has a different job, a different primary
   * entity, or a different audience. A different filter over the same list is
   * a view.
   */
  views: z
    .array(
      z.object({
        /** Stable within the page; becomes the saved view's id. */
        key: z.string(),
        /** What a user calls it: "Overdue", "Assigned to me". */
        label: z.string(),
        /**
         * Field -> value the list is narrowed by.
         *
         * String values, because that is what `FilterBar.savedViews[].filters`
         * accepts — a boolean here validates in the Blueprint and is rejected
         * at render, which is the split that has cost most of the debugging on
         * this path. Write "true", not true.
         */
        filter: z.record(z.string(), z.string()).default({}),
        /** The view shown when the page opens, if any. */
        isDefault: z.boolean().default(false),
      }),
    )
    .default([]),
  /**
   * The workflow this page starts, when it starts one.
   *
   * Not inferable from the workflow's steps. `Bike Drop-off Intake` begins by
   * searching for the owner and registering a Customer, so its first mutating
   * step names Customer while the page that starts it is `/jobs/new` — a rule
   * over step order binds the drop-off wizard to whichever flow happens to
   * touch Job first. The workflow knows its own entry point and says so in
   * prose ("started from the New Drop-off wizard (/jobs/new)"), which no later
   * stage can read.
   *
   * Declared here because the agent writing the page contract already knows
   * which process it opens. A form on this page dispatches it on submit; the
   * button that navigates here does not, since a twelve-step intake needs the
   * fields filled first.
   */
  dispatches: WorkflowId.optional(),

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
  /** The saved views this page declares — one control per view. */
  "views",
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
/**
 * One fetch this page's tree binds to.
 *
 * Carried on the layout rather than re-derived at projection time. The
 * composer's binder rewrites each pointer into a `{{name}}` and emits the
 * source behind it in the same pass, so it is the only place the tree and its
 * fetches are known together. Re-deriving them from the tree meant matching
 * binding names against entity names, which kept `plants` and silently dropped
 * four aggregate counts and two further lists — and shipped the tree that read
 * all seven, so a real page rendered the literal text "{{overdue.value}}".
 */
export const PageDataSource = z.object({
  name: z.string(),
  entity: z.string(),
  /**
   * WHAT THE APPLICATION CAN ACTUALLY FETCH. This was list|get|aggregate, and
   * `series` — the grouped aggregate every chart binds to — was missing.
   *
   * Measured on a real 50-page application: 130 committed dataSources and not
   * one `series`. `schema_prompt.ts`'s CHART DATA block instructs the page
   * author to emit exactly {op:"series", groupBy, bucket, agg}, the runtime
   * has a full resolver for it (SeriesSource in data-engine.ts), eight modules
   * produce it, and `PageDataSource` right here refused it:
   *
   *   BlueprintInvalid: pageLayouts/36/dataSources/4:
   *     Additional properties are not allowed ('agg', 'groupBy' were unexpected)
   *
   * The pipeline asked for a shape and then refused it, and the page carrying
   * it was lost — four of fourteen 404ing routes on that application. It is
   * also why `dashboard_no_chart` could not be satisfied by composing better:
   * a dashboard cannot have a chart if a chart's source cannot be committed.
   *
   * `../page.ts` has described the full shape all along; this is the second
   * copy, and it fell behind. Kept narrower than that one on purpose — the
   * Blueprint requires name+entity+op and does not carry the mutation ops —
   * so the two are not merged, but the read ops must agree.
   */
  op: z.enum(["list", "get", "aggregate", "series"]),
  filter: z.record(z.unknown()).optional(),
  metrics: z.record(z.unknown()).optional(),
  limit: z.number().int().optional(),
  orderBy: z.record(z.unknown()).optional(),
  /** op:"series" — the GROUP BY column. Ignored when agg.fn is running_sum. */
  groupBy: z.string().optional(),
  /** Set when groupBy is a date/timestamp column. */
  bucket: z.enum(["day", "week", "month"]).optional(),
  agg: z
    .object({
      fn: z.enum(["count", "sum", "avg", "min", "max", "running_sum"]),
      field: z.string().optional(),
    })
    .optional(),
  /** Order column for running_sum only; defaults to createdAt. */
  orderByCol: z.string().optional(),
  sort: z.enum(["label", "value"]).optional(),
});

export const PageLayout = z.object({
  /** Natural key — the page this tree renders. */
  page: PageId,
  /** Why this structure, for this page, in terms of what the user asked for. */
  rationale: z.string().default(""),
  root: TemplateNode,
  /** The fetches `root` binds to, as the composer's binder resolved them. */
  dataSources: z.array(PageDataSource).default([]),
  /**
   * Which composer produced this tree.
   *
   * Two can: A2UI, and the LLM page author that runs when A2UI declines or
   * fails. They emit the same shape, so a page nobody could compose properly
   * and a page composed well were indistinguishable in the Blueprint —
   * answerable only from run logs, which age out. §76 asks for divergence to
   * be legible, and "who designed this screen" is exactly that question.
   *
   * The same argument removed the deterministic pattern stub: a stubbed page
   * and a designed one looking alike was judged unacceptable. This closes the
   * remaining half of it.
   *
   * Empty on layouts written before this was recorded, which is honest — it
   * means unknown, not "the fallback".
   *
   * `deterministic` names a composer that NO LONGER EXISTS.
   * `blueprint/landing_page` assembled the entry point from the navigation
   * tree when nothing else composed it. It was deleted: it ran once against a
   * real Blueprint, emitted props no component has, and turned one dead route
   * into an application that would not compile — and a second composer is a
   * second answer to "what does this screen look like", which is the argument
   * that removed the deterministic pattern stub already.
   *
   * THE WORD STAYS. Documents written while it existed carry it, and every
   * commit validates the whole document — so dropping the value would refuse
   * every later write to those projects, on a section nobody is touching.
   * That failure has already cost this codebase two separate investigations
   * (`runtime.placeholders`, and this very field before it knew the word).
   *
   * An enum here is a vocabulary for what WAS written, not only for what can
   * be written now.
   */
  // `figma` — built from the frame it was designed as, rather than composed
  // from the catalog. A page carrying `figmaFrame` takes this route and
  // every other page takes A2UI, so the two are genuinely different
  // provenance and the distinction is worth keeping: a screen that came
  // from a drawing and a screen a model invented are not the same claim.
  composedBy: z
    .enum(["a2ui", "agent", "deterministic", "figma", ""])
    .default(""),
  /**
   * The Figma frame's own size, for a layout composed from one. `FigmaCanvas`
   * scales the page by (available width / frame width) and reads it off the
   * projected schema; the executor carries it here from the composer. Absent
   * for every A2UI page and for a frame with no recorded size — and, until it
   * was declared, present-but-forbidden: fifteen of fifteen layout rows were
   * refused as "'canvas' was unexpected" on the first run that wrote it.
   */
  canvas: z
    .object({
      width: z.number().positive(),
      height: z.number().positive(),
      // How the frame meets a viewport narrower than itself. `fluid`: the
      // page reflows — a drawn box is a maximum, not a size — which is what
      // an auto-layout frame supports. `scale`: the frame is a positioned
      // picture and shrinks as one. Absent means `scale`, the older behaviour.
      fit: z.enum(["scale", "fluid"]).optional(),
    })
    .optional(),
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
  /**
   * The entity this field points at, when it is a foreign key.
   *
   * Relations were real but unwritten: PartUsage carried `jobId: uuid` with
   * "Job the part was consumed on." in its description and nothing structural,
   * so every consumer re-derived them from the `Id` suffix or from English.
   * The page planner could not tell PartUsage — a row only ever written while
   * looking at a job — from Customer, and gave both a full list/detail/create
   * feature. Six of thirty-two pages on one run existed for records nobody
   * navigates to.
   *
   * Declaring it makes "reachable only through another entity" a fact rather
   * than an inference, which the seed order, cascade rules and the Data Engine
   * all currently guess at too.
   */
  references: EntityId.optional(),
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

/**
 * A step IS a workflow node — one of the components the editor's palette
 * offers and the runtime executes. The vocabulary is the workflow node catalog
 * (`packages/catalog/workflow-nodes.json`); a step's `config` carries what
 * that node declares it needs (`actionType` for an action, `expression` for a
 * condition, `assignType`/`assignTarget` for a human task, …) alongside any
 * Blueprint references. The workflow's own `trigger` is the start; an `end`
 * step is the terminal.
 */
export const WORKFLOW_NODE_TYPES = [
    "trigger",
    "action",
    "condition",
    "exclusive_gateway",
    "parallel_gateway",
    "fork",
    "join",
    "decision",
    "wait",
    "end",
    "end_event",
    "user_task",
    "assignment",
    "approval",
    "task_pool",
    "escalation",
    "ai_classify",
    "ai_extract",
    "ai_decide",
    "ai_generate",
] as const;

export const WorkflowStep = z.object({
  key: z.string(),
  name: z.string(),
  type: z.enum(WORKFLOW_NODE_TYPES),
  /** Entity mutation performed, if any. */
  entity: EntityId.optional(),
  /** Keys this step hands to. On a branching node the first is the then-branch, the second the else-branch. */
  next: z.array(z.string()).default([]),
  /**
   * Free-form per-step settings, EXCEPT `sets`, which has a consumer.
   *
   * `projection.project_workflows` reads `config.sets` as column-to-value pairs
   * — it is where a workflow states what a person never types, `status: "Open"`
   * — and called `.items()` on it. Nothing typed it, so one run emitted all 56
   * as lists of prose (`["status = in_triage", "lastActionAt = now"]`), which
   * validated against `z.unknown()`, raised AttributeError, and killed the
   * `integration` node along with thirty workflow definitions and `testing`
   * downstream.
   *
   * Scalars, because a column holds one value; the constraint that matters is
   * that this is a MAP and not a list. Typing the values as strings instead
   * rejected 33 existing Blueprints on `closedAt: null` and `isCurrent: true`,
   * which is what those columns actually hold.
   */
  config: z
    .object({
      sets: z
        .record(
          z.string(),
          z.union([z.string(), z.number(), z.boolean(), z.null()]),
        )
        .optional(),
    })
    .catchall(z.unknown())
    .default({}),
});

export const Workflow = z.object({
  id: WorkflowId,
  name: z.string(),
  purpose: z.string().default(""),
  trigger: z.object({
    /** A trigger variant from the workflow node catalog. */
    kind: z.enum(["manual", "webhook", "schedule", "api_event", "db_change"]),
    detail: z.string().default(""),
  }),
  steps: z.array(WorkflowStep).default([]),
  /** Pages that can launch this workflow — the wiring, declared not inferred. */
  launchedFrom: z.array(PageId).default([]),
  /**
   * What the workflow needs to start. A control that runs it must supply
   * every required input from what its page has in scope — the record a
   * detail page shows, the fields a form collects — and the composer refuses
   * a control that cannot. Undeclared, nothing could be checked: a button on
   * a case page sent `{}` and the first step failed to find the case.
   */
  inputs: z.array(z.object({
    name: z.string().min(1),
    kind: z.enum(["record", "field"]),
    /** For a record input: the entity whose record is needed. */
    entity: EntityId.optional(),
    /** For a field input: string, number, boolean, date, enum, text, … */
    type: z.string().optional(),
    required: z.boolean().default(true),
    description: z.string().default(""),
  })).default([]),
  ...artifactBase,
});

/**
 * What a rule does when its condition holds. The same actions the rules
 * panel authors and the runtime applies: a form effect (show or hide,
 * require, lock, narrow the options of a field), a value (set, default,
 * clear), a refusal (show_error), or a side effect.
 */
export const RuleAction = z.object({
  type: z.enum([
    "set_field", "set_default", "clear_field", "show_error",
    "set_visibility", "set_required", "set_readonly", "set_options",
    "recommendation", "trigger_workflow", "send_notification",
  ]),
  field: z.string().optional(),
  valueMode: z.enum(["literal", "field", "formula"]).optional(),
  value: z.string().optional(),
  message: z.string().optional(),
  visible: z.boolean().optional(),
  required: z.boolean().optional(),
  readonly: z.boolean().optional(),
  /** set_options: the options the field offers while the condition holds. */
  options: z.array(z.object({ value: z.string(), label: z.string() })).optional(),
  workflow: WorkflowId.optional(),
});

export const BusinessRule = z.object({
  id: RuleId,
  name: z.string(),
  /** Human statement of the rule, e.g. "Expenses above ₹50,000 need approval". */
  statement: z.string(),
  /** Machine-evaluable form. */
  expression: z.string().optional(),
  appliesTo: z.array(AnyArtifactId).default([]),
  /**
   * A rule with effects. `kind: "condition_action"` names the entity whose
   * form it governs, a FEEL condition over that entity's fields, and what
   * happens when it holds (and, optionally, when it does not). Projected
   * into the runtime's rules directory beside the panel's own rules, so a
   * rule the agent authored fires on the form exactly as one a person
   * authored. A rule with only a statement is prose; it constrains people,
   * not forms.
   */
  kind: z.enum(["statement", "condition_action"]).default("statement"),
  entity: EntityId.optional(),
  when: z.string().optional(),
  then: z.array(RuleAction).default([]),
  otherwise: z.array(RuleAction).default([]),
  scope: z.enum(["entity", "form", "server"]).default("form"),
  salience: z.number().int().default(0),
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

/**
 * An enforceable rule about one column and the acting user. Projected into
 * `src/lib/ownership-rules.ts`, which the data engine reads — so this object,
 * not the prose beside it, is what actually takes effect.
 *
 * Both kinds set the column server-side on create. Only `scope` filters:
 * an `attribution` column records who acted and is never an access filter,
 * which is what an application with agency-wide visibility needs.
 */
export const RecordScopeRule = z.object({
  /** Entity name or table, as spelled in `data.entities`. */
  entity: z.string().describe(
    "Entity name or table this governs, as spelled in data.entities.",
  ),
  /** Column holding the actor's value (`ownerId`, `createdByUserId`, …). */
  column: z.string().describe(
    "Column on that entity holding the actor's value, e.g. ownerId, workspaceId or createdByUserId.",
  ),
  /**
   * `scope` — the column decides who may reach the row: set on create and
   * added as a WHERE predicate to every read and write.
   * `attribution` — the column only records who acted: set on create, a body
   * value ignored, never used to filter.
   */
  kind: z
    .enum(["scope", "attribution"])
    .describe(
      '"scope": the column decides who may reach the row — it is set from the ' +
      "session on create AND becomes a WHERE predicate on every read and write. " +
      '"attribution": the column only records who acted — it is set from the ' +
      "session on create and a value in the request body is ignored, but it is " +
      "NEVER used as an access filter. Choose attribution wherever every holder " +
      "of a role is meant to see every row; scoping on an audit column silently " +
      "narrows an application that was designed to be shared.",
    )
    .default("scope"),
  /** The actor's own id, or the workspace/tenant id their session carries. */
  scope: z
    .enum(["user", "workspace"])
    .describe(
      "What `column` is compared to: the acting user's own id, or the " +
      "workspace/tenant id their session carries.",
    )
    .default("user"),
  /** Roles exempt from the rule — they read unscoped, and may write the column. */
  unscopedRoles: z
    .array(z.string())
    .describe(
      "Role names that read and write this entity unscoped. Name a role only " +
      "where the product genuinely grants it every row.",
    )
    .default([]),
  note: z.string().describe("Why this rule exists, in one sentence.").default(""),
}).describe(
  "An enforceable rule about one column and the acting user. A `scope` rule " +
  "limits which rows the actor reaches; an `attribution` rule only records who " +
  "acted. Both set the column server-side on create.",
);

export const Security = z.object({
  authentication: z
    .enum(["none", "email_password", "sso", "oauth", "magic_link"])
    .default("email_password"),
  rbac: z.boolean().default(true),
  /**
   * A string states policy and enforces nothing; a {@link RecordScopeRule}
   * is enforced. An entity with no rule is readable by every authenticated
   * user — correct when authorisation is by role rather than by record, and
   * a leak otherwise.
   */
  ownershipRules: z
    .array(
      z.union([
        z.string().describe(
          "Prose statement of an access rule. Documents policy; enforces nothing.",
        ),
        RecordScopeRule,
      ]),
    )
    .describe(
      "Who may reach which rows. A plain string is a prose statement of policy — " +
      "it documents the rule but nothing enforces it. An object is an enforceable " +
      "record-scoping rule: it is projected into src/lib/ownership-rules.ts and the " +
      "data engine adds it as a WHERE predicate to every read and write of that " +
      "entity, so declaring one here is what actually scopes the rows. An entity " +
      "with no object rule is readable by every authenticated user, which is " +
      "correct for an application whose authorisation is by role rather than by " +
      "record — say so in a string rule so the absence is a decision rather than " +
      "an omission.",
    )
    .default([]),
  protectedRoutes: z.array(z.string()).default([]),
  auditLogging: z.boolean().default(false),
});

// ===========================================================================
// §37 · design system
// ===========================================================================

/**
 * §41–§45 — a design the user connected, recorded so citations into it resolve.
 *
 * The design itself is not here. A Figma extraction carries generated TSX per
 * screen and a rendered PNG per frame; §91 snapshots the whole Blueprint on
 * every accepted change, so putting it in the document would copy megabytes
 * into every version and pollute every `blueprintDiff` (§92). It lives beside
 * the Blueprint, and this is the record that says which file it was.
 *
 * What this *does* carry is what the rest of the document needs to make sense:
 * §14 evidence cites `source: "FIGMA-001"`, and `PageContract.figmaFrame`
 * names a node id. Neither means anything without knowing which file the id
 * belongs to. That is this record's job.
 */
export const DesignSourceFrame = z.object({
  nodeId: z.string(),
  name: z.string(),
  /** False for covers, icon sheets and styleguide boards — recorded rather
   *  than filtered, because the naming convention is the file author's, not
   *  ours, and a wrong guess silently deletes evidence (§49). */
  looksLikeScreen: z.boolean().default(true),
  /**
   * What the frame shows, read off its own heading with the shared chrome
   * removed. Fifteen frames of one real file all carried the same name, so
   * the planner routed them by position: the Ticket Queue became `/login`,
   * Front Desk became `/cases`, Policy Manager `/users/new` — 14 of 15 wrong.
   * A frame's heading is its identity; this is the evidence the planner
   * routes by (§48, §49).
   */
  shows: z.string().optional(),
});

export const DesignSource = z.object({
  /** `FIGMA-001`. Its own sequence — a design source is evidence, not a
   *  Blueprint artifact, so it is deliberately outside ID_PREFIXES. */
  id: z.string().regex(/^FIGMA-\d{3,}$/),
  type: z.literal("figma").default("figma"),
  fileKey: z.string(),
  /** Set when the user linked one frame rather than the whole file (§41). */
  nodeId: z.string().optional(),
  url: z.string().default(""),
  name: z.string().default(""),
  extractedAt: z.string().default(""),
  frames: z.array(DesignSourceFrame).default([]),
  /**
   * WHETHER THIS DESIGN IS EVIDENCE OR THE SPECIFICATION.
   *
   * §48 is right that a design is normally evidence: a screen proves a
   * capability is reachable and says nothing about who may use it or what
   * happens when it is refused. That is `evidence`, and it stays the default —
   * one connected dashboard legitimately implies a sign-in, the lists behind
   * its numbers, and the forms that create them.
   *
   * `specification` is the other thing a person means: build these screens and
   * no others. `page_planner.page_slots` then asks its question frame by frame
   * instead of entity by entity, so the answer space is the design rather than
   * the cross-product of the data model.
   *
   * Its own docstring is why this is a source property and not a heuristic:
   * pruning was considered and rejected because "the obvious signals do not
   * discriminate" — every entity carries requirements, and matching names
   * against the description is "string-matching a heuristic into a rule". A
   * frame list is neither. It is an enumeration the user connected on purpose.
   *
   * Per source, because a project may connect a specification and a reference
   * and mean different things by them.
   */
  treatAs: z.enum(["evidence", "specification"]).default("evidence"),
  /** §102 — what the design could not answer, so a thin reference looks thin
   *  instead of passing for a complete one. Each is a clarification owed to
   *  the user before the DAG builds against it (§48, §50). */
  gaps: z.array(z.string()).default([]),
  /**
   * What every screen of this design shares — its chrome — read as evidence
   * (§48). The rail is the same subtree on every frame; `services/figma/chrome`
   * finds it by that definition and records what it says here, in the order
   * the designer drew it. `ux_architecture`, the one author of
   * `navigation.tree`, reads this and reproduces it; before it existed every
   * Figma application got the generic sidebar with the drawn one rendered
   * inside each page.
   *
   * Absent for a design with one frame, or frames that share nothing.
   */
  chrome: z
    .object({
      sidebar: z.object({
        brand: z.array(z.string()).default([]),
        groups: z
          .array(
            z.object({
              label: z.string().default(""),
              items: z
                .array(
                  z.object({
                    label: z.string(),
                    navigate: z.string().optional(),
                    workflow: z.string().optional(),
                  }),
                )
                .default([]),
            }),
          )
          .default([]),
      }),
      /** How many screens the rail was found on. */
      sharedBy: z.number().int().nonnegative(),
    })
    .optional(),
});

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
  /**
   * Why each frame-derived token was chosen: the number of times the frames
   * use it. Present only when the file published no variables and the
   * scheme was counted off the frames instead (§49 — an inference carries
   * its evidence). `background: 74` beside `#f7f3eb` lets a reader see the
   * ground was the ground and not a guess.
   */
  paletteEvidence: z.record(z.string(), z.number()).optional(),
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

/**
 * §25 + §95 — a user approval at one of the four gates.
 *
 * Deliberately not a `Decision`. §20 decisions are constraints on the
 * application that future agents must respect ("use left navigation, because
 * there are multiple modules"); an approval is a fact about the process ("the
 * user saw the definition at version 3 and accepted it"). Filing approvals in
 * `decisions` would make every gate crossing a binding design constraint, and
 * artifacts cite decisions by id — a page would end up citing a consent event
 * as its rationale.
 *
 * `digest` is what makes the record mean anything. Without it "approved" is
 * unfalsifiable: the Blueprint moves on and the approval still reads as
 * current. With it, an approval whose digest no longer matches what the
 * Blueprint now says is *stale*, and §76's rule that the document must not
 * silently diverge from what was agreed applies to consent too.
 */
export const ApprovalGate = z.enum([
  "understanding", // §95 Gate 1 — is this what you want to build?
  "blueprint",     // §95 Gate 2 — are the modules, users and behaviour right?
  "plan",          // §95 Gate 3 — should Smith proceed with this build?
  "deployment",    // §95 Gate 4 — the checks passed; deploy?
]);

export const Approval = z.object({
  gate: ApprovalGate,
  /** §25's three answers: accept, modify, discuss. */
  outcome: z.enum(["accepted", "changes_requested", "discussed"]),
  /** Blueprint version this answer was given against (§91). */
  version: z.number().int().min(1),
  at: z.string().describe("ISO-8601 timestamp"),
  /** Stable hash of exactly what was shown. See the note above. */
  digest: z.string().default(""),
  /** The message the user answered with, in the transcript (§14). */
  message: z.string().default(""),
  /** What they asked to change, when the outcome was `changes_requested`. */
  note: z.string().default(""),
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
  /**
   * What happened the last time the application was assembled — the install
   * and build exit codes and a verdict (§70).
   *
   * The `preview` projection has written this since it was built and the
   * contract did not declare it, so `additionalProperties: false` rejected
   * every Blueprint the engine produced. The document was written by the
   * engine and refused by the engine: the next `save()` raised, which made a
   * generated application permanently unmodifiable — Smith's move died before
   * it started, on every project.
   */
  build: z
    .object({
      install: z.number().optional(),
      build: z.number().optional(),
      status: z.string().optional(),
    })
    .optional(),
  /**
   * Substitution markers still in the assembled tree, `[]` when none.
   *
   * THE SAME OMISSION AS `build`, one field along. `_project_preview` has
   * written this since it was added and the contract never declared it, so
   * every Blueprint carrying it failed validation on the next `save()` —
   * five generated applications in `output/` are unmodifiable for this reason
   * alone, and the error names `placeholders` rather than the projection that
   * wrote it.
   */
  placeholders: z.array(z.string()).optional(),
  /**
   * Planned pages against pages the application actually serves (§72).
   *
   * A run that plans N pages and ships fewer reports success: composition
   * fails per subject, every projection downstream faithfully projects what
   * survived, `next build` compiles it, and the missing routes are found by a
   * person clicking on them. Two real builds went 53 -> 27 and 38 -> 23 that
   * way. Recorded on every run, `complete` included — a missing key would mean
   * the check did not run, which is a different fact from no shortfall.
   */
  pages: z
    .object({
      planned: z.number(),
      served: z.number(),
      missing: z.array(z.string()).default([]),
      status: z.enum(["complete", "short"]),
    })
    .optional(),
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

  /** §41–§45 — designs the user connected. Empty for a prompt-only app,
   *  which is also what tells the orchestrator there is no Figma work to do. */
  designSources: z.array(DesignSource).default([]),
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
  /** §25/§95 — what the user was shown at each gate, and what they answered. */
  approvals: z.array(Approval).default([]),
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
