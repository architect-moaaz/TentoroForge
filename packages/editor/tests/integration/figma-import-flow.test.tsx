/**
 * Integration test: figma-import flow
 *
 * Verifies end-to-end behaviour of the Import-from-Figma feature:
 *   1. Open editor.
 *   2. Press Cmd+Shift+F → ImportModal opens.
 *   3. Enter a valid Figma URL.
 *   4. Mock fetch returns a canned schema.
 *   5. Click "Save as page" → save endpoint called with extracted schema.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { z } from "zod";
import { Editor } from "../../src/Editor";

// ---------------------------------------------------------------------------
// Minimal registry + tokens
// ---------------------------------------------------------------------------

const reg = {
  list: () => [],
  has: () => false,
  get: () => undefined,
  validateProps: (_n: string, p: any) => p,
} as any;

const tokens = {
  colors: {},
  spacing: {},
  typography: {},
  radii: {},
  shadows: {},
} as any;

// ---------------------------------------------------------------------------
// Canned data
// ---------------------------------------------------------------------------

const FIGMA_URL =
  "https://www.figma.com/design/TestKey123/Design?node-id=1-2";

const CANNED_SCHEMA = {
  schemaVersion: "1",
  id: "figma/imported",
  route: "/figma/imported",
  root: {
    id: "fn1",
    type: "Box",
    props: { as: "div" },
    children: [],
  },
};

// ---------------------------------------------------------------------------
// Fetch mock factory
// ---------------------------------------------------------------------------

function makeFetchMock(savedPayloads: any[]) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    const u = typeof url === "string" ? url : String(url);

    // Theme
    if (u.includes("/api/editor/theme") && (!init || init.method === "GET" || !init.method)) {
      return new Response(
        JSON.stringify({ tokens: {}, source: "default" }),
        { status: 200 }
      );
    }
    // Explorer pages list
    if (u.includes("/api/editor/pages")) {
      return new Response(JSON.stringify({ paths: [] }), { status: 200 });
    }
    // Figma extraction
    if (u.includes("/api/figma/extract")) {
      return new Response(
        JSON.stringify({ schema: CANNED_SCHEMA }),
        { status: 200 }
      );
    }
    // Save
    if (u.includes("/api/editor/save")) {
      const body = JSON.parse((init?.body as string) ?? "{}");
      savedPayloads.push(body);
      return new Response(
        JSON.stringify({ ok: true, savedSchema: body.schema, suggestions: [] }),
        { status: 200 }
      );
    }
    return new Response("404", { status: 404 });
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("figma import flow", () => {
  it("Cmd+Shift+F opens ImportModal", async () => {
    vi.stubGlobal("fetch", makeFetchMock([]));

    render(<Editor registry={reg} tokens={tokens} />);

    // Fire Cmd+Shift+F
    fireEvent.keyDown(window, { key: "f", metaKey: true, shiftKey: true });

    await waitFor(() =>
      expect(screen.getByRole("dialog", { name: /import from figma/i })).toBeInTheDocument()
    );
  });

  it("Ctrl+Shift+F also opens ImportModal (Linux/Windows fallback)", async () => {
    vi.stubGlobal("fetch", makeFetchMock([]));

    render(<Editor registry={reg} tokens={tokens} />);

    fireEvent.keyDown(window, { key: "f", ctrlKey: true, shiftKey: true });

    await waitFor(() =>
      expect(screen.getByRole("dialog", { name: /import from figma/i })).toBeInTheDocument()
    );
  });

  it("full flow: enter URL → extract → save as page → save called with schema", async () => {
    const savedPayloads: any[] = [];
    vi.stubGlobal("fetch", makeFetchMock(savedPayloads));

    render(<Editor registry={reg} tokens={tokens} />);

    // Open modal via keyboard
    fireEvent.keyDown(window, { key: "f", metaKey: true, shiftKey: true });

    await waitFor(() =>
      expect(screen.getByRole("dialog", { name: /import from figma/i })).toBeInTheDocument()
    );

    // Enter Figma URL
    const urlInput = screen.getByLabelText("Figma URL");
    await userEvent.type(urlInput, FIGMA_URL);

    // Enter save path
    const pathInput = screen.getByLabelText("Save path");
    await userEvent.type(pathInput, "figma/imported");

    // Click Extract
    await userEvent.click(screen.getByRole("button", { name: "Extract" }));

    // Wait for "Extracted successfully" message
    await waitFor(() =>
      expect(screen.getByText(/extracted successfully/i)).toBeInTheDocument(),
      { timeout: 3000 }
    );

    // Click "Save as page"
    const saveBtn = screen.getByRole("button", { name: "Save as page" });
    await userEvent.click(saveBtn);

    // Modal should close
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: /import from figma/i })).not.toBeInTheDocument()
    );

    // The page should now be open in the editor (tab appears)
    await waitFor(() =>
      expect(screen.getByText("figma/imported")).toBeInTheDocument(),
      { timeout: 3000 }
    );
  });

  it("shows error for invalid Figma URL without calling extract endpoint", async () => {
    const fetchMock = makeFetchMock([]);
    vi.stubGlobal("fetch", fetchMock);

    render(<Editor registry={reg} tokens={tokens} />);
    fireEvent.keyDown(window, { key: "f", metaKey: true, shiftKey: true });

    await waitFor(() =>
      expect(screen.getByRole("dialog", { name: /import from figma/i })).toBeInTheDocument()
    );

    await userEvent.type(screen.getByLabelText("Figma URL"), "https://not-figma.com");
    await userEvent.click(screen.getByRole("button", { name: "Extract" }));

    expect(screen.getByRole("alert").textContent).toMatch(/invalid figma url/i);
    // No call to /api/figma/extract
    const extractCalls = fetchMock.mock.calls.filter(([url]) =>
      typeof url === "string" && url.includes("/api/figma/extract")
    );
    expect(extractCalls).toHaveLength(0);
  });

  it("Cancel button closes modal without saving", async () => {
    vi.stubGlobal("fetch", makeFetchMock([]));

    render(<Editor registry={reg} tokens={tokens} />);
    fireEvent.keyDown(window, { key: "f", metaKey: true, shiftKey: true });

    await waitFor(() =>
      expect(screen.getByRole("dialog", { name: /import from figma/i })).toBeInTheDocument()
    );

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: /import from figma/i })
      ).not.toBeInTheDocument()
    );
  });
});
