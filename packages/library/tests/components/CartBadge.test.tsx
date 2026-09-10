import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { CartBadge } from "../../src/components/CartBadge/CartBadge";

/**
 * The audit finding this pins: a dropped CartBadge had `childElementCount === 0`
 * and a 0x0 rect — nothing to see, click, select or diagnose — because the
 * component returned null whenever the count was not a number, which is every
 * environment without a live `/api/cart` (the editor canvas above all).
 */

const okCart = (count: number) =>
  vi.fn().mockResolvedValue({ ok: true, json: async () => ({ count }) });

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("no api")));
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CartBadge", () => {
  it("renders a visible badge when /api/cart is unreachable", async () => {
    render(<CartBadge />);
    const link = await screen.findByRole("link");
    expect(link).toHaveAttribute("data-cart-badge");
    expect(link).toHaveTextContent("Cart");
    // The count pill is present and reads 0, marked as not-yet-known.
    expect(link).toHaveAttribute("data-cart-count-known", "false");
    expect(screen.getByLabelText("Cart count unavailable")).toHaveTextContent("0");
  });

  it("stays visible with hideZero when the count is merely unknown", async () => {
    render(<CartBadge hideZero />);
    expect(await screen.findByRole("link")).toBeInTheDocument();
  });

  it("shows the fetched count once /api/cart answers", async () => {
    vi.stubGlobal("fetch", okCart(3));
    render(<CartBadge />);
    await waitFor(() =>
      expect(screen.getByRole("link")).toHaveAttribute("data-cart-count-known", "true"),
    );
    expect(screen.getByLabelText("3 items")).toHaveTextContent("3");
  });

  it("still honours hideZero for a real, fetched zero", async () => {
    vi.stubGlobal("fetch", okCart(0));
    const { container } = render(<CartBadge hideZero />);
    await waitFor(() => expect(container.querySelector("[data-cart-badge]")).toBeNull());
  });

  it("links to href and labels itself", async () => {
    render(<CartBadge href="/basket" label="Basket" />);
    const link = await screen.findByRole("link");
    expect(link).toHaveAttribute("href", "/basket");
    expect(link).toHaveTextContent("Basket");
  });
});
