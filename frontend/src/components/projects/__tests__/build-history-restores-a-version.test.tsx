/**
 * Build history read the app's git log, and a Blueprint application's
 * repository has no commits: only publish records showed, with no way back
 * (Mark 8, 2026-10-17). It lists the Blueprint's versions and restores one.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
let history: any;
const posts: [string, unknown][] = [];
vi.mock("@/lib/api", () => ({
  api: {
    get: async (u: string) => {
      if (u.endsWith("/blueprint/history")) { if (history instanceof Error) throw history; return history; }
      if (u.endsWith("/versions")) return [{ id: "x", message: "Initial generation", commit_hash: "abc1234", created_at: "2026-10-16T10:00:00Z" }];
      return null;
    },
    post: async (u: string, b: unknown) => { posts.push([u, b]); return { restored: (b as any).version, version: 50 }; },
  },
  ApiError: class extends Error {},
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { VersionSidebar } from "../VersionSidebar";

let root: Root;
let host: HTMLDivElement;
async function render() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => { root.render(<QueryClientProvider client={qc}><VersionSidebar projectId="p1" /></QueryClientProvider>); });
  for (let i = 0; i < 6; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}
const button = (label: string) =>
  [...document.body.querySelectorAll("button")].find((b) => b.textContent?.trim() === label) as HTMLButtonElement | undefined;

beforeEach(() => { host = document.createElement("div"); document.body.appendChild(host); root = createRoot(host); posts.length = 0; });
afterEach(() => { act(() => root.unmount()); host.remove(); });

describe("Build history", () => {
  it("lists every change and restores an earlier version after asking", async () => {
    history = { current: 49, versions: [
      { version: 49, at: "2026-10-17T17:20:43Z", request: "Remove the address app.mydomain.com", interpretation: "", undo: false, current: true, restorable: false },
      { version: 41, at: "2026-10-17T13:52:00Z", request: "can you add a page for tax calculation", interpretation: "", undo: false, current: false, restorable: true },
    ] };
    await render();
    const text = document.body.textContent ?? "";
    expect(text).toContain("now at v49 · 2 changes");
    expect(text).toContain("can you add a page for tax calculation");
    expect(text).toContain("Current");
    await act(async () => { button("Restore")!.click(); });
    expect(document.body.textContent).toContain("Restore version 41?");
    await act(async () => { button("Restore version 41")!.click(); });
    for (let i = 0; i < 4; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(posts).toEqual([["/api/projects/p1/blueprint/restore", { version: 41 }]]);
  });

  it("keeps the git list for a project with no Blueprint", async () => {
    history = new Error("404");
    await render();
    expect(document.body.textContent).toContain("Initial generation");
  });
});
