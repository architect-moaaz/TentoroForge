import { describe, it, expect } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AISidebar } from "../../src/panes/AI/AISidebar";
import { createEditorStore } from "../../src/state/store";

const page = (): any => ({
  schemaVersion: "1",
  id: "p",
  route: "/",
  root: {
    id: "r",
    type: "Stack",
    children: [
      { id: "btn", type: "IconButton", props: {} }, // missing aria-label → rule fires
    ],
  },
});

describe("AISidebar", () => {
  it("renders rule suggestions section with violations", () => {
    const store = createEditorStore();
    store.getState().openPage("p", page());
    render(<AISidebar store={store} />);
    // Should show the iconbutton rule suggestion title
    expect(screen.getByText("IconButton missing aria-label")).toBeInTheDocument();
  });

  it("renders AI section when LLM suggestions present", () => {
    const store = createEditorStore();
    store.getState().openPage("p", page());
    act(() => {
      store.getState().appendLlmSuggestions("p", [
        {
          id: "llm:1",
          source: "llm",
          severity: "info",
          title: "AI suggestion",
          description: "Try this improvement",
        },
      ]);
    });
    render(<AISidebar store={store} />);
    expect(screen.getByText("AI suggestion")).toBeInTheDocument();
    expect(screen.getByText("Try this improvement")).toBeInTheDocument();
  });

  it("groups suggestions by source: Rules vs AI", () => {
    const store = createEditorStore();
    store.getState().openPage("p", page());
    act(() => {
      store.getState().appendLlmSuggestions("p", [
        {
          id: "llm:1",
          source: "llm",
          severity: "info",
          title: "AI suggestion",
          description: "Try this",
        },
      ]);
    });
    render(<AISidebar store={store} />);
    // Both section headings should be present
    expect(screen.getByText("Rules")).toBeInTheDocument();
    expect(screen.getByText("AI")).toBeInTheDocument();
  });

  it("Dismiss removes the suggestion from view", async () => {
    const store = createEditorStore();
    store.getState().openPage("p", page());
    render(<AISidebar store={store} />);

    // Find the suggestion card by its exact title
    const card = screen.getByText("IconButton missing aria-label").closest("[data-suggestion-id]")!;
    expect(card).toBeTruthy();
    const dismissBtn = card.querySelector("button[aria-label='Dismiss']");
    expect(dismissBtn).toBeTruthy();
    await userEvent.click(dismissBtn!);

    // The suggestion should no longer appear
    expect(screen.queryByText("IconButton missing aria-label")).not.toBeInTheDocument();
  });

  it("shows Apply button only when fix is present", () => {
    const store = createEditorStore();
    store.getState().openPage("p", page());
    act(() => {
      store.getState().appendLlmSuggestions("p", [
        {
          id: "llm:no-fix",
          source: "llm",
          severity: "info",
          title: "No fix suggestion",
          description: "LLM has no fix",
        },
        {
          id: "llm:with-fix",
          source: "llm",
          severity: "warn",
          title: "Has fix suggestion",
          description: "LLM has a fix",
          fix: {
            kind: "set-prop" as const,
            id: "btn",
            key: "aria-label",
            value: "Close",
            prevValue: undefined,
          },
        },
      ]);
    });
    render(<AISidebar store={store} />);

    // Card with fix should have Apply button
    const withFix = screen.getByText("Has fix suggestion").closest("[data-suggestion-id]")!;
    expect(withFix.querySelector("button[aria-label='Apply']")).toBeTruthy();

    // Card without fix should not have Apply button
    const noFix = screen.getByText("No fix suggestion").closest("[data-suggestion-id]")!;
    expect(noFix.querySelector("button[aria-label='Apply']")).toBeFalsy();
  });

  it("Apply dispatches fix and dismisses suggestion", async () => {
    const store = createEditorStore();
    store.getState().openPage("p", page());
    act(() => {
      store.getState().appendLlmSuggestions("p", [
        {
          id: "llm:with-fix",
          source: "llm",
          severity: "warn",
          title: "Has fix suggestion",
          description: "LLM has a fix",
          fix: {
            kind: "set-prop" as const,
            id: "btn",
            key: "aria-label",
            value: "Close",
            prevValue: undefined,
          },
        },
      ]);
    });
    render(<AISidebar store={store} />);

    const card = screen.getByText("Has fix suggestion").closest("[data-suggestion-id]")!;
    const applyBtn = card.querySelector("button[aria-label='Apply']")!;
    await userEvent.click(applyBtn);

    // Suggestion dismissed
    expect(screen.queryByText("Has fix suggestion")).not.toBeInTheDocument();
    // Prop applied
    const root = store.getState().pages["p"].schema.root as any;
    const btn = root.children[0];
    expect(btn.props["aria-label"]).toBe("Close");
  });

  it("shows empty state message when no suggestions", () => {
    const store = createEditorStore();
    // Page with no rule violations
    store.getState().openPage("p", {
      schemaVersion: "1",
      id: "p",
      route: "/",
      root: { id: "r", type: "Stack", children: [] },
    } as any);
    render(<AISidebar store={store} />);
    expect(screen.getByText(/no suggestions/i)).toBeInTheDocument();
  });
});
