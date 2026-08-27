/**
 * Page scaffolding — "New Page → Layout → Form".
 *
 * A PURE, framework-free builder that turns a small config into a valid Page
 * schema tree: a LAYOUT wrapper (Container → Stack, optionally a Card) that
 * contains a declarative `Form`. The output is fed straight to the editor's
 * `addPage` reducer action (which also creates the nav-flow entry).
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

export type LayoutPreset = "centered" | "full";

export interface ScaffoldPageConfig {
  title: string;
  layout?: LayoutPreset;
  fields?: ScaffoldField[];
  submitLabel?: string;
  /** Include an <h1> page heading above the form. Default true. */
  heading?: boolean;
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

/**
 * Build a complete, valid Page from a New-Page config.
 *
 * centered (default): Container(md) → Stack → [Heading?, Card → Form]
 * full:               Container(xl) → Stack → [Heading?, Form]
 */
export function scaffoldPage(config: ScaffoldPageConfig): ScaffoldedPage {
  const nid = config.idFactory ?? randomIdFactory();
  const title = (config.title || "New Page").trim() || "New Page";
  const layout: LayoutPreset = config.layout ?? "centered";

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

  // Declarative form.
  const usedNames = new Set<string>();
  const sourceFields =
    config.fields && config.fields.length > 0 ? config.fields : DEFAULT_FIELDS;
  const fields = sourceFields.map((f) => toFieldSpec(f, usedNames));
  const submitLabel = (config.submitLabel || "").trim() || "Submit";
  const formNode: ScaffoldNode = {
    id: nid("Form"),
    type: "Form",
    props: { fields, submitLabel },
  };

  const stackChildren: ScaffoldNode[] = [];
  if (config.heading !== false) {
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

  const root: ScaffoldNode = {
    id: nid("Container"),
    type: "Container",
    props: { maxWidth: layout === "full" ? "xl" : "md" },
    children: [stack],
  };

  return { pageId, route, title, root };
}
