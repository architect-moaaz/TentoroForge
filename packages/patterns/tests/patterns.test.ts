import { describe, it, expect } from "vitest";
import { generateApp } from "../src/generate-app.js";
import { resolvePattern, deriveViewsForEntity } from "../src/resolver.js";
import { compile } from "@tentoroforge/compiler";
import { validateIR } from "@tentoroforge/ir";
import type { AppSpec, EntitySpec } from "../src/types.js";

// ---------------------------------------------------------------------------
// Test entities
// ---------------------------------------------------------------------------

const taskEntity: EntitySpec = {
  name: "Task",
  fields: [
    { name: "title", type: "string", required: true },
    { name: "description", type: "text" },
    { name: "status", type: "enum", values: ["todo", "in_progress", "review", "done"] },
    { name: "priority", type: "enum", values: ["low", "medium", "high", "urgent"] },
    { name: "assigneeId", type: "relation", relationTo: "User" },
    { name: "dueDate", type: "date" },
    { name: "tags", type: "string[]" },
  ],
  capabilities: ["list", "search", "filter", "create", "edit", "delete", "detail", "comments"],
};

const userEntity: EntitySpec = {
  name: "User",
  fields: [
    { name: "name", type: "string", required: true },
    { name: "email", type: "email", required: true },
    { name: "avatar", type: "avatar" },
    { name: "role", type: "enum", values: ["admin", "member", "viewer"] },
    { name: "department", type: "string" },
    { name: "phone", type: "tel" },
    { name: "bio", type: "text" },
    { name: "isActive", type: "boolean" },
  ],
  capabilities: ["list", "search", "create", "edit", "delete", "detail"],
};

const projectEntity: EntitySpec = {
  name: "Project",
  fields: [
    { name: "name", type: "string", required: true },
    { name: "description", type: "text" },
    { name: "thumbnail", type: "image", isIdentityImage: true },
    { name: "status", type: "enum", values: ["active", "completed", "archived"] },
    { name: "createdAt", type: "datetime" },
  ],
  capabilities: ["list", "search", "create", "edit", "delete", "detail"],
};

const logEntity: EntitySpec = {
  name: "ActivityLog",
  fields: [
    { name: "action", type: "string", required: true },
    { name: "actor", type: "string" },
    { name: "timestamp", type: "datetime" },
    { name: "details", type: "text" },
  ],
  capabilities: ["list", "filter"],
};

const simpleEntity: EntitySpec = {
  name: "Tag",
  fields: [
    { name: "name", type: "string", required: true },
    { name: "color", type: "string" },
  ],
  capabilities: ["list", "create", "delete"],
};

// ---------------------------------------------------------------------------
// Resolver tests
// ---------------------------------------------------------------------------

describe("resolvePattern", () => {
  it("should select sidebar-detail for Task (rich entity with text field)", () => {
    const result = resolvePattern(taskEntity, "browse-and-act");
    expect(result.pattern).toBe("sidebar-detail");
  });

  it("should select card-grid for Project (has image)", () => {
    const result = resolvePattern(projectEntity, "browse-and-act");
    expect(result.pattern).toBe("card-grid");
  });

  it("should select timeline for ActivityLog (temporal entity)", () => {
    const result = resolvePattern(logEntity, "browse-and-act");
    expect(result.pattern).toBe("timeline");
  });

  it("should select simple-table for Tag (few fields, no image)", () => {
    const result = resolvePattern(simpleEntity, "browse-and-act");
    expect(result.pattern).toBe("simple-table");
  });

  it("should select profile-detail for User (person entity)", () => {
    const result = resolvePattern(userEntity, "detail");
    expect(result.pattern).toBe("profile-detail");
  });

  it("should select tabbed-detail for Task (rich with comments)", () => {
    const result = resolvePattern(taskEntity, "detail");
    expect(result.pattern).toBe("tabbed-detail");
  });

  it("should select simple-detail for Tag (few fields)", () => {
    const result = resolvePattern(simpleEntity, "detail");
    expect(result.pattern).toBe("simple-detail");
  });

  it("should select modal-form for Tag (2 editable fields)", () => {
    const result = resolvePattern(simpleEntity, "create");
    expect(result.pattern).toBe("modal-form");
  });

  it("should select page-form for Task (7 editable fields)", () => {
    const result = resolvePattern(taskEntity, "create");
    expect(result.pattern).toBe("page-form");
  });

  it("should populate config with the right fields", () => {
    const result = resolvePattern(taskEntity, "browse-and-act");
    expect(result.config.titleField?.name).toBe("title");
    expect(result.config.statusField?.name).toBe("status");
    expect(result.config.dateField?.name).toBe("dueDate");
    expect(result.config.hasSearch).toBe(true);
    expect(result.config.hasFilters).toBe(true);
  });
});

describe("deriveViewsForEntity", () => {
  it("should derive browse + detail + create for Task", () => {
    const views = deriveViewsForEntity(taskEntity);
    expect(views).toContain("browse-and-act");
    expect(views).toContain("detail");
    expect(views).toContain("create");
  });

  it("should derive browse + create for Tag (simple entity)", () => {
    const views = deriveViewsForEntity(simpleEntity);
    expect(views).toContain("browse-and-act");
    expect(views).toContain("create");
  });
});

// ---------------------------------------------------------------------------
// Full app generation tests
// ---------------------------------------------------------------------------

describe("generateApp", () => {
  const spec: AppSpec = {
    name: "Acme Project Manager",
    entities: [taskEntity, userEntity, projectEntity],
  };

  it("should generate a valid AppIR", () => {
    const ir = generateApp(spec);
    expect(ir.$schema).toBe("tentoroforge/ir/1.0");
    expect(ir.app.name).toBe("Acme Project Manager");
  });

  it("should generate pages for all entities + dashboard + auth", () => {
    const ir = generateApp(spec);
    const pageIds = ir.pages.map((p) => p.$id);

    // Dashboard
    expect(pageIds).toContain("dashboard");

    // Task pages
    expect(pageIds).toContain("task-list");
    expect(pageIds).toContain("task-detail");
    expect(pageIds).toContain("task-create");

    // User pages (card-grid because user has avatar field)
    expect(pageIds).toContain("user-grid");
    expect(pageIds).toContain("user-profile");
    expect(pageIds).toContain("user-create");

    // Project pages
    expect(pageIds).toContain("project-grid");
    expect(pageIds).toContain("project-detail");
    expect(pageIds).toContain("project-create");

    // Auth
    expect(pageIds).toContain("login");
    expect(pageIds).toContain("signup");
  });

  it("should generate data sources for all CRUD operations", () => {
    const ir = generateApp(spec);
    const dsNames = Object.keys(ir.dataSources);

    expect(dsNames).toContain("tasks");
    expect(dsNames).toContain("createTask");
    expect(dsNames).toContain("updateTask");
    expect(dsNames).toContain("deleteTask");
    expect(dsNames).toContain("users");
    expect(dsNames).toContain("login");
    expect(dsNames).toContain("signup");
  });

  it("should generate navigation items", () => {
    const ir = generateApp(spec);
    expect(ir.navigation).toBeDefined();
    expect(ir.navigation!.items.length).toBeGreaterThan(0);
    expect(ir.navigation!.items.some((i) => i.label === "Dashboard")).toBe(true);
    expect(ir.navigation!.items.some((i) => i.label === "Tasks")).toBe(true);
    expect(ir.navigation!.items.some((i) => i.label === "Users")).toBe(true);
  });

  it("should produce IR that passes validation", () => {
    const ir = generateApp(spec);
    const errors = validateIR(ir);
    const critical = errors.filter((e) => e.severity === "error");
    if (critical.length > 0) {
      console.error("Validation errors:", JSON.stringify(critical.slice(0, 5), null, 2));
    }
    expect(critical).toHaveLength(0);
  });

  it("should produce IR that compiles without errors", () => {
    const ir = generateApp(spec);
    const result = compile(ir);
    if (result.errors.length > 0) {
      console.error("Compile errors:", result.errors.slice(0, 5));
    }
    expect(result.errors).toHaveLength(0);
    expect(Object.keys(result.files).length).toBeGreaterThan(0);
  });

  it("should compile to a reasonable number of files", () => {
    const ir = generateApp(spec);
    const result = compile(ir);
    const filePaths = Object.keys(result.files);

    // Dashboard + 3 entities × ~3 views + 2 auth + formatters = ~13+ files
    expect(filePaths.length).toBeGreaterThanOrEqual(10);

    // Each file should have content
    for (const [path, content] of Object.entries(result.files)) {
      expect(content.length).toBeGreaterThan(50);
    }
  });
});

// ---------------------------------------------------------------------------
// Simple entity test (edge case: minimal entity)
// ---------------------------------------------------------------------------

describe("generateApp — minimal entity", () => {
  it("should handle a single simple entity", () => {
    const spec: AppSpec = {
      name: "Tag Manager",
      entities: [simpleEntity],
    };

    const ir = generateApp(spec);
    const result = compile(ir);

    expect(result.errors).toHaveLength(0);
    expect(Object.keys(result.files).length).toBeGreaterThan(0);

    // Should have at least: dashboard, tag-list, tag-create, login, signup
    const pageIds = ir.pages.map((p) => p.$id);
    expect(pageIds).toContain("dashboard");
    expect(pageIds).toContain("tag-list");
    expect(pageIds).toContain("tag-create");
    expect(pageIds).toContain("login");
  });
});

// ---------------------------------------------------------------------------
// End-to-end: describe → IR → code
// ---------------------------------------------------------------------------

describe("end-to-end", () => {
  it("should compile a full task manager app to code", () => {
    const spec: AppSpec = {
      name: "TaskFlow",
      description: "Project management tool",
      entities: [taskEntity],
      userContext: { domain: "engineering", scale: "~20 users" },
    };

    const ir = generateApp(spec);
    const result = compile(ir);

    expect(result.errors).toHaveLength(0);

    // Check that the task list page exists and has expected code
    const taskListFile = Object.entries(result.files).find(([path]) => path.includes("tasks/page.tsx"));
    expect(taskListFile).toBeDefined();
    const [, code] = taskListFile!;
    expect(code).toContain('"use client"');
    expect(code).toContain("useState");

    // Dashboard
    const dashboardFile = Object.entries(result.files).find(([path]) => path.includes("dashboard/page.tsx"));
    expect(dashboardFile).toBeDefined();

    // Login
    const loginFile = Object.entries(result.files).find(([path]) => path.includes("login/page.tsx"));
    expect(loginFile).toBeDefined();
  });
});
