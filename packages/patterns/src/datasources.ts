/**
 * Data Source Generator — creates IR data source definitions from entity specs.
 */

import type { DataSourceDef } from "@tentoroforge/ir";
import type { EntitySpec } from "./types.js";
import { pluralize, slugify } from "./field-analysis.js";

/**
 * Generate all data sources for an entity.
 */
export function generateDataSources(entity: EntitySpec): Record<string, DataSourceDef> {
  const plural = pluralize(entity.name);
  const slug = slugify(plural);
  const sources: Record<string, DataSourceDef> = {};

  // GET list
  if (entity.capabilities.includes("list")) {
    const params: Record<string, any> = {
      page: { type: "number", from: "state:page", default: 1 },
      limit: { type: "number", default: 20 },
    };
    if (entity.capabilities.includes("search")) {
      params.search = { type: "string", from: "state:search" };
    }
    const statusField = entity.fields.find(
      (f) => f.type === "enum" && f.name.toLowerCase().includes("status"),
    );
    if (statusField && entity.capabilities.includes("filter")) {
      params.status = { type: "string", from: "state:statusFilter" };
    }

    sources[slug] = {
      type: "rest",
      method: "GET",
      path: `/api/${slug}`,
      params,
      shape: { items: `${entity.name}[]`, total: "number" },
      refresh: "on-focus",
    };
  }

  // GET single (for detail view)
  if (entity.capabilities.includes("detail") || entity.capabilities.includes("edit")) {
    sources[`${slugify(entity.name)}Detail`] = {
      type: "rest",
      method: "GET",
      path: `/api/${slug}/{id}`,
      params: { id: { type: "string", from: "state:selectedId" } },
    };
  }

  // POST create
  if (entity.capabilities.includes("create")) {
    const invalidateTargets = [slug];
    sources[`create${entity.name}`] = {
      type: "rest",
      method: "POST",
      path: `/api/${slug}`,
      body: { from: "state:form" },
      onSuccess: { invalidate: invalidateTargets },
    };
  }

  // PUT update
  if (entity.capabilities.includes("edit")) {
    sources[`update${entity.name}`] = {
      type: "rest",
      method: "PUT",
      path: `/api/${slug}/{id}`,
      body: { from: "state:form" },
      onSuccess: { invalidate: [slug, `${slugify(entity.name)}Detail`] },
    };
  }

  // DELETE
  if (entity.capabilities.includes("delete")) {
    sources[`delete${entity.name}`] = {
      type: "rest",
      method: "DELETE",
      path: `/api/${slug}/{id}`,
      onSuccess: { invalidate: [slug] },
    };
  }

  return sources;
}

/**
 * Generate dashboard-specific data sources.
 */
export function generateDashboardDataSources(entities: EntitySpec[]): Record<string, DataSourceDef> {
  const sources: Record<string, DataSourceDef> = {};

  for (const entity of entities) {
    const plural = pluralize(entity.name);
    const slug = slugify(plural);

    // Stats endpoint
    sources[`${slug}Stats`] = {
      type: "rest",
      method: "GET",
      path: `/api/${slug}/stats`,
      shape: { total: "number" },
      refresh: "on-focus",
    };

    // Recent items
    sources[`recent${plural}`] = {
      type: "rest",
      method: "GET",
      path: `/api/${slug}`,
      params: {
        limit: { type: "number", default: 5 },
        sort: { type: "string", default: "-updatedAt" },
      },
      shape: { items: `${entity.name}[]` },
    };
  }

  return sources;
}

/**
 * Generate auth data sources.
 */
export function generateAuthDataSources(): Record<string, DataSourceDef> {
  return {
    login: {
      type: "rest",
      method: "POST",
      path: "/api/auth/login",
      body: { from: "state:form" },
    },
    signup: {
      type: "rest",
      method: "POST",
      path: "/api/auth/signup",
      body: { from: "state:form" },
    },
  };
}
