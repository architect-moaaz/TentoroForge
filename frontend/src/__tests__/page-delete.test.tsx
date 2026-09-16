/**
 * ED-14 — "Delete a page from the editor" (Fail, P2,
 * DEFECT-EDITOR-NO-DELETE-PAGE).
 *
 * The tester's report was precise: no per-row button, no hover trash, no
 * context menu, and Delete/Backspace does nothing on a selected page. What the
 * report could not see is that `removePage` was already implemented, tested and
 * undoable in the reducer — it simply had no caller anywhere in the frontend.
 *
 * So these tests drive the CONTROL, not the reducer: find the trash in the
 * Pages panel, confirm, and assert the page actually left the artifacts. A test
 * that called `dispatch({type:"removePage"})` directly would have passed before
 * the fix and proved nothing.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PagePicker } from "@/components/editor/PagePicker";
import { useEditorStore } from "@/lib/editor-store";

vi.mock("next/navigation", () => ({ useParams: () => ({ projectId: "p1" }) }));

const NAV = {
  initialPage: "home",
  pages: [
    { id: "home", route: "/", title: "Home", schemaFile: "src/schemas/home.json", params: [] },
    { id: "about", route: "/about", title: "About", schemaFile: "src/schemas/about.json", params: [] },
  ],
  transitions: [{ id: "t1", from: "home", to: "about" }],
};

const page = (id: string, route: string) => ({
  schemaVersion: "2", id, route,
  root: { id: `${id}_root`, type: "Stack", children: [] },
});

function artifacts() {
  return {
    pageSchemas: { home: page("home", "/"), about: page("about", "/about") },
    navFlow: JSON.parse(JSON.stringify(NAV)),
    tokens: {},
  };
}

/** The panel reads nav-flow through react-query; shell.json lookups 404. */
function stubFetch(nav: unknown) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (String(url).includes("nav-flow.json")) {
      return { ok: true, json: async () => nav } as unknown as Response;
    }
    return { ok: false, status: 404, json: async () => ({}) } as unknown as Response;
  }));
}

function renderPicker(onChange = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const utils = render(
    <QueryClientProvider client={qc}>
      <PagePicker projectId="p1" value="home" onChange={onChange} />
    </QueryClientProvider>,
  );
  return { ...utils, onChange };
}

const nav = () => (useEditorStore.getState().artifacts as any).navFlow;
const schemas = () => (useEditorStore.getState().artifacts as any).pageSchemas;

beforeEach(() => {
  stubFetch(NAV);
  useEditorStore.setState({ artifacts: artifacts() as never, currentPageId: "home" });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  useEditorStore.setState({ artifacts: null, currentPageId: null });
});

describe("ED-14 — the Pages panel exposes a delete control", () => {
  it("renders a delete button on every page row", async () => {
    renderPicker();
    await screen.findByLabelText("Delete page /about");
    expect(screen.getByLabelText("Delete page /")).toBeTruthy();
  });

  it("asks before deleting — one click does not destroy anything", async () => {
    renderPicker();
    fireEvent.click(await screen.findByLabelText("Delete page /about"));
    // still there: the click opened a question, it did not act
    expect(schemas().about).toBeDefined();
    expect(screen.getByText(/delete this page\?/i)).toBeTruthy();
  });

  it("cancelling leaves the page alone", async () => {
    renderPicker();
    fireEvent.click(await screen.findByLabelText("Delete page /about"));
    fireEvent.click(screen.getByText("Cancel"));
    expect(schemas().about).toBeDefined();
    expect(nav().pages).toHaveLength(2);
  });

  it("confirming removes the page, its nav entry and its transitions", async () => {
    renderPicker();
    fireEvent.click(await screen.findByLabelText("Delete page /about"));
    fireEvent.click(screen.getByText("Delete page"));

    await waitFor(() => expect(schemas().about).toBeUndefined());
    expect(nav().pages.map((p: any) => p.id)).toEqual(["home"]);
    expect(nav().transitions).toEqual([]);
  });

  it("deleting the page you are looking at moves you to another one", async () => {
    const onChange = vi.fn();
    renderPicker(onChange);
    fireEvent.click(await screen.findByLabelText("Delete page /"));
    fireEvent.click(screen.getByText("Delete page"));

    await waitFor(() => expect(onChange).toHaveBeenCalledWith("about"));
  });

  it("deleting the entry page hands the entry to the survivor", async () => {
    renderPicker();
    fireEvent.click(await screen.findByLabelText("Delete page /"));
    fireEvent.click(screen.getByText("Delete page"));

    await waitFor(() => expect(nav().initialPage).toBe("about"));
  });

  it("warns that the entry page is about to move, and only then", async () => {
    renderPicker();
    fireEvent.click(await screen.findByLabelText("Delete page /"));
    expect(screen.getByText(/entry page moves/i)).toBeTruthy();
    fireEvent.click(screen.getByText("Cancel"));

    fireEvent.click(screen.getByLabelText("Delete page /about"));
    expect(screen.queryByText(/entry page moves/i)).toBeNull();
  });

  it("the last remaining page has no delete control", async () => {
    const solo = {
      initialPage: "home",
      pages: [NAV.pages[0]],
      transitions: [],
    };
    stubFetch(solo);
    useEditorStore.setState({
      artifacts: { pageSchemas: { home: page("home", "/") }, navFlow: solo, tokens: {} } as never,
    });
    renderPicker();
    await screen.findByText("/");
    expect(screen.queryByLabelText("Delete page /")).toBeNull();
  });

  it("undo brings the page back, with its entry status", async () => {
    renderPicker();
    fireEvent.click(await screen.findByLabelText("Delete page /"));
    fireEvent.click(screen.getByText("Delete page"));
    await waitFor(() => expect(schemas().home).toBeUndefined());

    useEditorStore.getState().undo();
    expect(schemas().home).toBeDefined();
    expect(nav().initialPage).toBe("home");
  });
});
