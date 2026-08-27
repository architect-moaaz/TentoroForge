import type { ReactElement } from "react";
import type React from "react";
import type { Page, LayoutTemplate } from "@tentoroforge/schema";
import { validatePage } from "./runtime/validate";
import { resolveDataSources, type DataEngine } from "./server/DataResolver";
import { applyLayout } from "./runtime/layouts";
import { renderNode } from "./runtime/dispatch";

/**
 * Minimal structural type for a component registry.
 * Structurally compatible with `Registry` from `@tentoroforge/library` —
 * kept here to avoid a circular workspace dependency.
 */
export type RegistryLike = {
  has(name: string): boolean;
  get(name: string): { component: React.ComponentType<any>; propsSchema: { parse: (v: unknown) => unknown } } | undefined;
  validateProps(name: string, props: unknown): Record<string, unknown>;
};

export type SchemaRendererProps = {
  page: Page;
  dataEngine: DataEngine;
  layouts?: Record<string, LayoutTemplate>;
  user?: Record<string, unknown>;
  request?: Request;
  /** Component registry for library node dispatch (Task 28). */
  registry?: RegistryLike;
};

export async function SchemaRenderer({
  page,
  dataEngine,
  layouts,
  user,
  request,
  registry,
}: SchemaRendererProps): Promise<ReactElement | null> {
  const valid = validatePage(page);
  const data = await resolveDataSources(valid, dataEngine, { request, user });

  const layoutTpl = valid.layout ? layouts?.[valid.layout] : null;
  const root = layoutTpl ? applyLayout(valid, layoutTpl) : valid.root;

  return <>{renderNode(root as any, { data, user, registry })}</>;
}

export type { DataEngine } from "./server/DataResolver";
