import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DialogStateProvider, useDialogState } from "@tentoroforge/renderer";
import { Dialog } from "../../src/components/Dialog/Dialog";

function TestOpener({ id }: { id: string }) {
  const dialogs = useDialogState();
  return (
    <button onClick={() => dialogs?.openDialog(id)} type="button">
      Open {id}
    </button>
  );
}

describe("Dialog", () => {
  // display 12 — with no provider the Portal rendered nothing: the editor node
  // measured 0×0 and swallowed any child dropped into it. Now the content
  // renders inline instead.
  it("renders its children inline when no DialogStateContext provider is mounted", () => {
    const { container, getByText } = render(
      <Dialog id="x" title="No Provider" description="desc">
        <span>inline child</span>
      </Dialog>,
    );
    // Not a modal — no Radix portal/overlay.
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    // …but the content is present and in place.
    const root = container.querySelector("[data-dialog-inline]");
    expect(root).not.toBeNull();
    expect(root!.getAttribute("data-node-id")).toBe("x");
    expect(getByText("inline child")).toBeInTheDocument();
    expect(getByText("No Provider")).toBeInTheDocument();
    expect(getByText("desc")).toBeInTheDocument();
  });

  it("applies className + StyleSlot on the provider-less inline fallback", () => {
    const { container } = render(
      <Dialog id="x" className="ring-2" style={{ padding: "tokens.spacing.4" } as any}>
        <span>child</span>
      </Dialog>,
    );
    const root = container.querySelector("[data-dialog-inline]") as HTMLElement;
    expect(root.className).toContain("ring-2");
    expect(root.style.padding).toBe("var(--token-spacing-4)");
  });

  it("stays closed (no inline fallback) when a provider IS mounted", () => {
    const { container } = render(
      <DialogStateProvider>
        <Dialog id="y" title="Closed">
          <span>hidden child</span>
        </Dialog>
      </DialogStateProvider>,
    );
    expect(container.querySelector("[data-dialog-inline]")).toBeNull();
    expect(screen.queryByText("hidden child")).toBeNull();
  });

  it("renders content when the engine opens it via openDialog(id)", async () => {
    const { user } = render(
      <DialogStateProvider>
        <TestOpener id="viewContact" />
        <Dialog id="viewContact" title="View contact" description="Prospect info">
          <p>Ahmed Al-Rashid</p>
        </Dialog>
      </DialogStateProvider>,
    ) as any;
    // Initially closed
    expect(screen.queryByText("View contact")).toBeNull();
    // Open via the engine's state hook
    const opener = screen.getByText("Open viewContact");
    opener.click();
    expect(await screen.findByText("View contact")).toBeInTheDocument();
    expect(screen.getByText("Prospect info")).toBeInTheDocument();
    expect(screen.getByText("Ahmed Al-Rashid")).toBeInTheDocument();
  });
});
