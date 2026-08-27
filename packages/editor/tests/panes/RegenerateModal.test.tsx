import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RegenerateModal } from "../../src/panes/AI/RegenerateModal";
import { createEditorStore } from "../../src/state/store";

// Mock the regenerateSection API call
vi.mock("../../src/save/api", () => ({
  regenerateSection: vi.fn(),
  saveSchema: vi.fn(),
  loadSchema: vi.fn(),
  listPages: vi.fn(),
  getTheme: vi.fn(),
  saveTheme: vi.fn(),
  getSuggestions: vi.fn(),
}));

import { regenerateSection } from "../../src/save/api";

const page = (): any => ({
  schemaVersion: "1",
  id: "p",
  route: "/",
  root: {
    id: "root",
    type: "Stack",
    children: [
      { id: "btn", type: "IconButton", props: {} },
    ],
  },
});

describe("RegenerateModal", () => {
  let store: ReturnType<typeof createEditorStore>;
  let onClose: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    store = createEditorStore();
    store.getState().openPage("p", page());
    store.getState().selectNode("btn");
    onClose = vi.fn();
    vi.clearAllMocks();
  });

  it("renders with subtree summary showing node type and id", () => {
    render(
      <RegenerateModal store={store} nodeId="btn" onClose={onClose} />
    );
    expect(screen.getByText("IconButton")).toBeInTheDocument();
    expect(screen.getByText(/#btn/)).toBeInTheDocument();
  });

  it("renders prompt textarea and Cancel + Regenerate buttons", () => {
    render(
      <RegenerateModal store={store} nodeId="btn" onClose={onClose} />
    );
    expect(screen.getByRole("textbox", { name: /prompt/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /regenerate/i })).toBeInTheDocument();
  });

  it("Cancel button calls onClose", async () => {
    render(
      <RegenerateModal store={store} nodeId="btn" onClose={onClose} />
    );
    await userEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("Regenerate button is disabled when prompt is empty", () => {
    render(
      <RegenerateModal store={store} nodeId="btn" onClose={onClose} />
    );
    const regenBtn = screen.getByRole("button", { name: /regenerate/i });
    expect(regenBtn).toBeDisabled();
  });

  it("shows thinking state while request is in progress", async () => {
    // Return a promise that we can control
    let resolve!: (v: any) => void;
    (regenerateSection as any).mockReturnValue(
      new Promise((r) => { resolve = r; })
    );

    render(
      <RegenerateModal store={store} nodeId="btn" onClose={onClose} />
    );
    await userEvent.type(screen.getByRole("textbox"), "Make it better");
    await userEvent.click(screen.getByRole("button", { name: /^regenerate$/i }));

    // Button label changes to "Thinking…" while waiting
    expect(screen.getByRole("button", { name: /thinking/i })).toBeInTheDocument();

    // Clean up
    act(() => resolve({ subtree: { id: "btn", type: "Stack", children: [] } }));
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /thinking/i })).not.toBeInTheDocument();
    });
  });

  it("shows proposed subtree JSON and Accept button after successful response", async () => {
    const newSubtree = { id: "btn", type: "Box", children: [] };
    (regenerateSection as any).mockResolvedValue({ subtree: newSubtree });

    render(
      <RegenerateModal store={store} nodeId="btn" onClose={onClose} />
    );
    await userEvent.type(screen.getByRole("textbox"), "Make it better");
    await userEvent.click(screen.getByRole("button", { name: /^regenerate$/i }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /accept/i })).toBeInTheDocument();
    });
    // Accept button should be enabled for valid node
    expect(screen.getByRole("button", { name: /accept/i })).not.toBeDisabled();
  });

  it("Accept dispatches composite mutation and calls onClose", async () => {
    const newSubtree = { id: "btn", type: "Box", children: [] };
    (regenerateSection as any).mockResolvedValue({ subtree: newSubtree });

    render(
      <RegenerateModal store={store} nodeId="btn" onClose={onClose} />
    );
    await userEvent.type(screen.getByRole("textbox"), "Make it a Stack");
    await userEvent.click(screen.getByRole("button", { name: /^regenerate$/i }));
    await waitFor(() => screen.getByRole("button", { name: /accept/i }));

    await userEvent.click(screen.getByRole("button", { name: /accept/i }));

    expect(onClose).toHaveBeenCalledOnce();
    // The replaced node should now be Box in the store
    const root = store.getState().pages["p"].schema.root as any;
    const replaced = root.children[0];
    expect(replaced.type).toBe("Box");
  });

  it("shows error message when API call fails", async () => {
    (regenerateSection as any).mockRejectedValue(new Error("Network error"));

    render(
      <RegenerateModal store={store} nodeId="btn" onClose={onClose} />
    );
    await userEvent.type(screen.getByRole("textbox"), "Try something");
    await userEvent.click(screen.getByRole("button", { name: /^regenerate$/i }));

    await waitFor(() => {
      expect(screen.getByText(/network error/i)).toBeInTheDocument();
    });
  });
});
