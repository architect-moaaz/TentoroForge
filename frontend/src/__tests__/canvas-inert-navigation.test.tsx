/**
 * Regression — docs/editor-audit/panels.md, "Components — Redirect — BUG (drops
 * navigate the whole editor away)".
 *
 * `Redirect` calls nav.replace(to) in a mount effect with a registry default of
 * `to: "/"`. The editor canvas renders live library components and mounted NO
 * NavigatorProvider, so useNavigator() fell back to the window.location-backed
 * defaultNavigator: dropping Redirect from the palette hard-navigated the whole
 * editor SPA. Autosave is a 500 ms debounce, so the drop and everything in that
 * window were lost.
 *
 * These tests render the real library components under the real
 * NavigatorProvider with the canvas's INERT_NAVIGATOR and assert that no
 * navigation escapes to the browser.
 */
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import * as React from "react";
import { NavigatorProvider } from "@tentoroforge/renderer";
import { Redirect } from "@tentoroforge/library";
import { Engine, EngineProvider } from "@tentoroforge/engine";
import { INERT_NAVIGATOR } from "@/lib/inert-navigator";

// jsdom lacks matchMedia / ResizeObserver, which the renderer's ShellState and
// the layout components touch on mount.
if (typeof window !== "undefined" && !window.matchMedia) {
  (window as unknown as { matchMedia: unknown }).matchMedia = (query: string) => ({
    matches: false, media: query, onchange: null,
    addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; },
  });
}
if (typeof window !== "undefined" && !(window as any).ResizeObserver) {
  (window as any).ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
}

function withCanvasNavigator(ui: React.ReactNode) {
  return render(
    <NavigatorProvider value={INERT_NAVIGATOR}>{ui}</NavigatorProvider>,
  );
}

/** Replace window.location with a spy-able stand-in and hand back the spies. */
function stubLocation() {
  const spies = {
    assign: vi.fn(),
    replace: vi.fn(),
    reload: vi.fn(),
    href: "http://localhost:6501/editor/p",
    pathname: "/editor/p",
    hash: "",
    search: "",
  };
  const original = window.location;
  Object.defineProperty(window, "location", {
    configurable: true,
    writable: true,
    value: spies,
  });
  return {
    spies,
    restore: () =>
      Object.defineProperty(window, "location", {
        configurable: true,
        writable: true,
        value: original,
      }),
  };
}

afterEach(cleanup);

describe("editor canvas navigator — schema nodes cannot navigate the editor", () => {
  it("Redirect does NOT touch window.location when the canvas navigator is mounted", () => {
    const loc = stubLocation();
    try {
      withCanvasNavigator(<Redirect to="/" />);
      expect(loc.spies.replace).not.toHaveBeenCalled();
      expect(loc.spies.assign).not.toHaveBeenCalled();
    } finally {
      loc.restore();
    }
  });

  it("Redirect still renders its inert, selectable placeholder", () => {
    const loc = stubLocation();
    try {
      const { container } = withCanvasNavigator(<Redirect to="/orders" />);
      const el = container.querySelector('[data-redirect="/orders"]');
      expect(el).toBeTruthy();
      expect(el!.textContent).toContain("Redirecting");
    } finally {
      loc.restore();
    }
  });

  it("without the provider the SAME component navigates — proving the seam is what fixed it", () => {
    const loc = stubLocation();
    try {
      render(<Redirect to="/" />);
      expect(loc.spies.replace).toHaveBeenCalledWith("/");
    } finally {
      loc.restore();
    }
  });
});

describe("editor canvas navigator — click-driven navigation is inert too", () => {
  /**
   * Engine mounts a delegated [data-nav-trigger] click listener that resolves
   * through the SAME useNavigator() seam (packages/engine/src/Engine.tsx:213-227),
   * so a Button/Link/Table-row click on the canvas navigated the editor away
   * too. This renders the exact composition Canvas.tsx uses.
   */
  const schema = {
    schemaVersion: "2", id: "p", route: "/",
    root: {
      id: "root", type: "Stack", props: {}, children: [
        {
          id: "btn", type: "Button",
          props: { label: "Go", onClick: { action: "navigate", to: "/orders" } },
        },
      ],
    },
  };

  it("a Button navigate action does not leave the editor when clicked", () => {
    const loc = stubLocation();
    try {
      render(
        <NavigatorProvider value={INERT_NAVIGATOR}>
          <EngineProvider designSpec={{}} navFlow={undefined as never}>
            <Engine schema={schema as never} previewData={{}} />
          </EngineProvider>
        </NavigatorProvider>,
      );
      fireEvent.click(screen.getByRole("button", { name: "Go" }));
      expect(loc.spies.assign).not.toHaveBeenCalled();
      expect(loc.spies.replace).not.toHaveBeenCalled();
    } finally {
      loc.restore();
    }
  });

  it("the same click DOES navigate without the provider — the seam is what fixed it", () => {
    const loc = stubLocation();
    try {
      render(
        <EngineProvider designSpec={{}} navFlow={undefined as never}>
          <Engine schema={schema as never} previewData={{}} />
        </EngineProvider>,
      );
      fireEvent.click(screen.getByRole("button", { name: "Go" }));
      expect(loc.spies.assign).toHaveBeenCalledWith("/orders");
    } finally {
      loc.restore();
    }
  });
});
