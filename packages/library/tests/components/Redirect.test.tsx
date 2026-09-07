import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { NavigatorProvider } from "@tentoroforge/renderer";
import { Redirect, isSelfRoute } from "../../src/components/Redirect/Redirect";

function mountAt(path: string, ui: React.ReactElement) {
  window.history.replaceState({}, "", path);
  const nav = { push: vi.fn(), replace: vi.fn(), back: vi.fn(), refresh: vi.fn() };
  const utils = render(<NavigatorProvider value={nav}>{ui}</NavigatorProvider>);
  return { nav, ...utils };
}

beforeEach(() => {
  window.history.replaceState({}, "", "/nav-lab-6");
});

describe("isSelfRoute", () => {
  it("matches the same path however it is spelled", () => {
    expect(isSelfRoute("/items", "/items")).toBe(true);
    expect(isSelfRoute("/items/", "/items")).toBe(true);
    expect(isSelfRoute("/items?q=1", "/items")).toBe(true);
  });
  it("matches through a preview base path", () => {
    expect(isSelfRoute("/nav-lab-6", "/p/gh0mlpbp/nav-lab-6")).toBe(true);
  });
  it("does not match a different route, or a partial segment", () => {
    expect(isSelfRoute("/items", "/other")).toBe(false);
    expect(isSelfRoute("/items", "/line-items")).toBe(false);
    expect(isSelfRoute("/", "/p/gh0mlpbp/items")).toBe(false);
  });
  it("is inert without a current path (SSR)", () => {
    expect(isSelfRoute("/items", undefined)).toBe(false);
  });
});

describe("Redirect", () => {
  it("navigates to a real destination", async () => {
    const { nav } = mountAt("/nav-lab-6", <Redirect to="/items" />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/items"));
    expect(screen.getByRole("status")).toHaveTextContent("Redirecting…");
  });

  it("with no destination it says so and never navigates", async () => {
    const { nav } = mountAt("/nav-lab-6", <Redirect to="" />);
    expect(await screen.findByText("Redirect — no destination set.")).toBeInTheDocument();
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("refuses a self-referential redirect instead of soft-locking on “Redirecting…”", async () => {
    const { nav } = mountAt("/nav-lab-6", <Redirect to="/nav-lab-6" />);
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("Redirect skipped"),
    );
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("refuses a self-redirect under a preview base path too", async () => {
    const { nav } = mountAt("/p/gh0mlpbp/nav-lab-6", <Redirect to="/nav-lab-6" />);
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("Redirect skipped"),
    );
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("shows the author's label while a real redirect fires", async () => {
    const { nav } = mountAt("/nav-lab-6", <Redirect to="/items" label="Taking you to Items…" />);
    await waitFor(() => expect(nav.replace).toHaveBeenCalled());
    expect(screen.getByRole("status")).toHaveTextContent("Taking you to Items…");
  });
});
