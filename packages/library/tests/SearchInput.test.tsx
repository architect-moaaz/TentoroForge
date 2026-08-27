import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, act } from "@testing-library/react";
import { SearchInput } from "../src/components/SearchInput/SearchInput";
import {
  getSearchState,
  resetSearchState,
} from "../src/components/SearchInput/searchStore";

// Shared fetch mock — each test resets the impl.
const fetchMock = vi.fn();

beforeEach(() => {
  resetSearchState();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

// Helper — advance the fake-timer clock AND drain pending microtasks so the
// promise chain the SearchInput kicks off inside setTimeout can settle. Plain
// vi.advanceTimersByTime doesn't drain microtasks; runAllTimersAsync does.
async function tickAndSettle(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("SearchInput — debounced fetch + store publish", () => {
  it("renders a searchbox with the given placeholder + a search icon", () => {
    const { getByRole } = render(
      <SearchInput endpoint="/api/search" placeholder="Find files…" />,
    );
    const input = getByRole("searchbox") as HTMLInputElement;
    expect(input.placeholder).toBe("Find files…");
  });

  it("does NOT fire the endpoint below minChars, and clears the store on sub-threshold input", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => [] });
    const { getByRole } = render(
      <SearchInput endpoint="/api/search" minChars={3} debounceMs={100} />,
    );
    const input = getByRole("searchbox") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "ab" } });
    await tickAndSettle(200);
    expect(fetchMock).not.toHaveBeenCalled();
    // Store reset — pristine state.
    expect(getSearchState().query).toBe("");
    expect(getSearchState().loading).toBe(false);
  });

  it("debounces — one keystroke burst yields ONE fetch after the settle window", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => [] });
    const { getByRole } = render(
      <SearchInput endpoint="/api/search" minChars={1} debounceMs={200} />,
    );
    const input = getByRole("searchbox") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "d" } });
    fireEvent.change(input, { target: { value: "do" } });
    fireEvent.change(input, { target: { value: "doc" } });
    // Well before the settle window: no fetch yet.
    await tickAndSettle(100);
    expect(fetchMock).not.toHaveBeenCalled();
    // Past the settle window: exactly one fetch, with the LATEST query.
    await tickAndSettle(200);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("q=doc");
  });

  it("publishes results to the shared store", async () => {
    const hits = [
      { id: "1", entity: "documents", snippet: "hi", rank: 0.5, title: "Doc" },
    ];
    fetchMock.mockResolvedValue({ ok: true, json: async () => hits });
    const { getByRole } = render(
      <SearchInput endpoint="/api/search" minChars={1} debounceMs={50} />,
    );
    fireEvent.change(getByRole("searchbox"), { target: { value: "hello" } });
    await tickAndSettle(100);
    expect(getSearchState().results.length).toBe(1);
    expect(getSearchState().query).toBe("hello");
    expect(getSearchState().loading).toBe(false);
    expect(getSearchState().error).toBeNull();
    expect(getSearchState().results[0].entity).toBe("documents");
  });

  it("shows a clear-X once the field carries text, and clearing empties the store", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => [] });
    const { getByRole, queryByLabelText, getByLabelText } = render(
      <SearchInput endpoint="/api/search" minChars={1} debounceMs={10} />,
    );
    // No clear button on a pristine field.
    expect(queryByLabelText("Clear search")).toBeNull();

    fireEvent.change(getByRole("searchbox"), { target: { value: "hello" } });
    await tickAndSettle(50);
    // Clear button appears.
    const clearBtn = getByLabelText("Clear search");
    fireEvent.click(clearBtn);
    expect((getByRole("searchbox") as HTMLInputElement).value).toBe("");
    expect(getSearchState().query).toBe("");
    expect(getSearchState().results).toEqual([]);
  });

  it("records an error on failed response", async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 500, json: async () => ({}) });
    const { getByRole } = render(
      <SearchInput endpoint="/api/search" minChars={1} debounceMs={10} />,
    );
    fireEvent.change(getByRole("searchbox"), { target: { value: "boom" } });
    await tickAndSettle(50);
    expect(getSearchState().error).toBeTruthy();
    expect(getSearchState().loading).toBe(false);
  });

  it("appends q= to an endpoint already carrying a query string", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => [] });
    const { getByRole } = render(
      <SearchInput endpoint="/api/search?scope=all" minChars={1} debounceMs={10} />,
    );
    fireEvent.change(getByRole("searchbox"), { target: { value: "x" } });
    await tickAndSettle(50);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("scope=all&q=x");
  });
});
