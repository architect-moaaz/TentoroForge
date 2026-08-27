import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Engine } from "../src/Engine";

function btnSchema(props: Record<string, unknown>) {
  return {
    schemaVersion: "2",
    id: "p",
    dataSources: [],
    root: { type: "Stack", id: "r", children: [{ type: "Button", id: "b", props }] },
  } as any;
}

describe("Engine — workflow dispatch wiring", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    // jsdom doesn't implement matchMedia, which the responsive hook uses.
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: (query: string) => ({
        matches: false, media: query, onchange: null,
        addEventListener: () => {}, removeEventListener: () => {},
        addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
      }),
    });
  });

  it("a Button with a workflow prop POSTs to /api/workflows/{name}/execute", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) });
    vi.stubGlobal("fetch", fetchMock);

    render(<Engine schema={btnSchema({ label: "Approve Entry", workflow: "entry-request-approval", args: { decision: "approve" } })} apiBaseUrl="" />);

    fireEvent.click(await screen.findByRole("button", { name: /Approve Entry/i }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) => String(c[0]).includes("/execute"));
      expect(call).toBeTruthy();
    });
    const call = fetchMock.mock.calls.find((c) => String(c[0]).includes("/execute"))!;
    expect(call[0]).toBe("/api/workflows/entry-request-approval/execute");
    expect(call[1].method).toBe("POST");
    expect(JSON.parse(call[1].body)).toEqual({ input: { decision: "approve" } });
  });

  it("honours apiBaseUrl prefix", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    render(<Engine schema={btnSchema({ label: "Go", workflow: "wf" })} apiBaseUrl="http://api.test" />);
    fireEvent.click(await screen.findByRole("button", { name: /Go/i }));
    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) => String(c[0]).includes("/execute"));
      expect(call?.[0]).toBe("http://api.test/api/workflows/wf/execute");
    });
  });

  it("stays inert in editor/preview mode (previewData set)", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    render(<Engine schema={btnSchema({ label: "Preview", workflow: "wf" })} apiBaseUrl="" previewData={{}} />);
    fireEvent.click(await screen.findByRole("button", { name: /Preview/i }));
    await new Promise((r) => setTimeout(r, 40));
    expect(fetchMock.mock.calls.filter((c) => String(c[0]).includes("/execute"))).toHaveLength(0);
  });
});
