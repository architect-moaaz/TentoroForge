import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { z } from "zod";
import { Editor } from "../../src/Editor";

// Minimal DashboardLayout schema stub matching the real one
const dashboardLayoutSchema = {
  schemaVersion: "1",
  id: "DashboardLayout",
  root: {
    id: "dash-shell",
    type: "Heading",
    props: { level: 1, content: "DashboardLayout" },
  },
};

const reg = {
  list: () => [
    {
      name: "Heading",
      category: "static",
      acceptsChildren: false,
      propsSchema: z.object({ level: z.number(), content: z.string() }).strict(),
    },
  ],
  has: (n: string) => n === "Heading",
  get: (n: string) =>
    n === "Heading"
      ? {
          name: "Heading",
          component: ({ content }: any) => <h1>{content}</h1>,
          propsSchema: z
            .object({ level: z.number(), content: z.string() })
            .strict(),
          category: "static",
          acceptsChildren: false,
        }
      : undefined,
  validateProps: (_n: string, p: any) => p,
} as any;

const tokens = {
  colors: {},
  spacing: {},
  typography: {},
  radii: {},
  shadows: {},
} as any;

function makeFetch(extraPaths: string[] = []) {
  return vi.fn(async (url: string, _init?: RequestInit) => {
    if (typeof url === "string" && url.includes("/api/editor/pages")) {
      return new Response(
        JSON.stringify({ paths: ["products/list", "_layouts/DashboardLayout", ...extraPaths] }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    if (typeof url === "string" && url.includes("path=_layouts%2FDashboardLayout")) {
      return new Response(
        JSON.stringify({ schema: dashboardLayoutSchema }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    if (typeof url === "string" && url.includes("/api/editor/theme")) {
      return new Response(
        JSON.stringify({ tokens, source: "default" }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    return new Response("404", { status: 404 });
  });
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("layout flow", () => {
  it("Explorer shows Layouts section when _layouts/* paths are present", async () => {
    vi.stubGlobal("fetch", makeFetch());

    render(<Editor registry={reg} tokens={tokens} />);

    // The "Layouts" section heading is rendered in the Explorer
    await waitFor(() => expect(screen.getByText(/layouts/i)).toBeInTheDocument(), { timeout: 3000 });
    // The layout name appears as a clickable leaf
    expect(screen.getByText("DashboardLayout")).toBeInTheDocument();
  });

  it("opening _layouts/DashboardLayout shows the layout mode banner", async () => {
    vi.stubGlobal("fetch", makeFetch());

    render(<Editor registry={reg} tokens={tokens} />);

    // Wait for Explorer to list the layout
    await waitFor(() => screen.getByText("DashboardLayout"), { timeout: 3000 });

    // Click it to open
    await userEvent.click(screen.getByText("DashboardLayout"));

    // Banner text visible
    await waitFor(
      () =>
        expect(
          screen.getByText(/editing layout template.*slot nodes enabled/i)
        ).toBeInTheDocument(),
      { timeout: 3000 }
    );
  });

  it("Slot entry appears in Palette when a layout template is open", async () => {
    vi.stubGlobal("fetch", makeFetch());

    render(<Editor registry={reg} tokens={tokens} />);

    // Wait for layout leaf, then open it
    await waitFor(() => screen.getByText("DashboardLayout"), { timeout: 3000 });
    await userEvent.click(screen.getByText("DashboardLayout"));

    // Banner confirms layout mode
    await waitFor(
      () =>
        expect(
          screen.getByText(/editing layout template/i)
        ).toBeInTheDocument(),
      { timeout: 3000 }
    );

    // Slot item must be visible in the Palette
    expect(screen.getByText("Slot")).toBeInTheDocument();
    // Palette category "Layout" is visible
    expect(screen.getByText(/^Layout$/i)).toBeInTheDocument();
  });
});
