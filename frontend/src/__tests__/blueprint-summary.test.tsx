/**
 * The right-hand Blueprint panel (§25, §109), rendered from a document shaped
 * like a real define run's output — the Task Tracker in output/3hhr1ruo.
 *
 * Covered:
 *   • identity, language, palette and the four counts come off the document
 *   • pages, entities, capabilities and requirements are named, not counted
 *   • long lists fold, and "+N more" unfolds them in place
 *   • the footer offers Build for a ready definition, and not for a built one
 */
import { describe, it, expect, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import {
  BlueprintSummary,
  blueprintCountsLine,
  type BlueprintStatus,
} from "@/components/smith/BlueprintSummary";

// createRoot + act() outside a test renderer: React wants to be told.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const DOC = {
  version: 31,
  application: {
    id: "3hhr1ruo",
    name: "Task Tracker App",
    domain: "unknown",
    description:
      "Simple Task Tracker with a /tasks table (per-row toggle status + New task button) and a /tasks/new form.",
  },
  product: {
    locale: "en",
    capabilities: [
      { name: "Task Listing & Filtering", description: "View all tasks in a table and filter by status." },
      { name: "Task Status Toggle", description: "Toggle a task's status directly from the list." },
      { name: "Task Creation", description: "Create a new task via a dedicated form page." },
    ],
  },
  designSystem: {
    colors: {
      accent: "#D97706",
      background: "#FAFAF9",
      primary: "#4F46E5",
      "primary-subtle": "#EEF0FE",
      "text-primary": "#1C1B1A",
    },
  },
  pages: [
    { id: "PAGE-001", name: "Tasks", route: "/tasks", purpose: "See every task.", pattern: "entity_list" },
    { id: "PAGE-002", name: "New Task", route: "/tasks/new", purpose: "Create a task.", pattern: "form" },
  ],
  data: {
    entities: [
      {
        id: "ENT-001",
        name: "Task",
        fields: [
          { name: "id", type: "uuid" },
          { name: "title", type: "text" },
          { name: "status", type: "enum" },
          { name: "priority", type: "enum" },
        ],
      },
    ],
  },
  workflows: [
    { id: "WF-1", name: "Create Task", trigger: { kind: "manual" } },
    { id: "WF-2", name: "Toggle Task Status", trigger: { kind: "manual" } },
    { id: "WF-3", name: "Filter Tasks", trigger: { kind: "manual" } },
  ],
  requirements: Array.from({ length: 9 }, (_, i) => ({
    id: `REQ-00${i + 1}`,
    description: `Requirement number ${i + 1} of the task tracker.`,
  })),
};

function mount(
  status: BlueprintStatus,
  handlers: Partial<{ onBuild: () => void; onEdit: () => void }> = {},
) {
  const el = document.createElement("div");
  document.body.appendChild(el);
  let root!: Root;
  act(() => {
    root = createRoot(el);
    root.render(
      <BlueprintSummary
        doc={DOC}
        status={status}
        onBuild={handlers.onBuild ?? (() => {})}
        onEdit={handlers.onEdit ?? (() => {})}
      />,
    );
  });
  const buttons = () => Array.from(el.querySelectorAll("button"));
  const click = (label: string) => {
    const b = buttons().find((x) => x.textContent?.trim().startsWith(label));
    if (!b) throw new Error(`no button starting with "${label}"`);
    act(() => b.click());
  };
  return { el, click, buttons, unmount: () => act(() => root.unmount()) };
}

describe("BlueprintSummary", () => {
  it("shows the application's identity and the four counts", () => {
    const { el, unmount } = mount({ kind: "ready" });
    const t = el.textContent ?? "";
    expect(t).toContain("App Blueprint");
    expect(t).toContain("v31");
    expect(t).toContain("Task Tracker App");
    expect(t).toContain("Simple Task Tracker");
    expect(t).toContain("English");
    expect(t).toContain("Ready to build");
    expect(t).toMatch(/2\s*Pages/);
    expect(t).toMatch(/1\s*Data model/);
    expect(t).toMatch(/3\s*Workflows/);
    expect(t).toMatch(/9\s*Requirements/);
    // Swatches come from the design system, light to dark.
    const dots = Array.from(el.querySelectorAll('[aria-label="Palette swatches"] span'));
    expect(dots.map((d) => (d as HTMLElement).style.backgroundColor)).toEqual([
      "rgb(250, 250, 249)",
      "rgb(238, 240, 254)",
      "rgb(79, 70, 229)",
      "rgb(28, 27, 26)",
    ]);
    unmount();
  });

  it("names pages, entities and capabilities rather than counting them", () => {
    const { el, unmount } = mount({ kind: "ready" });
    const t = el.textContent ?? "";
    expect(t).toContain("/tasks/new");
    expect(t).toContain("New Task");
    expect(t).toContain("4 fields");
    expect(t).toContain("id, title, status, priority");
    expect(t).toContain("Task Status Toggle");
    unmount();
  });

  it("folds long requirement lists and unfolds them in place", () => {
    const { el, click, unmount } = mount({ kind: "ready" });
    expect(el.textContent).toContain("Requirement number 3");
    expect(el.textContent).not.toContain("Requirement number 4");
    expect(el.textContent).toContain("6 more requirements");
    click("6 more requirements");
    expect(el.textContent).toContain("Requirement number 9");
    expect(el.textContent).toContain("Show less");
    unmount();
  });

  it("builds and edits from the footer when the definition is ready", () => {
    const onBuild = vi.fn();
    const onEdit = vi.fn();
    const { click, unmount } = mount({ kind: "ready" }, { onBuild, onEdit });
    click("Build app");
    expect(onBuild).toHaveBeenCalledTimes(1);
    click("Edit blueprint");
    expect(onEdit).toHaveBeenCalledTimes(1);
    unmount();
  });

  it("offers to finish a partly built application, and nothing to a built one", () => {
    const partial = mount({ kind: "partial", missing: 1, total: 2 });
    expect(partial.el.textContent).toContain("1 of 2 pages unbuilt");
    expect(partial.buttons().some((b) => b.textContent?.includes("Finish the missing pages"))).toBe(true);
    partial.unmount();

    const built = mount({ kind: "built" });
    expect(built.el.textContent).toContain("Built");
    expect(built.buttons().some((b) => b.textContent?.includes("Build app"))).toBe(false);
    expect(built.buttons().some((b) => b.textContent?.includes("Edit blueprint"))).toBe(true);
    built.unmount();
  });

  it("writes the transcript card's one line", () => {
    expect(blueprintCountsLine(DOC)).toBe(
      "2 pages · 1 data model · 3 workflows · 9 requirements",
    );
  });
});
