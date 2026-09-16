/**
 * A screen that changes without the server.
 *
 * The calculator that shipped had a table to hold its display and a workflow
 * per key, and no key that did anything. This is the whole path the fix
 * relies on, end to end: the page declares `clientState`, the Engine seeds it,
 * a Button's `clientAction` changes it, and the binding under it repaints —
 * with no fetch, no workflow and nothing written down.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Engine } from "../src/Engine";

function calculator() {
  return {
    schemaVersion: "2",
    id: "calculator",
    dataSources: [],
    clientState: [{ name: "display", type: "string", initial: "0" }],
    root: {
      type: "Stack", id: "r", children: [
        { type: "Text", id: "d", props: { content: "{{state.display}}" } },
        { type: "Button", id: "k7", props: {
          label: "7",
          clientAction: { kind: "compute", target: "display", formula: "display + '7'" },
        } },
        { type: "Button", id: "kc", props: {
          label: "Clear",
          clientAction: { kind: "set", target: "display", value: "0" },
        } },
      ],
    },
  } as any;
}

describe("Engine — the screen's own values", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: (query: string) => ({
        matches: false, media: query, onchange: null,
        addEventListener: () => {}, removeEventListener: () => {},
        addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
      }),
    });
  });

  it("paints a declared value at what it starts at", async () => {
    render(<Engine schema={calculator()} apiBaseUrl="" />);
    expect(await screen.findByText("0")).toBeTruthy();
  });

  it("a key changes the display and calls nothing", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);

    render(<Engine schema={calculator()} apiBaseUrl="" />);
    fireEvent.click(await screen.findByRole("button", { name: /^7$/ }));

    await waitFor(() => expect(screen.getByText("07")).toBeTruthy());
    // NOTHING IS STORED. The point of the whole contract: no workflow, no row,
    // no table for a number nobody wants kept.
    expect(fetchMock.mock.calls.filter((c) => String(c[0]).includes("/api"))).toEqual([]);
  });

  it("Clear puts it back", async () => {
    render(<Engine schema={calculator()} apiBaseUrl="" />);
    fireEvent.click(await screen.findByRole("button", { name: /^7$/ }));
    await waitFor(() => expect(screen.getByText("07")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /Clear/i }));
    await waitFor(() => expect(screen.getByText("0")).toBeTruthy());
  });

  it("a page that declares none renders exactly as before", async () => {
    const plain = {
      schemaVersion: "2", id: "p", dataSources: [],
      root: { type: "Stack", id: "r", children: [
        { type: "Text", id: "t", props: { content: "Nurses" } }] },
    } as any;
    render(<Engine schema={plain} apiBaseUrl="" />);
    expect(await screen.findByText("Nurses")).toBeTruthy();
  });
});
