/**
 * The page schema shape generated apps deal with. Mirrors PageV2 from
 * @tentoroforge/schema but kept as a structural type here so consumers
 * don't have to import the full schema package at type-check time.
 */
export interface PageSchema {
  schemaVersion: "1" | "2";
  id: string;
  route?: string;
  layout?: string;
  meta?: Record<string, unknown>;
  dataSources?: DataSource[];
  root?: SchemaNode;
  children?: SchemaNode[]; // legacy: some LLM outputs use top-level children
}

export interface SchemaNode {
  type: string;
  id?: string;
  props?: Record<string, unknown>;
  children?: SchemaNode[];
  slots?: Record<string, SchemaNode[]>;
  visibleIf?: string;
}

export interface DataSource {
  name: string;
  source?: string;
  op?: "list" | "get" | "search";
  params?: Record<string, unknown>;
}

export interface DesignSpec {
  register?: string;
  colorPalette?: { primary?: string; [k: string]: unknown };
  typography?: Record<string, unknown>;
  entityPhotos?: Record<string, string>;
  tokens?: Record<string, unknown>;
  cta_hierarchy?: Record<string, unknown>;
  /** Per-project illustration asset base path. Passed to buildDefaultRegistry
   *  so Hero / Section / EmptyStateRich resolve illustration slugs against the
   *  correct project route (e.g. /p/<projectId>/illustrations in the scaffold). */
  illustrationBasePath?: string;
}

export interface EngineProps {
  schema: PageSchema;
  designSpec?: DesignSpec;
  apiBaseUrl?: string;
  previewData?: Record<string, unknown>;
  /** Force live workflow dispatch even when `previewData` is supplied. Standalone
   *  apps resolve dataSources server-side (→ previewData) for SSR but are still
   *  fully live — without this, the Engine would infer preview/editor mode from
   *  the presence of previewData and make its dispatch a no-op. */
  live?: boolean;
}

export interface DataContext {
  data: Record<string, unknown>;
  user?: Record<string, unknown>;
}

