import { describe, it, expect } from "vitest";
import { renderNode } from "../src/runtime/dispatch";
import { applyLayout } from "../src/runtime/layouts";
import { renderToString } from "react-dom/server";

const layout = {
  schemaVersion: "1",
  id: "DashboardLayout",
  root: {
    id: "shell",
    type: "Stack",
    children: [
      { id: "main-slot", type: "Slot", props: { name: "main" } },
    ],
  },
};

describe("Slot + applyLayout", () => {
  it("inserts page root into the named slot", () => {
    const page = {
      schemaVersion: "1",
      id: "p",
      route: "/",
      layout: "DashboardLayout",
      root: { id: "page-content", type: "Text", props: { content: "page-body" } },
    };
    const composed = applyLayout(page as any, layout as any);
    const html = renderToString(renderNode(composed, { data: {} } as any));
    expect(html).toContain("page-body");
  });

  it("fills named slots from page.slots", () => {
    const pageWithSlots = {
      schemaVersion: "1",
      id: "p2",
      route: "/",
      layout: "DashboardLayout",
      root: { id: "main-content", type: "Text", props: { content: "main-area" } },
      slots: {
        sidebar: { id: "sb", type: "Text", props: { content: "sidebar-content" } },
      },
    };
    const layoutWithSidebar = {
      schemaVersion: "1",
      id: "DashboardLayout",
      root: {
        id: "shell",
        type: "Stack",
        children: [
          { id: "main-slot", type: "Slot", props: { name: "main" } },
          { id: "sidebar-slot", type: "Slot", props: { name: "sidebar" } },
        ],
      },
    };
    const composed = applyLayout(pageWithSlots as any, layoutWithSidebar as any);
    const html = renderToString(renderNode(composed, { data: {} } as any));
    expect(html).toContain("main-area");
    expect(html).toContain("sidebar-content");
  });
});
