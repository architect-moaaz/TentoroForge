import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { z } from "zod";
import { Editor } from "../../src/Editor";

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

const defaultThemeTokens = {
  colors: { "primary.500": "#3b82f6", "neutral.0": "#ffffff" },
  spacing: { "spacing.4": "1rem" },
};

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("theme flow", () => {
  it("load editor → open theme pane (Cmd+T) → change a color → save → verify saveTheme called", async () => {
    let savedThemeBody: any = null;

    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const urlStr = typeof url === "string" ? url : String(url);

        if (urlStr.includes("/api/editor/pages")) {
          return new Response(JSON.stringify({ paths: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (urlStr.includes("/api/editor/theme") && (!init || init.method === "GET" || !init.method)) {
          return new Response(
            JSON.stringify({ tokens: defaultThemeTokens, source: "default" }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          );
        }
        if (urlStr.includes("/api/editor/theme") && init?.method === "POST") {
          savedThemeBody = JSON.parse(init.body as string);
          return new Response(JSON.stringify({ ok: true }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        return new Response("404", { status: 404 });
      })
    );

    render(<Editor registry={reg} tokens={tokens} />);

    // Wait for the theme to load (the GET request resolves)
    await waitFor(
      () => {
        // Theme was loaded when at least one fetch for /api/editor/theme was made
        const fetchMock = vi.mocked(fetch as any);
        const themeCalls = fetchMock.mock.calls.filter(([url]: [string]) =>
          typeof url === "string" && url.includes("/api/editor/theme")
        );
        expect(themeCalls.length).toBeGreaterThan(0);
      },
      { timeout: 3000 }
    );

    // Open the theme pane via Cmd+T
    const user = userEvent.setup();
    await user.keyboard("{Meta>}t{/Meta}");

    // Theme editor should be visible — shows "Save theme" button and token groups
    await waitFor(
      () => expect(screen.getByRole("button", { name: /save theme/i })).toBeInTheDocument(),
      { timeout: 3000 }
    );

    // The primary.500 token should appear (it's in the default theme)
    expect(screen.getByLabelText("primary.500")).toBeInTheDocument();

    // Change the primary.500 color via the text input (exact label, not the color picker)
    const colorInput = screen.getByLabelText("primary.500") as HTMLInputElement;
    await userEvent.clear(colorInput);
    await userEvent.type(colorInput, "#ff0000");

    // The Save theme button should now be enabled (theme is dirty)
    const saveBtn = screen.getByRole("button", { name: /save theme/i });
    expect(saveBtn).not.toBeDisabled();

    // Click save
    await userEvent.click(saveBtn);

    // Verify POST to /api/editor/theme was called with updated token
    await waitFor(
      () => expect(savedThemeBody).not.toBeNull(),
      { timeout: 3000 }
    );
    expect(savedThemeBody.tokens.colors["primary.500"]).toBe("#ff0000");
  });
});
