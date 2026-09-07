/**
 * Page scaffolding — "New Page → Kind → (options)".
 *
 * A PURE, framework-free builder that turns a small config into a valid Page
 * schema tree. The output is fed straight to the editor's `addPage` reducer
 * action (which also creates the nav-flow entry).
 *
 * There are seven KINDS of page (see `PAGE_KINDS`). Historically this file only
 * knew how to build one of them — a form page — and the dialog's two "layout"
 * buttons (centered / full) were the only choice on offer. `LayoutPreset` still
 * means exactly what it always meant (the FORM page's wrapper), so every
 * existing call site keeps working; `kind` is the new axis and defaults to
 * `"form"` so an un-migrated caller gets byte-identical output.
 *
 * Everything here is deterministic given its inputs except node ids (random,
 * like the palette drop factory) so two scaffolds never collide. Tests inject a
 * seeded id factory for stable assertions.
 *
 * The `Form` uses DECLARATIVE mode (`props.fields`) — the field shapes match
 * the strict discriminated union in
 * `packages/library/src/components/Form/Form.schema.ts`, and the layout prop
 * values mirror the proven home.json (so the renderer never emits an
 * "invalid props" placeholder).
 *
 * ---------------------------------------------------------------------------
 * WHY the template kinds are hand-authored here rather than imported from
 * `packages/patterns/src/fragments/*`:
 *
 * Those fragments are the input to a DIFFERENT pipeline. They emit `IRNode`
 * (`{ node: "Text", typography: "heading-2" }`) which `@tentoroforge/compiler`
 * turns into TSX source files — not the Page schema v2 tree
 * (`{ type, props, children }`) that the editor store, `validateForCommit` and
 * the renderer consume. Three concrete blockers, each fatal on its own:
 *
 *   1. Vocabulary mismatch. The fragments' most load-bearing nodes — StatCard,
 *      DataTable, Repeater — are not among the 133 entries in
 *      `@forge/registry`'s starter.json, so `validateRegistryTypes` rejects
 *      them and the renderer would draw `data-unknown-node` placeholders.
 *   2. Input mismatch. Every fragment takes an `EntitySpec` (fields,
 *      capabilities, relations). The New Page dialog has a title and nothing
 *      else; there is no entity to hand them.
 *   3. `@tentoroforge/patterns` is not a dependency of `frontend/` and is
 *      imported by no other package in the repo — the import would not even
 *      resolve.
 *
 * What IS reused is their COMPOSITION: the dashboard/list/detail templates
 * below reproduce the shapes of `statTableDashboardRoot` (fragments/
 * dashboard.ts), `simpleTableRoot` (fragments/browse.ts) and `simpleDetailRoot`
 * (fragments/detail.ts) translated node-for-node into registry components.
 */

export type ScaffoldFieldKind =
  | "text"
  | "email"
  | "number"
  | "textarea"
  | "select"
  | "checkbox"
  | "date"
  | "switch";

/** A field as authored in the New Page dialog (before → Form field spec). */
export interface ScaffoldField {
  label: string;
  kind: ScaffoldFieldKind;
  required?: boolean;
}

/**
 * The FORM page's wrapper preset. Unchanged since the dialog only built form
 * pages — kept under its original name so no call site has to be migrated.
 * Ignored by every kind other than `"form"`.
 */
export type LayoutPreset = "centered" | "full";

/** What kind of page the dialog is building. */
export type PageKind =
  | "blank"
  | "form"
  | "sidebar"
  | "navbar"
  | "dashboard"
  | "list"
  | "detail";

/** One entry in a scaffolded page's navigation (sidebar rail / top nav). */
export interface ScaffoldNavItem {
  label: string;
  route: string;
}

export interface PageKindMeta {
  kind: PageKind;
  label: string;
  description: string;
  /**
   * Whether the emitted tree contains a `Form`. The dialog keys its field
   * editor off this — showing Name/Email pickers on a page that will never
   * contain a form is the original bug this file's rewrite fixes.
   */
  hasForm: boolean;
  /** Whether `config.layout` (centered / full) changes the output. */
  hasLayoutPreset: boolean;
  /** Whether the emitted tree contains NavLinks built from `config.navItems`. */
  hasNav: boolean;
  /** Dialog grouping: a bare layout you fill in, vs. a pre-populated template. */
  group: "layout" | "template";
}

/**
 * The single source of truth for what the dialog offers and which extra
 * controls each choice needs. The dialog renders from this list rather than
 * hardcoding buttons, so adding a kind here is enough to surface it.
 */
export const PAGE_KINDS: readonly PageKindMeta[] = [
  {
    kind: "blank",
    label: "Empty page",
    description: "A bare container. Drag components in from the palette.",
    hasForm: false,
    hasLayoutPreset: false,
    hasNav: false,
    group: "layout",
  },
  {
    kind: "form",
    label: "Form",
    description: "A form with the fields you choose.",
    hasForm: true,
    hasLayoutPreset: true,
    hasNav: false,
    group: "layout",
  },
  {
    kind: "sidebar",
    label: "Sidebar",
    description: "A pinned left nav rail beside the page content.",
    hasForm: false,
    hasLayoutPreset: false,
    hasNav: true,
    group: "layout",
  },
  {
    kind: "navbar",
    label: "Top nav",
    description: "A horizontal nav bar above the page content.",
    hasForm: false,
    hasLayoutPreset: false,
    hasNav: true,
    group: "layout",
  },
  {
    kind: "dashboard",
    label: "Dashboard",
    description: "Metric tiles over a recent-activity table.",
    hasForm: false,
    hasLayoutPreset: false,
    hasNav: false,
    group: "template",
  },
  {
    kind: "list",
    label: "List",
    description: "A titled table with a primary action.",
    hasForm: false,
    hasLayoutPreset: false,
    hasNav: false,
    group: "template",
  },
  {
    kind: "detail",
    label: "Detail",
    description: "A two-column record view with a summary rail.",
    hasForm: false,
    hasLayoutPreset: false,
    hasNav: false,
    group: "template",
  },
];

const KIND_META = new Map<PageKind, PageKindMeta>(PAGE_KINDS.map((k) => [k.kind, k]));

/** Metadata for a kind; falls back to `"form"` so an unknown string is safe. */
export function pageKindMeta(kind: PageKind | undefined): PageKindMeta {
  return KIND_META.get(kind as PageKind) ?? KIND_META.get("form")!;
}

export interface ScaffoldPageConfig {
  title: string;
  /** What to build. Default "form" — the historical behaviour. */
  kind?: PageKind;
  /** FORM pages only: centered card vs. full width. */
  layout?: LayoutPreset;
  fields?: ScaffoldField[];
  submitLabel?: string;
  /** Include an <h1> page heading above the content. Default true. */
  heading?: boolean;
  /** sidebar / navbar kinds: the links to put in the nav. */
  navItems?: ScaffoldNavItem[];
  /** Existing page ids + routes so the new slug is de-duplicated. */
  existingPageIds?: string[];
  existingRoutes?: string[];
  /** Injectable id factory (tests pass a deterministic one). */
  idFactory?: (type: string) => string;
}

export interface ScaffoldNode {
  id: string;
  type: string;
  props?: Record<string, unknown>;
  children?: ScaffoldNode[];
}

export interface ScaffoldedPage {
  pageId: string;
  route: string;
  title: string;
  root: ScaffoldNode;
}

/** The kinds whose Form Field variant permits a `required` flag (checkbox and
 * switch do not — the schema is `.strict()`). */
const REQUIRABLE = new Set<ScaffoldFieldKind>([
  "text",
  "email",
  "number",
  "textarea",
  "select",
  "date",
]);

const DEFAULT_FIELDS: ScaffoldField[] = [
  { label: "Name", kind: "text", required: true },
  { label: "Email", kind: "email", required: true },
];

const DEFAULT_NAV_ITEMS: ScaffoldNavItem[] = [
  { label: "Overview", route: "/" },
  { label: "Reports", route: "/" },
  { label: "Settings", route: "/" },
];

/** kebab-case slug: lowercase, non-alphanumerics → hyphens, trimmed. */
export function slugify(input: string): string {
  return (input || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .replace(/-{2,}/g, "-");
}

/** camelCase field name from a label ("First Name" → "firstName"). */
export function camelName(input: string): string {
  const parts = (input || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (parts.length === 0) return "field";
  return parts
    .map((p, i) => (i === 0 ? p : p.charAt(0).toUpperCase() + p.slice(1)))
    .join("");
}

function uniqueIn(base: string, taken: Set<string>, fallback: string): string {
  let candidate = base || fallback;
  let n = 2;
  while (taken.has(candidate)) candidate = `${base || fallback}-${n++}`;
  taken.add(candidate);
  return candidate;
}

function randomIdFactory(): (type: string) => string {
  return (type: string) =>
    `${type.toLowerCase()}-${Math.random().toString(36).slice(2, 8)}`;
}

/** Map a dialog field → the strict Form Field spec (Form.schema.ts union). */
function toFieldSpec(
  field: ScaffoldField,
  usedNames: Set<string>,
): Record<string, unknown> {
  const name = uniqueIn(camelName(field.label), usedNames, "field");
  const label = (field.label || "").trim() || name;
  const req = field.required && REQUIRABLE.has(field.kind) ? { required: true } : {};
  switch (field.kind) {
    case "text":
    case "email":
    case "number":
      return { kind: field.kind, name, label, ...req };
    case "textarea":
      return { kind: "textarea", name, label, ...req };
    case "select":
      return {
        kind: "select",
        name,
        label,
        ...req,
        options: [
          { value: "option-1", label: "Option 1" },
          { value: "option-2", label: "Option 2" },
        ],
      };
    case "checkbox":
      return { kind: "checkbox", name, label };
    case "switch":
      return { kind: "switch", name, label };
    case "date":
      return { kind: "date", name, label, ...req };
    default: {
      // Exhaustiveness guard — a new kind must be handled explicitly.
      const _never: never = field.kind;
      return { kind: "text", name, label } as Record<string, unknown>;
    }
  }
}

// ---------------------------------------------------------------------------
// Tree helpers. `nid` is threaded through every builder so a single scaffold
// draws all its ids from one factory (uniqueness is a commit-time check —
// `validateIdUniqueness` in @forge/patches rejects a page with a duplicate).
// ---------------------------------------------------------------------------

type Nid = (type: string) => string;

function node(
  nid: Nid,
  type: string,
  props?: Record<string, unknown>,
  children?: ScaffoldNode[],
): ScaffoldNode {
  const n: ScaffoldNode = { id: nid(type), type };
  if (props) n.props = props;
  if (children) n.children = children;
  return n;
}

const vstack = (nid: Nid, gap: string, children: ScaffoldNode[]): ScaffoldNode =>
  node(nid, "Stack", { direction: "vertical", gap: `tokens.spacing.${gap}` }, children);

const pageHeading = (nid: Nid, title: string): ScaffoldNode =>
  node(nid, "Heading", { content: title, level: 1 });

/** NavLinks for the sidebar / navbar kinds. `label` + `navigate` is the
 *  schema-pipeline prop pair NavLink accepts (NavLink.schema.ts); `href` is the
 *  hand-authored JSX pair and would not survive the dialog's round trip. */
function navLinks(nid: Nid, items: ScaffoldNavItem[]): ScaffoldNode[] {
  return items.map((item) =>
    node(nid, "NavLink", { label: item.label, navigate: item.route }),
  );
}

/** Placeholder table used by the list + dashboard templates. Columns are real
 *  ColumnDefs (`key` + `label`) so the Table renders headers instead of
 *  falling back to the uppercased key. */
function placeholderTable(nid: Nid, emptyText: string): ScaffoldNode {
  return node(nid, "Table", {
    columns: [
      { key: "name", label: "Name" },
      { key: "status", label: "Status", format: "badge" },
      { key: "updatedAt", label: "Updated", format: "date" },
    ],
    rows: [],
    emptyText,
  });
}

// ---------------------------------------------------------------------------
// Per-kind root builders
// ---------------------------------------------------------------------------

/** Container(lg) → Stack → [Heading?]. No form, nothing else — the user drags. */
function buildBlank(nid: Nid, title: string, heading: boolean): ScaffoldNode {
  const children = heading ? [pageHeading(nid, title)] : [];
  return node(nid, "Container", { maxWidth: "lg" }, [vstack(nid, "6", children)]);
}

/**
 * centered (default): Container(md) → Stack → [Heading?, Card → Form]
 * full:               Container(xl) → Stack → [Heading?, Form]
 *
 * Byte-for-byte the pre-`kind` output. Any change here is a regression.
 */
function buildForm(
  nid: Nid,
  title: string,
  heading: boolean,
  layout: LayoutPreset,
  fields: Array<Record<string, unknown>>,
  submitLabel: string,
): ScaffoldNode {
  const formNode: ScaffoldNode = {
    id: nid("Form"),
    type: "Form",
    props: { fields, submitLabel },
  };

  const stackChildren: ScaffoldNode[] = [];
  if (heading) {
    stackChildren.push({
      id: nid("Heading"),
      type: "Heading",
      props: { content: title, level: 1 },
    });
  }

  if (layout === "full") {
    stackChildren.push(formNode);
  } else {
    stackChildren.push({
      id: nid("Card"),
      type: "Card",
      props: { density: "regular" },
      children: [formNode],
    });
  }

  const stack: ScaffoldNode = {
    id: nid("Stack"),
    type: "Stack",
    props: { direction: "vertical", gap: "tokens.spacing.6" },
    children: stackChildren,
  };

  return {
    id: nid("Container"),
    type: "Container",
    props: { maxWidth: layout === "full" ? "xl" : "md" },
    children: [stack],
  };
}

/**
 * Sidebar(16rem) → [nav rail, main].
 *
 * `Sidebar` is the registry's own pinned-rail primitive (SidebarNode in
 * packages/schema/src/nodes/layout-v2.ts) and its contract is EXACTLY two
 * children — pane 0 is the aside, pane 1 is the main column. `width` is
 * regex-checked as `\d+(px|rem|%)`; "16rem" is used rather than "240px" so the
 * tree also passes `validateTokenClosure`'s raw-px check, which the stricter
 * `validateAll` runs at generation time.
 */
function buildSidebar(
  nid: Nid,
  title: string,
  heading: boolean,
  items: ScaffoldNavItem[],
): ScaffoldNode {
  const rail = vstack(nid, "2", navLinks(nid, items));
  const mainChildren = heading ? [pageHeading(nid, title)] : [];
  const main = vstack(nid, "6", mainChildren);
  return node(nid, "Sidebar", { width: "16rem" }, [rail, main]);
}

/** Stack → [Row(brand, links), Divider, Container → Stack → [Heading?]]. */
function buildNavbar(
  nid: Nid,
  title: string,
  heading: boolean,
  items: ScaffoldNavItem[],
): ScaffoldNode {
  const brand = node(nid, "Heading", { content: title, level: 3 });
  const links = node(
    nid,
    "Row",
    { gap: "tokens.spacing.2", align: "center" },
    navLinks(nid, items),
  );
  const bar = node(
    nid,
    "Row",
    { gap: "tokens.spacing.4", align: "center", justify: "between" },
    [brand, links],
  );
  const divider = node(nid, "Divider", { orientation: "horizontal" });
  const body = node(nid, "Container", { maxWidth: "lg" }, [
    vstack(nid, "6", heading ? [pageHeading(nid, title)] : []),
  ]);
  return vstack(nid, "4", [bar, divider, body]);
}

/**
 * Dashboard template — the shape of `statTableDashboardRoot`
 * (packages/patterns/src/fragments/dashboard.ts:13): a heading, a 4-up stat
 * grid, then a card wrapping a recent-records table. `StatCard` there becomes
 * `MetricTile` here (the registry's equivalent); values are 0 placeholders
 * because the dialog has no data source to bind to.
 */
function buildDashboard(nid: Nid, title: string, heading: boolean): ScaffoldNode {
  const tiles = ["Total", "Active", "Pending", "Archived"].map((label) =>
    node(nid, "MetricTile", { label, value: 0, format: "number" }),
  );
  const grid = node(nid, "Grid", { columns: 4, gap: "tokens.spacing.4", equalRows: true }, tiles);
  const recent = node(nid, "Card", { title: "Recent activity" }, [
    placeholderTable(nid, "No recent activity"),
  ]);
  const children = [
    ...(heading ? [pageHeading(nid, title)] : []),
    grid,
    recent,
  ];
  return node(nid, "Container", { maxWidth: "xl" }, [vstack(nid, "6", children)]);
}

/**
 * List template — the shape of `simpleTableRoot`
 * (packages/patterns/src/fragments/browse.ts:14): a header row pairing the
 * title with the primary create action, then the table.
 */
function buildList(nid: Nid, title: string, heading: boolean): ScaffoldNode {
  const headerChildren: ScaffoldNode[] = [];
  if (heading) headerChildren.push(pageHeading(nid, title));
  headerChildren.push(node(nid, "Button", { label: "New", variant: "primary" }));
  const header = node(
    nid,
    "Row",
    { gap: "tokens.spacing.4", align: "center", justify: "between" },
    headerChildren,
  );
  const table = node(nid, "Card", undefined, [placeholderTable(nid, "Nothing here yet")]);
  return node(nid, "Container", { maxWidth: "xl" }, [
    vstack(nid, "6", [header, table]),
  ]);
}

/**
 * Detail template — the shape of `simpleDetailRoot`
 * (packages/patterns/src/fragments/detail.ts:13): a back-action header over a
 * wide field area with a narrow summary rail. `Split` carries that two-column
 * intent declaratively and, like `Sidebar`, is schema-constrained to EXACTLY
 * two children (SplitNode, packages/schema/src/nodes/layout-v2.ts:6).
 */
function buildDetail(nid: Nid, title: string, heading: boolean): ScaffoldNode {
  const headerChildren: ScaffoldNode[] = [
    node(nid, "Button", { label: "Back", variant: "ghost" }),
  ];
  if (heading) headerChildren.push(pageHeading(nid, title));
  const header = node(
    nid,
    "Row",
    { gap: "tokens.spacing.3", align: "center" },
    headerChildren,
  );
  const body = node(nid, "Card", { title: "Details" }, [
    vstack(nid, "3", [
      node(nid, "Text", { content: "Field", as: "span" }),
      node(nid, "Text", { content: "—", as: "p" }),
    ]),
  ]);
  const rail = node(nid, "Card", { title: "Summary" }, [
    node(nid, "Text", { content: "—", as: "p" }),
  ]);
  const split = node(nid, "Split", { ratio: "2:1", breakpoint: "md" }, [body, rail]);
  return node(nid, "Container", { maxWidth: "xl" }, [
    vstack(nid, "6", [header, split]),
  ]);
}

/**
 * Build a complete, valid Page from a New-Page config.
 *
 * Dispatches on `config.kind` (default `"form"`). Every branch must produce a
 * tree that survives `validateForCommit` (@forge/patches) — unique ids and
 * component types that are either renderer builtins or present in
 * @forge/registry — because `addPage` silently rejects a page that doesn't.
 */
export function scaffoldPage(config: ScaffoldPageConfig): ScaffoldedPage {
  const nid = config.idFactory ?? randomIdFactory();
  const title = (config.title || "New Page").trim() || "New Page";
  const kind: PageKind = config.kind ?? "form";
  const layout: LayoutPreset = config.layout ?? "centered";
  const heading = config.heading !== false;

  // Slug shared by pageId + route, de-duplicated against everything taken.
  const taken = new Set<string>([
    ...(config.existingPageIds ?? []),
    ...(config.existingRoutes ?? []).map((r) => r.replace(/^\//, "")),
  ]);
  const base = slugify(title) || "page";
  let slug = base;
  let n = 2;
  while (taken.has(slug)) slug = `${base}-${n++}`;
  const pageId = slug;
  const route = `/${slug}`;

  const navItems =
    config.navItems && config.navItems.length > 0 ? config.navItems : DEFAULT_NAV_ITEMS;

  let root: ScaffoldNode;
  switch (kind) {
    case "blank":
      root = buildBlank(nid, title, heading);
      break;
    case "sidebar":
      root = buildSidebar(nid, title, heading, navItems);
      break;
    case "navbar":
      root = buildNavbar(nid, title, heading, navItems);
      break;
    case "dashboard":
      root = buildDashboard(nid, title, heading);
      break;
    case "list":
      root = buildList(nid, title, heading);
      break;
    case "detail":
      root = buildDetail(nid, title, heading);
      break;
    case "form":
    default: {
      const usedNames = new Set<string>();
      const sourceFields =
        config.fields && config.fields.length > 0 ? config.fields : DEFAULT_FIELDS;
      const fields = sourceFields.map((f) => toFieldSpec(f, usedNames));
      const submitLabel = (config.submitLabel || "").trim() || "Submit";
      root = buildForm(nid, title, heading, layout, fields, submitLabel);
      break;
    }
  }

  return { pageId, route, title, root };
}
