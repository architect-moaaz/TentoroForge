/**
 * Runtime renderer context types.
 *
 * Shared across all node renderer components.
 */

export type NodePath = number[];

export interface RendererContext {
  /** Page-local reactive state */
  state: Record<string, unknown>;
  setState: (path: string, value: unknown) => void;

  /** Data sources (mock or real) */
  dataSources: Record<string, DataSourceState>;

  /** Design tokens from AppIR */
  tokens: TokenMap;

  /** Reusable fragment definitions */
  fragments: Record<string, FragmentDef>;

  /** Modal open/close state */
  modals: Record<string, boolean>;
  toggleModal: (name: string) => void;

  /** Iterator scope for Repeater/DataTable */
  iteratorScope: IteratorScope | null;

  /** Execute an action */
  onAction: (action: ActionDef) => void;

  /** Editor integration */
  selectedPath: NodePath | null;
  hoveredPath: NodePath | null;
  onSelect: (path: NodePath) => void;
  onHover: (path: NodePath | null) => void;

  /** Whether editor interactions are enabled */
  editable: boolean;
}

export interface DataSourceState {
  data: unknown;
  isLoading: boolean;
  error: string | null;
}

export interface IteratorScope {
  variable: string;
  index: number;
  value: unknown;
}

export interface TokenMap {
  color?: Record<string, string>;
  spacing?: Record<string, string>;
  radius?: Record<string, string>;
  typography?: Record<string, unknown>;
}

export interface FragmentDef {
  root: IRNode;
  props?: Record<string, unknown>;
}

// Simplified IR types for the renderer (mirrors packages/ir/src/types.ts)
export interface IRNode {
  node: string;
  children?: IRNode[];
  visible?: string;
  [key: string]: unknown;
}

export type ActionDef =
  | { type: "navigate"; to: string }
  | { type: "mutate"; source: string; confirm?: string }
  | { type: "setState"; path: string; value: unknown }
  | { type: "openModal"; modal: string }
  | { type: "closeModal"; modal: string }
  | { type: "toast"; variant?: string; message: string; duration?: number }
  | { type: "invalidate"; sources: string[] }
  | { type: "sequence"; steps: ActionDef[] }
  | { type: "custom"; code: string };

export interface NodeRendererProps {
  node: IRNode;
  path: NodePath;
}

/** Safely cast unknown IR node values for rendering */
export function str(v: unknown): string {
  return v == null ? "" : String(v);
}

export function bool(v: unknown): boolean {
  return Boolean(v);
}

export function num(v: unknown, fallback = 0): number {
  return typeof v === "number" ? v : fallback;
}
