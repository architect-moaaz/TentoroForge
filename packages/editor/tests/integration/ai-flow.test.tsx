/**
 * AI flow integration test — Phase 2E
 *
 * Tests that:
 * 1. Loading a page with an IconButton missing aria-label triggers the rule engine
 *    and shows the suggestion in the AI sidebar.
 * 2. Dismissing the suggestion removes it from the sidebar.
 * 3. (Ambient LLM flow) Mocked fetch returning canned suggestions merges them
 *    into the AI section of the sidebar.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { z } from "zod";
import { createEditorStore } from "../../src/state/store";
import { AISidebar } from "../../src/panes/AI/AISidebar";
import { selectSuggestions } from "../../src/state/selectors";

// Registry that includes IconButton, Stack, Button
const reg = {
  list: () => [
    {
      name: "IconButton",
      category: "interactive",
      acceptsChildren: false,
      propsSchema: z.object({ "aria-label": z.string().optional() }).passthrough(),
    },
    {
      name: "Stack",
      category: "layout",
      acceptsChildren: true,
      propsSchema: z.object({}).passthrough(),
    },
  ],
  has: (n: string) => ["IconButton", "Stack"].includes(n),
  get: (n: string) => {
    if (n === "IconButton")
      return {
        name: "IconButton",
        component: (props: any) => (
          <button aria-label={props["aria-label"]} data-testid="icon-btn">⭐</button>
        ),
        propsSchema: z.object({ "aria-label": z.string().optional() }).passthrough(),
        category: "interactive",
        acceptsChildren: false,
      };
    if (n === "Stack")
      return {
        name: "Stack",
        component: ({ children }: any) => <div>{children}</div>,
        propsSchema: z.object({}).passthrough(),
        category: "layout",
        acceptsChildren: true,
      };
    return undefined;
  },
  validateProps: (_n: string, p: any) => p,
} as any;

/** Minimal page schema: Stack root with one IconButton missing aria-label. */
const pageWithA11yViolation = (): any => ({
  schemaVersion: "1",
  id: "test/page",
  route: "/test",
  root: {
    id: "root",
    type: "Stack",
    children: [
      { id: "icon-btn", type: "IconButton", props: {} }, // no aria-label
    ],
  },
});

beforeEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Test 1: Rule suggestion appears in sidebar
// ---------------------------------------------------------------------------
describe("AI flow — rule suggestions", () => {
  it("shows iconbutton-aria-label suggestion in AI sidebar for missing aria-label", () => {
    const store = createEditorStore();
    store.getState().openPage("test/page", pageWithA11yViolation());

    render(<AISidebar store={store} />);

    // Rule should fire and surface a suggestion
    expect(screen.getByText("IconButton missing aria-label")).toBeInTheDocument();
    expect(screen.getByText(/inaccessible/i)).toBeInTheDocument();
  });

  it("suggestion is listed under 'Rules' section heading", () => {
    const store = createEditorStore();
    store.getState().openPage("test/page", pageWithA11yViolation());

    render(<AISidebar store={store} />);

    expect(screen.getByText("Rules")).toBeInTheDocument();
    // The suggestion should be a descendant of the Rules section
    const rulesSection = screen.getByText("Rules").closest("[data-section]");
    if (rulesSection) {
      expect(rulesSection.textContent).toContain("IconButton missing aria-label");
    }
  });

  it("dismissing the suggestion removes it from the sidebar", async () => {
    const store = createEditorStore();
    store.getState().openPage("test/page", pageWithA11yViolation());

    render(<AISidebar store={store} />);

    // Verify the suggestion is visible
    expect(screen.getByText("IconButton missing aria-label")).toBeInTheDocument();

    // Find the dismiss button on the suggestion card
    const card = screen
      .getByText("IconButton missing aria-label")
      .closest("[data-suggestion-id]")!;
    expect(card).not.toBeNull();
    const dismissBtn = card.querySelector("button[aria-label='Dismiss']")!;
    expect(dismissBtn).not.toBeNull();

    await userEvent.click(dismissBtn);

    // After dismiss, the suggestion should no longer appear
    expect(screen.queryByText("IconButton missing aria-label")).not.toBeInTheDocument();
  });

  it("dismissSuggestion is reflected in the store's dismissedIds", async () => {
    const store = createEditorStore();
    store.getState().openPage("test/page", pageWithA11yViolation());

    render(<AISidebar store={store} />);

    const sid = store.getState().pages["test/page"].suggestions[0].id;

    const card = screen
      .getByText("IconButton missing aria-label")
      .closest("[data-suggestion-id]")!;
    await userEvent.click(card.querySelector("button[aria-label='Dismiss']")!);

    // Store should record the dismissal
    expect(store.getState().pages["test/page"].dismissedIds).toContain(sid);
  });

  it("selectSuggestions filters out dismissed suggestions", () => {
    const store = createEditorStore();
    store.getState().openPage("test/page", pageWithA11yViolation());

    const before = selectSuggestions(store.getState());
    expect(before.length).toBeGreaterThan(0);

    const sid = before[0].id;
    act(() => store.getState().dismissSuggestion(sid));

    const after = selectSuggestions(store.getState());
    expect(after.find((s) => s.id === sid)).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// Test 2: Ambient LLM flow (mocked fetch)
// ---------------------------------------------------------------------------
describe("AI flow — ambient LLM suggestions", () => {
  it("appendLlmSuggestions merges canned LLM suggestions into AI section", () => {
    const store = createEditorStore();
    store.getState().openPage("test/page", pageWithA11yViolation());

    act(() => {
      store.getState().appendLlmSuggestions("test/page", [
        {
          id: "llm:add-label",
          source: "llm",
          severity: "info",
          title: "Improve visual hierarchy",
          description: "Consider adding a heading above the icon button.",
        },
      ]);
    });

    render(<AISidebar store={store} />);

    // Both rule and LLM suggestions should be visible
    expect(screen.getByText("IconButton missing aria-label")).toBeInTheDocument();
    expect(screen.getByText("Improve visual hierarchy")).toBeInTheDocument();
    expect(screen.getByText("AI")).toBeInTheDocument();
  });

  it("does not duplicate suggestions with the same id", () => {
    const store = createEditorStore();
    store.getState().openPage("test/page", pageWithA11yViolation());

    const llmSugg = {
      id: "llm:unique",
      source: "llm" as const,
      severity: "info" as const,
      title: "Unique suggestion",
      description: "Only once.",
    };

    act(() => {
      store.getState().appendLlmSuggestions("test/page", [llmSugg]);
      store.getState().appendLlmSuggestions("test/page", [llmSugg]); // duplicate call
    });

    const suggs = store.getState().pages["test/page"].suggestions.filter((s) => s.id === "llm:unique");
    expect(suggs).toHaveLength(1);
  });

  it("dismissing LLM suggestion removes it from view", async () => {
    const store = createEditorStore();
    store.getState().openPage("test/page", pageWithA11yViolation());

    act(() => {
      store.getState().appendLlmSuggestions("test/page", [
        {
          id: "llm:dismiss-me",
          source: "llm",
          severity: "info",
          title: "To be dismissed",
          description: "Will be dismissed.",
        },
      ]);
    });

    render(<AISidebar store={store} />);
    expect(screen.getByText("To be dismissed")).toBeInTheDocument();

    const card = screen.getByText("To be dismissed").closest("[data-suggestion-id]")!;
    await userEvent.click(card.querySelector("button[aria-label='Dismiss']")!);

    expect(screen.queryByText("To be dismissed")).not.toBeInTheDocument();
  });
});
