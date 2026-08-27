import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Explorer } from "../../src/panes/Explorer/Explorer";
import { createEditorStore } from "../../src/state/store";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Explorer", () => {
  it("lists pages from /api/editor/pages and groups by folder", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      paths: ["products/list", "products/detail", "customers/list"],
    }), { status: 200 })));

    const store = createEditorStore();
    render(<Explorer store={store} apiBaseUrl="" onOpenPage={() => {}} />);

    await waitFor(() => expect(screen.getByText("products")).toBeInTheDocument());
    expect(screen.getByText("customers")).toBeInTheDocument();
    // "list" appears twice (products/list and customers/list)
    expect(screen.getAllByText("list").length).toBeGreaterThanOrEqual(1);
  });

  it("clicking a page calls onOpenPage with the path", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      paths: ["products/list"],
    }), { status: 200 })));

    const store = createEditorStore();
    const onOpen = vi.fn();
    render(<Explorer store={store} apiBaseUrl="" onOpenPage={onOpen} />);
    await waitFor(() => screen.getByText("list"));
    await userEvent.click(screen.getByText("list"));
    expect(onOpen).toHaveBeenCalledWith("products/list");
  });

  it("highlights already-open pages", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      paths: ["products/list"],
    }), { status: 200 })));

    const store = createEditorStore();
    const page = (): any => ({ schemaVersion: "1", id: "p", route: "/", root: { id: "r", type: "Text", props: { content: "x" } } });
    store.getState().openPage("products/list", page());

    render(<Explorer store={store} apiBaseUrl="" onOpenPage={() => {}} />);
    await waitFor(() => screen.getByText("list"));
    const btn = screen.getByText("list").closest("[data-open='true']");
    expect(btn).toBeTruthy();
  });

  it("shows a Layouts section for _layouts/* paths", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      paths: ["products/list", "_layouts/DashboardLayout", "_layouts/AuthLayout"],
    }), { status: 200 })));

    const store = createEditorStore();
    render(<Explorer store={store} apiBaseUrl="" onOpenPage={() => {}} />);

    await waitFor(() => expect(screen.getByText("DashboardLayout")).toBeInTheDocument());
    expect(screen.getByText("AuthLayout")).toBeInTheDocument();
    // "Layouts" heading is rendered
    expect(screen.getByText(/layouts/i)).toBeInTheDocument();
    // layout paths do NOT appear under the Pages section as raw paths
    expect(screen.queryByText("_layouts")).toBeNull();
  });

  it("clicking a layout calls onOpenPage with the _layouts/ prefixed path", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      paths: ["_layouts/DashboardLayout"],
    }), { status: 200 })));

    const store = createEditorStore();
    const onOpen = vi.fn();
    render(<Explorer store={store} apiBaseUrl="" onOpenPage={onOpen} />);
    await waitFor(() => screen.getByText("DashboardLayout"));
    await userEvent.click(screen.getByText("DashboardLayout"));
    expect(onOpen).toHaveBeenCalledWith("_layouts/DashboardLayout");
  });
});
