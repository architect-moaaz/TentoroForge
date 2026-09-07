import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NavigatorProvider } from "@tentoroforge/renderer";
import { CommandPalette } from "../../src/components/CommandPalette/CommandPalette";
import { DesignTimeProvider } from "../../src/util/designTime";

const ITEMS = [
  { id: "go-dash", label: "Go to dashboard", group: "Pages", action: { type: "navigate", to: "/" } },
  { id: "create", label: "Create record", group: "Actions", action: { type: "workflow", workflow: "createRecord" } },
] as any;

function openWithShortcut() {
  fireEvent.keyDown(document, { key: "k", code: "KeyK", ctrlKey: true });
}

describe("CommandPalette — the shortcut printed on its own face", () => {
  it("Ctrl+K opens it", async () => {
    render(<CommandPalette items={ITEMS} />);
    expect(screen.queryByRole("dialog")).toBeNull();
    openWithShortcut();
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("matches the trigger key case-insensitively", async () => {
    // Caps Lock, or a Shift-modified layout, reports `e.key` as "K" while the
    // seed is "k". Strict equality missed, and the button advertised a shortcut
    // that did nothing.
    render(<CommandPalette items={ITEMS} />);
    fireEvent.keyDown(document, { key: "K", code: "KeyK", metaKey: true });
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("matches by physical key when the layout reports a different letter", async () => {
    // Dvorak / AZERTY / Cyrillic: `e.key` is not the Latin letter at all.
    render(<CommandPalette items={ITEMS} />);
    fireEvent.keyDown(document, { key: "л", code: "KeyK", ctrlKey: true });
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("needs the modifier — a bare 'k' never opens it", () => {
    render(<CommandPalette items={ITEMS} />);
    fireEvent.keyDown(document, { key: "k", code: "KeyK" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("CommandPalette — it does not take the editor's keyboard", () => {
  it("registers no document shortcut inside a design-time surface", () => {
    // The round-4/5 trap: every palette dropped on a canvas fighting the editor
    // for Ctrl+K. Making the shortcut work and keeping the canvas out of it are
    // the same requirement.
    render(
      <DesignTimeProvider>
        <CommandPalette items={ITEMS} />
      </DesignTimeProvider>,
    );
    openWithShortcut();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("CommandPalette — modal semantics and focus", () => {
  it("announces itself as a modal dialog", async () => {
    render(<CommandPalette items={ITEMS} />);
    openWithShortcut();
    const dlg = await screen.findByRole("dialog");
    expect(dlg).toHaveAttribute("aria-modal", "true");
    expect(dlg).toHaveAccessibleName("Command palette");
  });

  it("moves focus into the search box on open", async () => {
    render(<CommandPalette items={ITEMS} />);
    openWithShortcut();
    const input = await screen.findByPlaceholderText(/type a command/i);
    await waitFor(() => expect(document.activeElement).toBe(input));
  });

  it("gives focus back to the trigger on close, and never steals it on mount", async () => {
    const { container } = render(
      <>
        <input data-testid="elsewhere" />
        <CommandPalette items={ITEMS} />
      </>,
    );
    const elsewhere = screen.getByTestId("elsewhere");
    elsewhere.focus();
    expect(document.activeElement).toBe(elsewhere); // mount did not take focus

    openWithShortcut();
    await screen.findByRole("dialog");
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() =>
      expect(document.activeElement).toBe(
        container.querySelector('button[aria-haspopup="dialog"]'),
      ),
    );
  });
});

describe("CommandPalette — a navigate command goes through the Navigator", () => {
  it("uses the host navigator rather than window.location", async () => {
    // `window.location.assign("/")` resolved against the ORIGIN root, so
    // "Go to dashboard" on /p/<project>/<page> 404'd. Every other
    // schema-driven navigation goes through this seam; this one was missed.
    const push = vi.fn();
    render(
      <NavigatorProvider value={{ push, replace: vi.fn(), back: vi.fn() } as any}>
        <CommandPalette items={ITEMS} />
      </NavigatorProvider>,
    );
    openWithShortcut();
    await screen.findByRole("dialog");
    await userEvent.click(await screen.findByText("Go to dashboard"));
    expect(push).toHaveBeenCalledWith("/");
  });
});
