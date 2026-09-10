import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { DesignTimeProvider } from "@tentoroforge/renderer";
import { Drawer } from "../../src/components/Drawer/Drawer";
import { FocusRing } from "../../src/components/FocusRing/FocusRing";
import { HoverCard } from "../../src/components/HoverCard/HoverCard";
import { Tooltip } from "../../src/components/Tooltip/Tooltip";
import { CartPanel } from "../../src/components/CartPanel/CartPanel";

describe("Drawer does not modal-block the editor it is being built in", () => {
  it("opens fully modal in a running app", () => {
    const { container } = render(<Drawer trigger="Open" title="Panel" content="Body" />);
    fireEvent.click(screen.getByText("Open"));
    // The scrim is the whole point of a modal drawer.
    expect(document.querySelector(".fixed.inset-0")).not.toBeNull();
    expect(container).toBeTruthy();
  });

  it("opens without a scrim on an authoring surface", () => {
    // Measured on the canvas: the scrim was 1525x678 — the BROWSER VIEWPORT, not
    // the canvas frame — with `pointer-events: none` on the body, so the
    // palette, the pages rail and the Properties panel were all behind a modal
    // layer belonging to a node being edited. Radix portals to document.body,
    // so the drawer was not even on the page it belongs to.
    render(
      <DesignTimeProvider>
        <Drawer trigger="Open" title="Panel" content="Body" />
      </DesignTimeProvider>,
    );
    fireEvent.click(screen.getByText("Open"));
    expect(document.querySelector(".fixed.inset-0")).toBeNull();
    // Everything the author is trying to look at is still there.
    expect(screen.getByText("Panel")).toBeInTheDocument();
    expect(screen.getByText("Body")).toBeInTheDocument();
  });

  it("renders the accessible description Radix warns about when it is missing", () => {
    render(<Drawer trigger="Open" title="Panel" description="What this panel is for" content="Body" />);
    fireEvent.click(screen.getByText("Open"));
    expect(screen.getByText("What this panel is for")).toBeInTheDocument();
  });
});

describe("FocusRing carries its own rule", () => {
  it("emits a scoped stylesheet that reads the tokens it sets", () => {
    // The custom properties were set and inherited correctly and NOTHING
    // consumed them: the rule lived in a stylesheet reaching apps only through
    // a flag-gated backend pass, so the ring was absent on the canvas AND in the
    // shipped app. A component cannot depend on that for the one thing it does.
    const { container } = render(
      <FocusRing color="#ff0000" width={4} offset={3}>
        <button>focus me</button>
      </FocusRing>,
    );
    const wrapper = container.querySelector<HTMLElement>("[data-forge-focus-ring]")!;
    expect(wrapper.style.getPropertyValue("--focus-ring-color")).toBe("#ff0000");
    expect(wrapper.style.getPropertyValue("--focus-ring-width")).toBe("4px");
    const style = wrapper.querySelector("style");
    expect(style).not.toBeNull();
    expect(style!.innerHTML).toContain("outline");
    // Scoped to its own attribute, so it cannot leak onto the rest of the page.
    expect(style!.innerHTML).toContain("[data-forge-focus-ring]");
    expect(style!.innerHTML).toContain("--focus-ring-color");
  });

  it("stays layout-neutral", () => {
    const { container } = render(<FocusRing><button>x</button></FocusRing>);
    expect(container.querySelector<HTMLElement>("[data-forge-focus-ring]")!.style.display)
      .toBe("contents");
  });
});

describe("the floating surfaces can be placed", () => {
  it("Tooltip takes a side", () => {
    // Declared by TooltipProps AND TooltipNode, passed to RTooltip.Content, and
    // reachable from nothing — every authored Tooltip was pinned to "top".
    const { container } = render(<Tooltip label="t" content="c" side="right" />);
    expect(container.querySelector("[data-tooltip]")).not.toBeNull();
  });

  it("HoverCard has hover intent instead of popping instantly", async () => {
    // openDelay/closeDelay were hardwired to 0 in the component and existed in
    // no layer, so a rich preview card fired on the slightest mouse-over.
    const { container } = render(<HoverCard label="t" content="c" openDelay={700} />);
    const trigger = container.querySelector("[data-hover-card]")!;
    fireEvent.pointerEnter(trigger);
    // Nothing has opened yet — the whole point of the intent window.
    expect(screen.queryByText("c")).toBeNull();
  });
});

describe("CartPanel's checkout footer is previewable", () => {
  it("stays hidden on an empty cart in a running app", async () => {
    const { container } = render(
      <CartPanel title="Cart" checkoutLabel="Buy now" />,
    );
    await screen.findByText("Your cart is empty.");
    // The footer belongs to a cart with something in it.
    expect(screen.queryByText("Buy now")).toBeNull();
    expect(container.querySelector("select")).toBeNull();
  });

  it("shows on an authoring surface, so its three props stop being invisible", async () => {
    // `checkoutLabel`, `paymentMethods` and `onCheckoutNavigate` all live in the
    // non-empty branch, and the editor cannot produce a non-empty cart — rename
    // the button to "Buy now" and nothing anywhere changed. The button is
    // already disabled on an empty cart, so showing the footer invents nothing.
    render(
      <DesignTimeProvider>
        <CartPanel title="Cart" checkoutLabel="Buy now" paymentMethods={["invoice"]} />
      </DesignTimeProvider>,
    );
    const btn = await screen.findByText("Buy now");
    expect(btn).toBeDisabled();
    expect(await screen.findByText("invoice")).toBeInTheDocument();
    // The honest empty state is still there next to it.
    expect(screen.getByText("Your cart is empty.")).toBeInTheDocument();
  });
});
