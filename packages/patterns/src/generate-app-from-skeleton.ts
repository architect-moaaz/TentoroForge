/**
 * Skeleton-based App Generator — takes LLM-generated page skeletons
 * and fills their PlaceholderSlot nodes with entity-specific IR.
 *
 * This replaces the fully deterministic generateApp() for cases
 * where the LLM has generated creative page layouts.
 */

import type { AppIR, PageIR, IRNode } from "@tentoroforge/ir";
import { getTheme, getThemeForDomain, applyThemeTokens } from "@tentoroforge/ir";
import type { AppSpec, EntitySpec } from "./types.js";
import { buildSlotFillerContext, fillPageSlots } from "./slot-filler.js";
import { generateDataSources, generateDashboardDataSources, generateAuthDataSources } from "./datasources.js";
import { slugify, pluralize } from "./field-analysis.js";

/**
 * Generate a complete AppIR from LLM-generated page skeletons.
 *
 * @param skeletons - PageIR[] with PlaceholderSlot nodes
 * @param spec - AppSpec with entity definitions
 * @returns Complete AppIR with all slots filled
 */
export function generateAppFromSkeletons(
  skeletons: PageIR[],
  spec: AppSpec,
): AppIR {
  // Build slot filler context
  const ctx = buildSlotFillerContext(spec.name, spec.entities);

  // Generate data sources
  const dataSources: Record<string, any> = {};
  for (const entity of spec.entities) {
    Object.assign(dataSources, generateDataSources(entity));
  }
  if (spec.entities.length > 0) {
    Object.assign(dataSources, generateDashboardDataSources(spec.entities));
  }
  Object.assign(dataSources, generateAuthDataSources());

  // Fill slots in each skeleton page
  const pages: PageIR[] = skeletons.map((skeleton) => fillPageSlots(skeleton, ctx));

  // Resolve theme
  const themeName =
    (spec as any).app?.theme ||
    (spec.userContext?.domain ? getThemeForDomain(spec.userContext.domain) : "ocean");
  const tokens = applyThemeTokens({}, themeName);

  // Apply tokenOverrides from AppSpec (e.g., Figma-extracted colors)
  const overrides = (spec as any).tokenOverrides as Record<string, string> | undefined;
  if (overrides) {
    if (!tokens.color) tokens.color = {};
    for (const [key, value] of Object.entries(overrides)) {
      if (key === "fontFamily") continue;
      (tokens.color as Record<string, string>)[key] = value;
    }
  }

  const userCtx = { ...(spec.userContext || {}) } as Record<string, unknown>;
  if (overrides?.fontFamily) {
    userCtx.fontFamily = overrides.fontFamily;
  }

  // Build navigation
  const navigation = {
    items: [
      { label: "Dashboard", icon: "layout-dashboard", route: "/dashboard" },
      ...spec.entities.map((e) => ({
        label: pluralize(e.name),
        icon: "list",
        route: `/${slugify(pluralize(e.name))}`,
      })),
    ],
  };

  return {
    $schema: "tentoroforge/ir/1.0",
    app: { name: spec.name, theme: themeName },
    userContext: userCtx,
    tokens,
    dataSources,
    pages,
    navigation,
  };
}
