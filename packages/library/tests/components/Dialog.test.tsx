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
  it("renders nothing when no DialogStateContext provider is mounted", () => {
    const { container } = render(<Dialog id="x" title="No Provider">body</Dialog>);
    // Closed → Radix Dialog.Portal renders nothing in the DOM.
    expect(container.querySelector('[role="dialog"]')).toBeNull();
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
