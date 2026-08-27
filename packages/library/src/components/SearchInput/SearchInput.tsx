"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { SearchInputPropsType } from "./SearchInput.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import {
  setSearchState,
  resetSearchState,
  type SearchHit,
} from "./searchStore";

export interface SearchInputProps extends SearchInputPropsType {
  style?: StyleSlotT;
  /** Optional callback receiving results in addition to updating the store.
   *  Handy for tests / one-off panels that don't want to consume the store. */
  onResults?: (hits: SearchHit[]) => void;
}

/**
 * SearchInput — debounced text input that hits an op:"search" endpoint and
 * publishes results into the shared searchStore. Renders a magnifying-glass
 * icon on the left; a clear-X on the right when the field carries text.
 *
 * SEARCH-3 slice. The paired SearchResults component reads out of the store
 * so a header search + a body results panel can live in different subtrees.
 */
export function SearchInput({
  placeholder = "Search…",
  endpoint,
  debounceMs = 300,
  minChars = 2,
  style,
  onResults,
}: SearchInputProps): React.ReactElement {
  const [value, setValue] = React.useState<string>("");
  const timerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = React.useRef<AbortController | null>(null);
  const motion = useMotion(style?.motion);
  const styleProps = resolveStyle(style);

  const fetchResults = React.useCallback(async (q: string): Promise<void> => {
    // Cancel any in-flight request — only the newest query wins.
    if (abortRef.current) abortRef.current.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    setSearchState({ query: q, loading: true, error: null });
    try {
      const url = endpoint + (endpoint.includes("?") ? "&" : "?") + "q=" + encodeURIComponent(q);
      const res = await fetch(url, { signal: ctrl.signal });
      if (!res.ok) throw new Error("Search failed (" + res.status + ")");
      const hits: SearchHit[] = await res.json();
      setSearchState({ loading: false, results: Array.isArray(hits) ? hits : [], error: null });
      onResults?.(Array.isArray(hits) ? hits : []);
    } catch (e) {
      // Aborted requests are the newest-wins signal — not a user-facing error.
      if ((e as Error)?.name === "AbortError") return;
      setSearchState({ loading: false, results: [], error: (e as Error)?.message || "Search failed" });
    }
  }, [endpoint, onResults]);

  const onChange = React.useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const q = e.target.value;
    setValue(q);
    if (timerRef.current !== null) clearTimeout(timerRef.current);
    const trimmed = q.trim();
    if (trimmed.length < minChars) {
      // Sub-threshold — flush any pending search + clear the store so the
      // results panel returns to its initial empty state.
      if (abortRef.current) abortRef.current.abort();
      resetSearchState();
      return;
    }
    timerRef.current = setTimeout(() => {
      void fetchResults(trimmed);
    }, debounceMs);
  }, [debounceMs, fetchResults, minChars]);

  const onClear = React.useCallback(() => {
    setValue("");
    if (timerRef.current !== null) clearTimeout(timerRef.current);
    if (abortRef.current) abortRef.current.abort();
    resetSearchState();
  }, []);

  // Cleanup on unmount — cancel timers + in-flight fetches so unmounting mid-
  // search doesn't setState on a dead tree.
  React.useEffect(() => {
    return () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current);
      if (abortRef.current) abortRef.current.abort();
    };
  }, []);

  return (
    <div
      data-search-input=""
      data-testid="search-input"
      {...motion}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        padding: "6px 10px",
        border: "1px solid var(--border, hsl(0 0% 90%))",
        borderRadius: "var(--radius-md, 0.375rem)",
        background: "var(--background, white)",
        minWidth: 240,
        ...styleProps,
      }}
    >
      {/* Magnifying-glass icon on the left (Lucide `Search` shape). */}
      <svg
        width="14" height="14" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="2" strokeLinecap="round"
        strokeLinejoin="round" aria-hidden="true"
        style={{ color: "var(--muted-foreground, hsl(0 0% 45%))", flexShrink: 0 }}
      >
        <circle cx="11" cy="11" r="8" />
        <line x1="21" y1="21" x2="16.65" y2="16.65" />
      </svg>
      <input
        type="search"
        role="searchbox"
        placeholder={placeholder}
        value={value}
        onChange={onChange}
        aria-label="Search"
        style={{
          border: "none",
          outline: "none",
          background: "transparent",
          flex: 1,
          fontSize: "0.875rem",
          color: "var(--foreground, hsl(0 0% 15%))",
          minWidth: 0,
        }}
      />
      {value.length > 0 && (
        <button
          type="button"
          aria-label="Clear search"
          onClick={onClear}
          style={{
            border: "none",
            background: "transparent",
            padding: 2,
            cursor: "pointer",
            color: "var(--muted-foreground, hsl(0 0% 45%))",
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <svg
            width="12" height="12" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2" strokeLinecap="round"
            strokeLinejoin="round" aria-hidden="true"
          >
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      )}
    </div>
  );
}
