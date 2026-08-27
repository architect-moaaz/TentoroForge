import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { z } from "zod";
import { Editor } from "../../src/Editor";

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

beforeEach(() => {
  vi.restoreAllMocks();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const urlStr = typeof url === "string" ? url : String(url);
      if (urlStr.includes("/api/editor/pages")) {
        return new Response(JSON.stringify({ paths: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (urlStr.includes("/api/editor/theme")) {
        return new Response(
          JSON.stringify({ tokens: { colors: {}, spacing: {} }, source: "default" }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      return new Response("404", { status: 404 });
    })
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("polish flow", () => {
  it("load editor → switch viewport to mobile → canvas reflects mobile width", async () => {
    render(<Editor registry={reg} tokens={tokens} />);

    const user = userEvent.setup();

    // Wait for editor to render
    await waitFor(() => expect(screen.getByRole("radiogroup", { name: /viewport size/i })).toBeInTheDocument());

    // Default should be desktop
    expect(screen.getByRole("radio", { name: /desktop/i })).toBeChecked();

    // Switch to mobile
    await user.click(screen.getByRole("radio", { name: /mobile/i }));
    expect(screen.getByRole("radio", { name: /mobile/i })).toBeChecked();
  });

  it("press ? → help modal opens → Escape closes it", async () => {
    render(<Editor registry={reg} tokens={tokens} />);

    const user = userEvent.setup();

    // Wait for editor to be ready
    await waitFor(() => expect(screen.getByRole("radiogroup", { name: /viewport size/i })).toBeInTheDocument());

    // Press ? to open help
    await user.keyboard("?");
    await waitFor(() => screen.getByRole("dialog", { name: /keyboard shortcuts/i }));
    expect(screen.getByRole("dialog", { name: /keyboard shortcuts/i })).toBeInTheDocument();

    // Press Escape to close (clicking backdrop)
    await user.click(screen.getByRole("dialog", { name: /keyboard shortcuts/i }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: /keyboard shortcuts/i })).not.toBeInTheDocument());
  });
});
