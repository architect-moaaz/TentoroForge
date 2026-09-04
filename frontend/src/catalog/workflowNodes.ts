/**
 * The workflow node catalog — the components a workflow is built from.
 *
 * `workflow-nodes.json` is emitted from `packages/catalog/workflow-nodes.json`
 * (`npm run emit --workspace=packages/catalog`); the backend reads the same
 * catalog, so the palette here, the nodes the workflow agent authors and the
 * nodes the engine runs are one list. Do not edit the JSON copy by hand.
 */
import catalog from "./workflow-nodes.json";
import type { NodeCategory, NodeCategoryItem, WorkflowNodeConfig, WorkflowNodeType } from "@/types/workflow";

export interface CatalogConfig {
  /** Groups of alternative keys; a node is configured when every group has one present. */
  required: string[][];
  defaults: Record<string, unknown>;
}

export interface CatalogVariant {
  key: string;
  label: string;
  icon: string;
  gradient: string;
  description: string;
  config: CatalogConfig;
}

export interface CatalogNode {
  type: string;
  category: string;
  label: string;
  icon: string;
  gradient: string;
  description: string;
  handles: { in: boolean; out: boolean; else: boolean };
  config: CatalogConfig;
  /** The config key that picks a variant (`type` on a trigger, `actionType` on an action). */
  variantKey?: string;
  variants?: CatalogVariant[];
  /** `false` for a runtime alias the palette does not offer. */
  palette?: boolean;
}

export interface WorkflowNodeCatalog {
  catalogVersion: number;
  categories: { id: string; label: string }[];
  nodes: CatalogNode[];
}

export const WORKFLOW_NODE_CATALOG = catalog as WorkflowNodeCatalog;

const BY_TYPE: Record<string, CatalogNode> = Object.fromEntries(
  WORKFLOW_NODE_CATALOG.nodes.map((n) => [n.type, n]),
);

export function catalogNode(nodeType: string): CatalogNode | undefined {
  return BY_TYPE[nodeType];
}

function variantOf(node: CatalogNode, config: Record<string, unknown> | undefined): CatalogVariant | undefined {
  if (!node.variantKey || !node.variants) return undefined;
  const key = config?.[node.variantKey];
  return node.variants.find((v) => v.key === key);
}

/** The icon name and gradient for a node, honouring its variant. */
export function visualFor(
  nodeType: string,
  config?: Record<string, unknown>,
): { icon: string; gradient: string } {
  const node = BY_TYPE[nodeType] ?? BY_TYPE.action;
  const variant = variantOf(node, config);
  if (variant) return { icon: variant.icon, gradient: variant.gradient };
  // Legacy form: an `action` whose actionType is itself a node type (an older
  // workflow's ai_generate) — show that node's visual, not the generic action.
  const legacy = nodeType === "action" ? config?.actionType : undefined;
  if (typeof legacy === "string" && BY_TYPE[legacy]) {
    return { icon: BY_TYPE[legacy].icon, gradient: BY_TYPE[legacy].gradient };
  }
  return { icon: node.icon, gradient: node.gradient };
}

/** Required-key groups a configured node of this kind must satisfy. */
export function requiredGroups(nodeType: string, config?: Record<string, unknown>): string[][] {
  const node = BY_TYPE[nodeType];
  if (!node) return [];
  const variant = variantOf(node, config);
  return [...node.config.required, ...(variant?.config.required ?? [])];
}

function present(v: unknown): boolean {
  if (v === null || v === undefined) return false;
  if (typeof v === "string" || Array.isArray(v)) return v.length > 0;
  if (typeof v === "object") return Object.keys(v as object).length > 0;
  return true;
}

/** Which required groups `config` leaves empty, as `a|b` strings. */
export function missingConfig(nodeType: string, config?: Record<string, unknown>): string[] {
  return requiredGroups(nodeType, config)
    .filter((group) => !group.some((k) => present(config?.[k])))
    .map((group) => group.join("|"));
}

function item(node: CatalogNode, variant?: CatalogVariant): NodeCategoryItem {
  const defaults: Record<string, unknown> = {
    ...node.config.defaults,
    ...(variant ? { [node.variantKey as string]: variant.key, ...variant.config.defaults } : {}),
  };
  return {
    id: variant ? `${node.type}-${variant.key}` : node.type,
    type: node.type as WorkflowNodeType,
    label: variant?.label ?? node.label,
    icon: variant?.icon ?? node.icon,
    description: variant?.description ?? node.description,
    gradient: variant?.gradient ?? node.gradient,
    defaultConfig: Object.keys(defaults).length ? (defaults as Partial<WorkflowNodeConfig>) : undefined,
  };
}

/** The palette, category by category, derived from the catalog. */
export const NODE_CATEGORIES: NodeCategory[] = WORKFLOW_NODE_CATALOG.categories.map((cat) => ({
  label: cat.label,
  nodes: WORKFLOW_NODE_CATALOG.nodes
    .filter((n) => n.category === cat.id && n.palette !== false)
    .flatMap((n) => (n.variants?.length ? n.variants.map((v) => item(n, v)) : [item(n)])),
}));
