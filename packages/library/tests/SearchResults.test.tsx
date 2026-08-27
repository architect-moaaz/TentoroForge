import { describe, it, expect, beforeEach } from "vitest";
import { render, act } from "@testing-library/react";
import { SearchResults } from "../src/components/SearchResults/SearchResults";
import {
  resetSearchState,
  setSearchState,
} from "../src/components/SearchInput/searchStore";

beforeEach(() => {
  resetSearchState();
});

describe("SearchResults — states from the shared store", () => {
  it("renders the PRISTINE state when there is no query and no results", () => {
    const { getByTestId } = render(
      <SearchResults pristineText="Search across your data." />,
    );
    const el = getByTestId("search-results");
    expect(el.getAttribute("data-state")).toBe("pristine");
    expect(el.textContent).toContain("Search across your data.");
  });

  it("renders skeleton rows while LOADING", () => {
    act(() => {
      setSearchState({ query: "d", loading: true, results: [], error: null });
    });
    const { getByTestId, queryAllByTestId } = render(
      <SearchResults skeletonRows={4} />,
    );
    expect(getByTestId("search-results").getAttribute("data-state")).toBe("loading");
    expect(queryAllByTestId("search-results-skeleton").length).toBe(4);
  });

  it("renders the NO_MATCHES state distinctly from pristine", () => {
    act(() => {
      // A settled query with an empty result set — NOT the pristine state.
      setSearchState({ query: "does-not-exist", loading: false, results: [], error: null });
    });
    const { getByTestId } = render(
      <SearchResults emptyText="No matches found." pristineText="Search across your data." />,
    );
    const el = getByTestId("search-results");
    expect(el.getAttribute("data-state")).toBe("empty");
    expect(el.textContent).toContain("No matches found.");
    expect(el.textContent).not.toContain("Search across your data.");
  });

  it("renders the LIST state — primary field + entity badge + snippet", () => {
    act(() => {
      setSearchState({
        query: "invoice",
        loading: false,
        error: null,
        results: [
          { id: "1", entity: "documents", snippet: "…the <b>invoice</b> pdf…", rank: 0.9, title: "Invoice 42" },
          { id: "2", entity: "extractions", snippet: "vendor <b>invoice</b> total", rank: 0.7, field_name: "vendor" },
        ],
      });
    });
    const { getByTestId, getAllByTestId } = render(<SearchResults />);
    expect(getByTestId("search-results").getAttribute("data-state")).toBe("list");
    const rows = getAllByTestId("search-result-row");
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain("Invoice 42");
    const badges = getAllByTestId("search-result-entity-badge");
    expect(badges[0].textContent).toBe("documents");
    expect(badges[1].textContent).toBe("extractions");
    // Snippet HTML from ts_headline is injected via dangerouslySetInnerHTML.
    const snippets = getAllByTestId("search-result-snippet");
    expect(snippets[0].innerHTML).toContain("<b>invoice</b>");
  });

  it("substitutes ${entity} / ${id} in the hrefPattern", () => {
    act(() => {
      setSearchState({
        query: "x",
        loading: false,
        error: null,
        results: [{ id: "42", entity: "documents", snippet: "", rank: 1, title: "Doc" }],
      });
    });
    const { getAllByTestId } = render(
      <SearchResults hrefPattern="/app/${entity}/${id}" />,
    );
    const row = getAllByTestId("search-result-row")[0] as HTMLAnchorElement;
    expect(row.getAttribute("href")).toBe("/app/documents/42");
  });

  it("accepts test-mode override props (bypassing the store)", () => {
    const { getByTestId } = render(
      <SearchResults
        loading={true}
        query="anything"
        results={[]}
        skeletonRows={2}
      />,
    );
    expect(getByTestId("search-results").getAttribute("data-state")).toBe("loading");
  });
});
