/**
 * Full App Generator — takes an AppSpec and produces a complete AppIR.
 *
 * This is the top-level entry point for the pattern system.
 * No LLM involved — pure deterministic code.
 */

import type { AppIR, PageIR, IRNode } from "@tentoroforge/ir";
import { getTheme, getThemeForDomain, applyThemeTokens } from "@tentoroforge/ir";
import type { AppSpec, EntitySpec, ViewIntent, PatternSelection } from "./types.js";
import { resolvePattern, deriveViewsForEntity } from "./resolver.js";
import { generateDataSources, generateDashboardDataSources, generateAuthDataSources } from "./datasources.js";
import { slugify, pluralize, countEditableFields } from "./field-analysis.js";

// Browse fragments
import { simpleTableRoot, denseTableRoot, sidebarDetailRoot, cardGridRoot } from "./fragments/browse.js";
import { kanbanRoot } from "./fragments/kanban.js";
import { timelineRoot } from "./fragments/timeline.js";
// Form fragments
import { modalFormRoot, pageFormRoot, sectionedFormRoot } from "./fragments/forms.js";
import { wizardRoot } from "./fragments/wizard.js";
// Detail fragments
import { simpleDetailRoot, tabbedDetailRoot, profileDetailRoot } from "./fragments/detail.js";
// Dashboard fragments
import { statTableDashboardRoot } from "./fragments/dashboard.js";
import { kpiActivityRoot } from "./fragments/kpi-activity.js";
// Shell fragments
import { authLoginRoot, authSignupRoot } from "./fragments/shell.js";

// ---------------------------------------------------------------------------
// Main entry
// ---------------------------------------------------------------------------

export function generateApp(spec: AppSpec): AppIR {
  const dataSources: Record<string, any> = {};
  const pages: PageIR[] = [];

  // Generate pages for each entity
  for (const entity of spec.entities) {
    // Derive views
    const explicitViews = spec.views?.[entity.name];
    const viewIntents = explicitViews
      ? explicitViews.map((v) => v.intent)
      : deriveViewsForEntity(entity);

    // Generate data sources
    Object.assign(dataSources, generateDataSources(entity));

    // Generate pages per view
    for (const intent of viewIntents) {
      const selection = resolvePattern(entity, intent);
      const page = generatePage(selection);
      if (page) pages.push(page);
    }
  }

  // Dashboard page
  if (spec.entities.length > 0) {
    Object.assign(dataSources, generateDashboardDataSources(spec.entities));
    pages.unshift(generateDashboardPage(spec));
  }

  // Auth pages
  Object.assign(dataSources, generateAuthDataSources());
  pages.push(generateLoginPage(spec.name));
  pages.push(generateSignupPage(spec.name));

  // Resolve theme: explicit app.theme > domain inference > default
  const themeName =
    (spec as any).app?.theme ||
    (spec.userContext?.domain ? getThemeForDomain(spec.userContext.domain) : "ocean");
  const theme = getTheme(themeName);
  const tokens = applyThemeTokens({}, themeName);

  // Apply tokenOverrides from AppSpec (e.g., Figma-extracted colors)
  const overrides = (spec as any).tokenOverrides as Record<string, string> | undefined;
  if (overrides) {
    if (!tokens.color) tokens.color = {};
    for (const [key, value] of Object.entries(overrides)) {
      if (key === "fontFamily") continue; // handled via userContext
      (tokens.color as Record<string, string>)[key] = value;
    }
  }

  // Pass font override through userContext
  const userCtx = { ...(spec.userContext || {}) } as Record<string, unknown>;
  if (overrides?.fontFamily) {
    userCtx.fontFamily = overrides.fontFamily;
  }

  return {
    $schema: "tentoroforge/ir/1.0",
    app: { name: spec.name, theme: themeName },
    userContext: userCtx,
    tokens,
    dataSources,
    pages,
    navigation: {
      items: [
        { label: "Dashboard", icon: "layout-dashboard", route: "/dashboard" },
        ...spec.entities.map((e) => ({
          label: pluralize(e.name),
          icon: "list",
          route: `/${slugify(pluralize(e.name))}`,
        })),
      ],
    },
  };
}

// ---------------------------------------------------------------------------
// Page generation by pattern
// ---------------------------------------------------------------------------

function generatePage(selection: PatternSelection): PageIR | null {
  const { pattern, entity, intent, config } = selection;
  const slug = slugify(pluralize(entity.name));
  const entitySlug = slugify(entity.name);

  switch (pattern) {
    // Browse
    case "simple-table":
      return {
        $id: `${entitySlug}-list`,
        route: `/${slug}`,
        title: pluralize(entity.name),
        auth: { required: true },
        state: buildBrowseState(config),
        root: simpleTableRoot(entity, config),
      };

    case "dense-table":
      return {
        $id: `${entitySlug}-list`,
        route: `/${slug}`,
        title: pluralize(entity.name),
        auth: { required: true },
        state: buildBrowseState(config),
        root: denseTableRoot(entity, config),
      };

    case "sidebar-detail":
      return {
        $id: `${entitySlug}-list`,
        route: `/${slug}`,
        title: pluralize(entity.name),
        auth: { required: true },
        state: { ...buildBrowseState(config), selectedId: null },
        root: sidebarDetailRoot(entity, config),
      };

    case "card-grid":
      return {
        $id: `${entitySlug}-grid`,
        route: `/${slug}`,
        title: pluralize(entity.name),
        auth: { required: true },
        state: buildBrowseState(config),
        root: cardGridRoot(entity, config),
      };

    case "kanban":
      return {
        $id: `${entitySlug}-board`,
        route: `/${slug}/board`,
        title: `${pluralize(entity.name)} Board`,
        auth: { required: true },
        state: buildBrowseState(config),
        root: kanbanRoot(entity, config),
      };

    case "timeline":
      return {
        $id: `${entitySlug}-timeline`,
        route: `/${slug}`,
        title: pluralize(entity.name),
        auth: { required: true },
        state: { ...buildBrowseState(config), dateFilter: "all" },
        root: timelineRoot(entity, config),
      };

    // Detail
    case "simple-detail":
      return {
        $id: `${entitySlug}-detail`,
        route: `/${slug}/[id]`,
        title: `${entity.name} Detail`,
        auth: { required: true },
        state: {},
        root: simpleDetailRoot(entity, config),
      };

    case "tabbed-detail":
      return {
        $id: `${entitySlug}-detail`,
        route: `/${slug}/[id]`,
        title: `${entity.name} Detail`,
        auth: { required: true },
        state: {},
        root: tabbedDetailRoot(entity, config),
      };

    case "profile-detail":
      return {
        $id: `${entitySlug}-profile`,
        route: `/${slug}/[id]`,
        title: `${entity.name} Profile`,
        auth: { required: true },
        state: {},
        root: profileDetailRoot(entity, config),
      };

    // Forms
    case "modal-form":
    case "page-form":
      return {
        $id: `${entitySlug}-create`,
        route: `/${slug}/new`,
        title: `Create ${entity.name}`,
        auth: { required: true },
        state: { form: buildFormState(entity) },
        root: pageFormRoot(entity, config),
      };

    case "sectioned-form":
      return {
        $id: `${entitySlug}-create`,
        route: `/${slug}/new`,
        title: `Create ${entity.name}`,
        auth: { required: true },
        state: { form: buildFormState(entity) },
        root: sectionedFormRoot(entity, config),
      };

    case "wizard":
      return {
        $id: `${entitySlug}-wizard`,
        route: `/${slug}/new`,
        title: `Create ${entity.name}`,
        auth: { required: true },
        state: { form: buildFormState(entity), step: 0 },
        root: wizardRoot(entity, config),
      };

    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Dashboard page
// ---------------------------------------------------------------------------

function generateDashboardPage(spec: AppSpec): PageIR {
  return {
    $id: "dashboard",
    route: "/dashboard",
    title: "Dashboard",
    auth: { required: true },
    state: {},
    root: statTableDashboardRoot(spec.entities),
  };
}

// ---------------------------------------------------------------------------
// Auth pages
// ---------------------------------------------------------------------------

function generateLoginPage(appName: string): PageIR {
  return {
    $id: "login",
    route: "/login",
    title: "Sign In",
    state: { form: { email: "", password: "" }, error: null },
    root: authLoginRoot(appName),
  };
}

function generateSignupPage(appName: string): PageIR {
  return {
    $id: "signup",
    route: "/signup",
    title: "Create Account",
    state: { form: { name: "", email: "", password: "" } },
    root: authSignupRoot(appName),
  };
}

// ---------------------------------------------------------------------------
// State builders
// ---------------------------------------------------------------------------

function buildBrowseState(config: any): Record<string, any> {
  const state: Record<string, any> = { page: 1 };
  if (config.hasSearch) state.search = "";
  if (config.statusField) state.statusFilter = "all";
  return state;
}

function buildFormState(entity: EntitySpec): Record<string, any> {
  const form: Record<string, any> = {};
  for (const field of entity.fields) {
    if (field.name === "id" || field.name === "createdAt" || field.name === "updatedAt") continue;
    switch (field.type) {
      case "string":
      case "email":
      case "url":
      case "tel":
      case "text":
      case "richtext":
        form[field.name] = field.defaultValue ?? "";
        break;
      case "number":
        form[field.name] = field.defaultValue ?? 0;
        break;
      case "boolean":
        form[field.name] = field.defaultValue ?? false;
        break;
      case "enum":
        form[field.name] = field.defaultValue ?? (field.values?.[0] || "");
        break;
      case "date":
      case "datetime":
        form[field.name] = "";
        break;
      case "relation":
        form[field.name] = "";
        break;
      default:
        form[field.name] = "";
    }
  }
  return form;
}
