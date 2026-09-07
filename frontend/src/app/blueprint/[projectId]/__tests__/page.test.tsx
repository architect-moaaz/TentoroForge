/**
 * /blueprint/[projectId] — the Pages → preview link (§113).
 *
 * Selecting a page under Pages used to set an iframe to
 * `/api/projects/<uuid>/preview/<route>`, which no route serves: the proxy
 * lives at `/preview/serve` under the project's SHORT id, and nothing had
 * started the dev server it forwards to. Every page opened a 404.
 *
 * Covered here:
 *   • selecting a page starts the preview and frames the served path
 *   • a preview already running is reused, not restarted
 *   • a start that fails says why, and offers to try again
 *
 * jsdom + createRoot + act(), same convention as the mcp-servers page test.
 * The inner `Workspace` is exercised so the Promise-wrapped `params` of the
 * default export need not be constructed.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

// Smith is a column of its own with its own transport; not under test here.
vi.mock("@/components/smith/SmithPanel", () => ({
  SmithPanel: () => null,
}));

const apiGet = vi.fn();
const apiPost = vi.fn();
vi.mock("@/lib/api", () => ({
  api: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
  },
}));

const PROJECT = "3f1c2a6e-0000-4000-8000-000000000001";
const SERVE = "/api/projects/abc12345/preview/serve";

const BLUEPRINT = {
  pages: [
    { id: "PAGE-001", name: "Dashboard", route: "/dashboard" },
    { id: "PAGE-002", name: "Tickets", route: "/tickets" },
  ],
};

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("Workspace — Pages open the live application", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    apiGet.mockReset();
    apiPost.mockReset();
    // The Blueprint itself is fetched directly, with the token.
    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      redirected: false,
      json: async () => BLUEPRINT,
    })) as unknown as typeof fetch;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  async function mount() {
    const { Workspace } = await import("../page");
    await act(async () => {
      root.render(<Workspace projectId={PROJECT} evidence={[]} />);
    });
    await flush();
  }

  function pageButton(name: string): HTMLButtonElement {
    const btn = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent === name,
    );
    if (!btn) throw new Error(`no page button "${name}"`);
    return btn;
  }

  it("starts the preview and frames the served route", async () => {
    apiGet.mockRejectedValue(new Error("Not running"));
    apiPost.mockResolvedValue({ port: 3210, servePath: SERVE });
    await mount();

    expect(container.querySelector("iframe")).toBeNull();

    await act(async () => {
      pageButton("Dashboard").click();
    });
    await flush();

    expect(apiPost).toHaveBeenCalledWith(`/api/projects/${PROJECT}/preview/start`);
    const frame = container.querySelector("iframe");
    expect(frame?.getAttribute("src")).toBe(`${SERVE}/dashboard`);

    // A second page navigates the running preview; it does not start another.
    await act(async () => {
      pageButton("Tickets").click();
    });
    await flush();
    expect(apiPost).toHaveBeenCalledTimes(1);
    expect(container.querySelector("iframe")?.getAttribute("src")).toBe(`${SERVE}/tickets`);
  });

  it("reuses a preview that is already running", async () => {
    apiGet.mockResolvedValue({ running: true, port: 3210, servePath: SERVE });
    await mount();

    await act(async () => {
      pageButton("Dashboard").click();
    });
    await flush();

    expect(apiPost).not.toHaveBeenCalled();
    expect(container.querySelector("iframe")?.getAttribute("src")).toBe(`${SERVE}/dashboard`);
  });

  it("says why a preview could not start, and offers to try again", async () => {
    apiGet.mockRejectedValue(new Error("Not running"));
    apiPost.mockRejectedValueOnce(
      new Error("No application to preview yet — nothing has been built into this project."),
    );
    await mount();

    await act(async () => {
      pageButton("Dashboard").click();
    });
    await flush();

    expect(container.querySelector("iframe")).toBeNull();
    expect(container.textContent).toContain("No application to preview yet");

    apiPost.mockResolvedValueOnce({ port: 3210, servePath: SERVE });
    await act(async () => {
      pageButton("Try again").click();
    });
    await flush();

    expect(apiPost).toHaveBeenCalledTimes(2);
    expect(container.querySelector("iframe")?.getAttribute("src")).toBe(`${SERVE}/dashboard`);
  });
});
