/** Plain names for what is on the page — the words the editor speaks (UX-004). */
import type { ComponentDef, ModelNode, PageModel, Registry } from "../types";

const ELEMENT_NAMES: Record<string, string> = {
  div: "Section", section: "Section", main: "Main area", article: "Article", aside: "Side panel",
  header: "Header", footer: "Footer", nav: "Navigation", form: "Form", fieldset: "Field group",
  h1: "Heading", h2: "Heading", h3: "Heading", h4: "Heading", h5: "Heading", h6: "Heading",
  p: "Text", span: "Text", small: "Small text", strong: "Bold text", em: "Emphasis", label: "Label",
  a: "Link", img: "Image", ul: "List", ol: "Numbered list", li: "List item",
  table: "Table", thead: "Table header", tbody: "Table rows", tr: "Row", th: "Column heading", td: "Cell",
  button: "Button", input: "Field", textarea: "Text area", select: "Dropdown", option: "Option",
  hr: "Divider", br: "Line break", svg: "Icon", Fragment: "Group",
  // The UI kit, for a registry that does not name a kind.
  Input: "Field", Textarea: "Text area", Checkbox: "Checkbox", Label: "Label", Separator: "Divider",
  Skeleton: "Loading placeholder", Select: "Dropdown", SelectItem: "Option", TableRow: "Row", TableCell: "Cell",
  TableHead: "Column heading", Link: "Link",
};

export function componentFor(registry: Registry | null | undefined, type: string): ComponentDef | null {
  if (!registry) return null;
  return registry.components.find((c) => c.match.types.includes(type)) ?? null;
}

export function plainType(node: ModelNode, registry?: Registry | null): string {
  const def = componentFor(registry, node.type);
  if (def) return def.label;
  if (ELEMENT_NAMES[node.type]) return ELEMENT_NAMES[node.type];
  // "CardHeader" → "Card header"; "motion.div" → "Motion div"
  const words = node.type.replace(/\./g, " ").replace(/([a-z])([A-Z])/g, "$1 $2").split(/\s+/);
  return words.map((w, i) => (i === 0 ? w[0].toUpperCase() + w.slice(1) : w.toLowerCase())).join(" ");
}

/** A short label with the text if it has any: `Heading “Records”`. */
export function plainName(node: ModelNode, registry?: Registry | null): string {
  const base = plainType(node, registry);
  const text = node.text && node.textEditable ? node.text.trim() : "";
  if (text) return `${base} “${text.length > 24 ? text.slice(0, 23) + "…" : text}”`;
  const label = node.props.find((p) => p.name === "label" && p.kind === "string")?.value
    ?? node.props.find((p) => p.name === "title" && p.kind === "string")?.value
    ?? node.props.find((p) => p.name === "placeholder" && p.kind === "string")?.value;
  if (label) return `${base} “${label}”`;
  return base;
}

export function ancestors(model: PageModel, id: string): ModelNode[] {
  const out: ModelNode[] = [];
  let cur = model.nodes[id];
  while (cur && cur.parent) {
    cur = model.nodes[cur.parent];
    if (cur) out.push(cur);
  }
  return out;
}

export function breadcrumb(model: PageModel, id: string, registry?: Registry | null): { id: string; label: string }[] {
  const node = model.nodes[id];
  if (!node) return [];
  const chain = [...ancestors(model, id).reverse(), node];
  return chain.map((n) => ({ id: n.id, label: plainType(n, registry) }));
}

export function isDescendant(model: PageModel, id: string, maybeAncestor: string): boolean {
  return ancestors(model, id).some((a) => a.id === maybeAncestor);
}

/** The root the View returns — the page itself, as opposed to helper components' JSX. */
export function mainRoot(model: PageModel): string | null {
  const view = model.roots.find((r) => r.owner === "View") ?? model.roots[model.roots.length - 1];
  return view?.id ?? null;
}

/** Which of the selected ids are topmost (none of the others contains them). */
export function topmost(model: PageModel, ids: string[]): string[] {
  return ids.filter((id) => !ids.some((other) => other !== id && isDescendant(model, id, other)));
}

export function describeCount(n: number, singular: string, plural = singular + "s"): string {
  return `${n} ${n === 1 ? singular : plural}`;
}
