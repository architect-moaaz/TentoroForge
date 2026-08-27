/**
 * /org/[orgId]/settings/mcp-servers — smoke.
 *
 * Covers the three shapes a human will actually notice:
 *   • empty state when the API returns []
 *   • table renders one row per registered server
 *   • clicking "Test" fires POST to the test endpoint
 *
 * jsdom + createRoot + act(), same convention as page-scaffold.test.tsx.
 * Because the Next.js page component takes a Promise-wrapped `params`,
 * we exercise the inner `McpServersSettings` (default export applies the
 * `use(params)` unwrap that we can't easily construct in vitest).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---- jsdom polyfills --------------------------------------------------------
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = ((q: string) => ({
    matches: false, media: q, onchange: null,
    addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; },
  })) as unknown as typeof window.matchMedia;
}
if (typeof window !== "undefined" && !(window as any).ResizeObserver) {
  (window as any).ResizeObserver = class {
    observe() {} unobserve() {} disconnect() {}
  };
}
if (typeof window !== "undefined" && !(window as any).PointerEvent) {
  (window as any).PointerEvent = class extends Event {} as any;
}
if (typeof Element !== "undefined" && !(Element.prototype as any).hasPointerCapture) {
  (Element.prototype as any).hasPointerCapture = () => false;
  (Element.prototype as any).releasePointerCapture = () => {};
  (Element.prototype as any).setPointerCapture = () => {};
  (Element.prototype as any).scrollIntoView = () => {};
}

// Silence the delete-row window.confirm — not exercised here but the button
// is present in the DOM.
if (typeof window !== "undefined") {
  window.confirm = () => true;
}

// ---- api mock ---------------------------------------------------------------
const apiGet = vi.fn<[string], Promise<unknown>>();
const apiPost = vi.fn<[string, unknown?], Promise<unknown>>(async () => ({
  ok: true,
  tool_count: 3,
}));
const apiPut = vi.fn<[string, unknown?], Promise<unknown>>();
const apiDelete = vi.fn<[string], Promise<unknown>>(async () => undefined);

vi.mock("@/lib/api", () => ({
  api: {
    get: (url: string) => apiGet(url),
    post: (url: string, body?: unknown) => apiPost(url, body),
    put: (url: string, body?: unknown) => apiPut(url, body),
    delete: (url: string) => apiDelete(url),
  },
}));

// sonner toast is not what we're asserting — silence side effects.
vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  },
}));

// Import AFTER mocks are registered.
import McpServersSettingsPage from "@/app/org/[orgId]/settings/mcp-servers/page";

// We render the default export by calling it as a function and passing a
// resolved-promise-like `params`. Next 15's `use()` reads the underlying
// value; a plain resolved promise works in tests.

let container: HTMLDivElement;
let root: Root;
let client: QueryClient;

async function renderPage() {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  const params = Promise.resolve({ orgId: "org_x" });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <McpServersSettingsPage params={params as any} />
      </QueryClientProvider>,
    );
  });
  // Give react-query a tick + the `use()` unwrap.
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
  await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
}

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockClear();
  apiPut.mockClear();
  apiDelete.mockClear();
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  client?.clear();
});

// =============================================================================
describe("McpServersSettingsPage — smoke", () => {
  it("renders the empty state when there are no registered servers", async () => {
    apiGet.mockResolvedValueOnce([]);
    await renderPage();

    expect(container.textContent).toContain("No MCP servers registered");
    // The "Add Server" primary button is always visible in the header.
    expect(
      container.querySelector('[data-testid="add-server-button"]'),
    ).toBeTruthy();
  });

  it("lists registered servers and exposes per-row Test buttons", async () => {
    apiGet.mockResolvedValueOnce([
      {
        id: "srv_1",
        name: "Firecrawl",
        server_url: "https://mcp.firecrawl.dev",
        transport: "http",
        auth_kind: "bearer",
        enabled: true,
      },
    ]);
    await renderPage();

    expect(container.textContent).toContain("Firecrawl");
    expect(container.textContent).toContain("https://mcp.firecrawl.dev");

    const testBtn = container.querySelector<HTMLButtonElement>(
      '[data-testid="test-button-srv_1"]',
    );
    expect(testBtn).toBeTruthy();
  });

  it("clicking Test fires POST to the test endpoint and surfaces the result", async () => {
    apiGet.mockResolvedValueOnce([
      {
        id: "srv_1",
        name: "Firecrawl",
        server_url: "https://mcp.firecrawl.dev",
        transport: "http",
        auth_kind: "bearer",
        enabled: true,
      },
    ]);
    await renderPage();

    const testBtn = container.querySelector<HTMLButtonElement>(
      '[data-testid="test-button-srv_1"]',
    )!;

    await act(async () => {
      testBtn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    // Let the promise resolve + state update commit.
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });

    const call = apiPost.mock.calls.find(([u]) =>
      String(u).endsWith("/api/orgs/org_x/mcp-servers/srv_1/test"),
    );
    expect(call).toBeTruthy();

    // Green badge appears with the tool count from the canned response.
    expect(
      container.querySelector('[data-testid="test-ok-srv_1"]'),
    ).toBeTruthy();
    expect(container.textContent).toMatch(/3 tools/);
  });
});
