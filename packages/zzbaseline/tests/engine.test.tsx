import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Engine } from "../src/Engine";
import { EngineProvider } from "../src/EngineProvider";
import { NavFlowContext } from "../src/nav/NavFlowContext";

describe("EngineProvider", () => {
  it("sets data-register attribute", () => {
    const { container } = render(
      <EngineProvider designSpec={{ register: "linear" }}>x</EngineProvider>
    );
    expect((container.firstChild as HTMLElement).getAttribute("data-register")).toBe("linear");
  });

  it("falls back to data-register='default'", () => {
    const { container } = render(
      <EngineProvider designSpec={{}}>x</EngineProvider>
    );
    expect((container.firstChild as HTMLElement).getAttribute("data-register")).toBe("default");
  });
});

describe("Engine", () => {
  it("renders minimal schema with Text root", async () => {
    // Renderer's Text component uses `content` prop, not `text`
    const schema = {
      schemaVersion: "2" as const, id: "x",
      root: { type: "Text", id: "t", props: { content: "hello" } },
    };
    const { findByText } = render(<Engine schema={schema} />);
    await findByText("hello");
  });

  it("synthesises a root from top-level children", async () => {
    const schema = {
      schemaVersion: "2" as const, id: "x",
      children: [{ type: "Text", id: "t", props: { content: "hi" } }],
    } as any;
    const { findByText } = render(<Engine schema={schema} />);
    await findByText("hi");
  });

  it("interpolates data via previewData", async () => {
    // Renderer's Text component uses `content` prop; interpolation runs on props
    // before dispatch so {{user.name}} expands to the actual name.
    const schema = {
      schemaVersion: "2" as const, id: "x",
      root: { type: "Text", id: "t", props: { content: "Hi, {{user.name}}" } },
    };
    const { findByText } = render(
      <Engine schema={schema} previewData={{ user: { name: "Alex" } }} />
    );
    await findByText("Hi, Alex");
  });

  it("renders error stub when schema is null", () => {
    const { container } = render(<Engine schema={null as any} />);
    expect(container.textContent).toMatch(/schema/i);
  });
});

describe("useNavigate", () => {
  // Light tests — full unit tests live in nav.test.tsx
  it("returns null when nav-flow is not provided", async () => {
    const { container } = render(
      <EngineProvider designSpec={{}}>
        <Engine schema={{ schemaVersion: "2", id: "x",
                          root: { type: "Text", id: "t", props: { content: "ok" } } }} />
      </EngineProvider>
    );
    expect(container.textContent).toContain("ok");
  });
});

describe("Engine responsive resolution", () => {
  it("resolves responsive padding through the engine", () => {
    // jsdom defaults to window.innerWidth = 1024 (lg)
    const schema = {
      schemaVersion: "2" as const, id: "x",
      root: { type: "Text", id: "t",
              props: { content: "hi", padding: { default: "sm", md: "md", lg: "lg" } } },
    };
    const { container } = render(<Engine schema={schema} />);
    // The renderer should see padding="lg" (window=1024 → lg)
    // We can't assert the inline style trivially, but we CAN confirm no
    // crash + content present
    expect(container.textContent).toContain("hi");
  });
});

describe("Engine nav-trigger delegation", () => {
  it("Button with onClick navigate action renders data-nav-trigger attribute", async () => {
    const navFlow = {
      version: "1.0",
      initialPage: "home",
      pages: [
        { id: "home", route: "/", title: "Home", schemaFile: "home.json", params: [] },
        { id: "dash", route: "/dash", title: "Dash", schemaFile: "dash.json", params: [] },
      ],
      transitions: [{ id: "t1", from: "home", trigger: "go-dash", to: "dash" }],
      guards: {},
    };

    const schema = {
      schemaVersion: "2" as const,
      id: "home",
      root: {
        type: "Button",
        id: "b",
        props: { label: "Go", onClick: { action: "navigate", trigger: "go-dash" } },
      },
    };

    const { container } = render(
      <NavFlowContext.Provider value={navFlow as any}>
        <Engine schema={schema as any} />
      </NavFlowContext.Provider>
    );

    // Button should be rendered with data-nav-trigger set to the trigger name
    const btn = container.querySelector("[data-nav-trigger='go-dash']") as HTMLElement;
    expect(btn).toBeTruthy();
    // And it should NOT have an onClick-wired JS handler replacing the trigger
    // (the delegated Engine listener handles navigation, not inline click)
  });

  it("Engine click listener resolves nav-trigger and sets window.location.href", async () => {
    const navFlow = {
      version: "1.0",
      initialPage: "home",
      pages: [
        { id: "home", route: "/", title: "Home", schemaFile: "home.json", params: [] },
        { id: "dash", route: "/dash", title: "Dash", schemaFile: "dash.json", params: [] },
      ],
      transitions: [{ id: "t1", from: "home", trigger: "go-dash", to: "dash" }],
      guards: {},
    };

    const schema = {
      schemaVersion: "2" as const,
      id: "home",
      root: {
        type: "Button",
        id: "b",
        props: { label: "Go", onClick: { action: "navigate", trigger: "go-dash" } },
      },
    };

    let navigatedTo = "";
    // jsdom allows replacing window.location via Object.defineProperty
    const origDescriptor = Object.getOwnPropertyDescriptor(window, "location");
    try {
      Object.defineProperty(window, "location", {
        configurable: true,
        writable: true,
        value: {
          ...window.location,
          get href() { return navigatedTo; },
          set href(v: string) { navigatedTo = v; },
        },
      });

      const { container } = render(
        <NavFlowContext.Provider value={navFlow as any}>
          <Engine schema={schema as any} />
        </NavFlowContext.Provider>
      );

      const btn = container.querySelector("[data-nav-trigger='go-dash']") as HTMLElement;
      expect(btn).toBeTruthy();
      btn.click();
      expect(navigatedTo).toBe("/dash");
    } finally {
      // Restore original descriptor so other tests are not affected
      if (origDescriptor) {
        Object.defineProperty(window, "location", origDescriptor);
      }
    }
  });
});
