/**
 * Test and Production in the Publish dialog: Publish goes where the switch
 * is; publishing untested changes to production asks once more; Promote sends
 * what Test runs; moving the switch saves it.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = ((q: string) => ({ matches: false, media: q, onchange: null, addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; } })) as unknown as typeof window.matchMedia;
}
if (typeof window !== "undefined" && !(window as any).ResizeObserver) {
  (window as any).ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
}
if (typeof Element !== "undefined" && !(Element.prototype as any).hasPointerCapture) {
  (Element.prototype as any).hasPointerCapture = () => false;
  (Element.prototype as any).releasePointerCapture = () => {};
  (Element.prototype as any).setPointerCapture = () => {};
  (Element.prototype as any).scrollIntoView = () => {};
}

let status: any;
const started: unknown[] = [];
const puts: [string, unknown][] = [];

vi.mock("@/lib/api", () => ({
  api: {
    get: async (u: string) => {
      if (u.endsWith("/publish-status")) return status;
      if (u.endsWith("/check")) return { checked: false, pages: 0, working: 0, failing: [], processes: [] };
      if (u.endsWith("/api/projects/p1")) return { status: "ready" };
      return null;
    },
    put: async (u: string, b: unknown) => { puts.push([u, b]); return { target: (b as any).target }; },
    post: async () => ({}),
    delete: async () => ({}),
  },
  authFetch: async () => new Response(null, { status: 200 }),
}));
vi.mock("@/hooks/useDeployStream", () => ({
  useDeployStream: () => ({ events: [], status: "idle", start: (b?: unknown) => { started.push(b); }, reset: () => {} }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("../MobileBuildsPanel", () => ({ MobileBuildsPanel: () => null }));
vi.mock("../DomainsPanel", () => ({ DomainsPanel: () => null }));
vi.mock("next/navigation", () => ({ useParams: () => ({}), useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ replace() {} }), usePathname: () => "/" }));

import { PublishDialog } from "../PublishDialog";
import { PublishButton } from "../PublishButton";

const side = (url: string, at = "2026-10-16T10:00:00Z") =>
  ({ id: url, status: "succeeded", url, deployment_url: url, app_version: null, promoted_from: null, finished_at: at });

let root: Root;
let host: HTMLDivElement;

async function render(el: React.ReactNode = <PublishDialog projectId="p1" open onOpenChange={() => {}} />) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(<QueryClientProvider client={qc}>{el}</QueryClientProvider>);
  });
  for (let i = 0; i < 4; i++) await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}

const button = (label: string) =>
  [...document.body.querySelectorAll("button")].find((b) => b.textContent?.trim() === label) as HTMLButtonElement | undefined;

beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  started.length = 0;
  puts.length = 0;
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("Publish, Test and Production", () => {
  it("publishes to Test when the switch is on Test, and never touches production", async () => {
    status = { target: "test", test: null, production: side("https://acme.vercel.app"),
               test_address: "https://acme-test.vercel.app", untested_changes: true, test_ahead: false };
    await render();
    expect(document.body.textContent).toContain("Not published to Test yet. The live app is not affected.");
    expect(document.body.textContent).toContain("acme-test.vercel.app");
    await act(async () => { button("Publish to Test")!.click(); });
    expect(started).toEqual([{ environment: "test", reset_test_data: false }]);
  });

  it("asks once more before untested changes go live, and offers Test first", async () => {
    status = { target: "production", test: side("https://acme-test.vercel.app"), production: side("https://acme.vercel.app"),
               test_address: "https://acme-test.vercel.app", untested_changes: true, test_ahead: false };
    await render();
    await act(async () => { button("Publish to Production")!.click(); });
    expect(started).toEqual([]);
    expect(document.body.querySelector('[role="alert"]')?.textContent).toContain("changed since it was last tried on Test");
    await act(async () => { button("Publish to Production anyway")!.click(); });
    expect(started).toEqual([{ environment: "production" }]);
  });

  it("promotes exactly what Test runs", async () => {
    status = { target: "production", test: side("https://acme-test.vercel.app"), production: side("https://acme.vercel.app"),
               test_address: "https://acme-test.vercel.app", untested_changes: false, test_ahead: true };
    await render();
    await act(async () => { button("Promote to Production")!.click(); });
    expect(started).toEqual([{ promote: true }]);
  });

  it("moves the switch and saves it", async () => {
    status = { target: "test", test: null, production: null, test_address: "https://acme-test.vercel.app",
               untested_changes: true, test_ahead: false };
    await render();
    const prod = [...document.body.querySelectorAll('[role="radio"]')].find((b) => b.textContent?.includes("Production")) as HTMLButtonElement;
    expect(prod.getAttribute("aria-checked")).toBe("false");
    await act(async () => { prod.click(); });
    expect(puts).toEqual([["/api/projects/p1/publish-target", { target: "production" }]]);
  });

  it("can start the test data again from demo data", async () => {
    status = { target: "test", test: side("https://acme-test.vercel.app"), production: null,
               test_address: "https://acme-test.vercel.app", untested_changes: true, test_ahead: false };
    await render();
    const box = [...document.body.querySelectorAll('input[type="checkbox"]')][0] as HTMLInputElement;
    await act(async () => { box.click(); });
    await act(async () => { button("Publish to Test")!.click(); });
    expect(started).toEqual([{ environment: "test", reset_test_data: true }]);
  });

  it("shows both addresses in the toolbar, the live app at its Tentoro address, whichever way the switch is set", async () => {
    status = { target: "test", test: side("https://acme-test.vercel.app"), production: side("https://acme.vercel.app"),
               test_address: "https://acme-test.vercel.app", production_address: "https://acme.apps.tentoro.ai",
               untested_changes: false, test_ahead: false };
    await render(<PublishButton projectId="p1" />);
    const links = [...host.querySelectorAll("a")].map((a) => [a.textContent?.trim(), a.getAttribute("href")]);
    expect(links).toEqual([
      ["Liveacme.apps.tentoro.ai", "https://acme.apps.tentoro.ai"],
      ["Testacme-test.vercel.app", "https://acme-test.vercel.app"],
    ]);
    expect(host.textContent).not.toContain("acme.vercel.app");
  });

  it("shows the live app at its Vercel address while it has no other", async () => {
    status = { target: "production", test: null, production: side("https://acme.vercel.app"),
               test_address: "https://acme-test.vercel.app", production_address: "https://acme.vercel.app",
               untested_changes: true, test_ahead: false };
    await render(<PublishButton projectId="p1" />);
    expect([...host.querySelectorAll("a")].map((a) => a.getAttribute("href"))).toEqual(["https://acme.vercel.app"]);
  });

  it("the dialog's summary names the live app's main address", async () => {
    status = { target: "production", test: null, production: side("https://acme.vercel.app"),
               test_address: "https://acme-test.vercel.app", production_address: "https://acme.apps.tentoro.ai",
               untested_changes: true, test_ahead: false };
    await render();
    expect(document.body.textContent).toContain("acme.apps.tentoro.ai");
  });
});
