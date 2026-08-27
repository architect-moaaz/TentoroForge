import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Switcher } from "../../src/panes/Switcher/Switcher";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Switcher", () => {
  it("filters paths by substring", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      paths: ["products/list", "products/detail", "customers/list"],
    }), { status: 200 })));

    const onOpen = vi.fn();
    render(<Switcher open={true} onClose={() => {}} onOpenPage={onOpen} apiBaseUrl="" />);
    await waitFor(() => screen.getByPlaceholderText(/jump to page/i));
    const input = screen.getByPlaceholderText(/jump to page/i);
    await userEvent.type(input, "cust");
    expect(screen.getByText("customers/list")).toBeInTheDocument();
    expect(screen.queryByText("products/list")).not.toBeInTheDocument();
  });

  it("Enter opens the first match", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      paths: ["products/list"],
    }), { status: 200 })));
    const onOpen = vi.fn();
    render(<Switcher open={true} onClose={() => {}} onOpenPage={onOpen} apiBaseUrl="" />);
    await waitFor(() => screen.getByPlaceholderText(/jump to page/i));
    await userEvent.keyboard("{Enter}");
    expect(onOpen).toHaveBeenCalledWith("products/list");
  });

  it("Escape calls onClose", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      paths: ["products/list"],
    }), { status: 200 })));
    const onClose = vi.fn();
    render(<Switcher open={true} onClose={onClose} onOpenPage={() => {}} apiBaseUrl="" />);
    await waitFor(() => screen.getByPlaceholderText(/jump to page/i));
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });

  it("renders nothing when open=false", () => {
    render(<Switcher open={false} onClose={() => {}} onOpenPage={() => {}} apiBaseUrl="" />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
