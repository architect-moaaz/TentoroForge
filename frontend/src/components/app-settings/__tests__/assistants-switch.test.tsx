/**
 * App settings → AI assistants: the switch reads whether the app's MCP server
 * is on, turning it saves the setting, and the tools an assistant gets are
 * listed with who may use each.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

let state: any;
const puts: [string, unknown][] = [];

vi.mock("@/lib/api", () => ({
  api: {
    get: async () => state,
    put: async (u: string, b: any) => { puts.push([u, b]); state = { ...state, enabled: b.enabled }; return state; },
  },
}));

import { AssistantsSection } from "../AssistantsSection";

let root: Root;
let host: HTMLDivElement;
const flush = async () => { for (let i = 0; i < 10; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)); }); };

beforeEach(() => {
  puts.length = 0;
  state = {
    enabled: false, path: "/api/mcp", connectPage: "/connect-ai",
    tools: {
      workflows: [{ tool: "add_product", name: "Add Product", roles: ["Admin"] },
                  { tool: "add_to_cart", name: "Add to Cart", roles: ["*"] }],
      records: [{ find: "find_orders", get: "get_orders", name: "Order", roles: null }],
    },
  };
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => { act(() => root.unmount()); host.remove(); });

describe("AI assistants in App settings", () => {
  it("shows the switch off, the tools and who may use each", async () => {
    await act(async () => {
      root.render(<QueryClientProvider client={new QueryClient()}><AssistantsSection projectId="p1" /></QueryClientProvider>);
    });
    await flush();
    const sw = host.querySelector('[role="switch"]')!;
    expect(sw.getAttribute("aria-checked")).toBe("false");
    expect(host.textContent).toContain("Off. The app's MCP address answers “not found”");
    const rows = [...host.querySelectorAll("[data-app-mcp-tools] li")].map((li) => li.textContent);
    expect(rows).toEqual([
      "add_product runs Add ProductAdmin",
      "add_to_cart runs Add to Carteveryone",
      "find_orders / get_orders reads Orderanyone signed in",
    ]);
    expect(host.textContent).toContain("What an assistant can do (4 tools)");
  });

  it("turning it on saves the setting and says how people connect", async () => {
    await act(async () => {
      root.render(<QueryClientProvider client={new QueryClient()}><AssistantsSection projectId="p1" /></QueryClientProvider>);
    });
    await flush();
    await act(async () => { (host.querySelector('[role="switch"]') as HTMLButtonElement).click(); });
    await flush();
    expect(puts).toEqual([["/api/projects/p1/app-mcp", { enabled: true }]]);
    expect(host.querySelector('[role="switch"]')!.getAttribute("aria-checked")).toBe("true");
    expect(host.textContent).toContain("“Connect an AI assistant” page");
    expect(host.textContent).toContain("next publish");
  });
});
