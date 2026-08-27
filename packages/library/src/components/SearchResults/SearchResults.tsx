"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { SearchResultsPropsType } from "./SearchResults.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import {
  getSearchState,
  subscribeSearch,
  type SearchHit,
} from "../SearchInput/searchStore";

export interface SearchResultsProps extends SearchResultsPropsType {
  style?: StyleSlotT;
  /** Optional test-mode override — bypasses the store so unit tests can pass
   *  hits directly. Ignored in production usage; the store is the SoT. */
  results?: SearchHit[];
  loading?: boolean;
  query?: string;
}

/**
 * SearchResults — ranked hit list backed by the shared searchStore.
 *
 * Renders one of four states:
 *   - PRISTINE    (query empty)          → pristineText
 *   - LOADING     (query set, fetching)  → skeleton rows
 *   - NO_MATCHES  (results empty)        → emptyText
 *   - LIST        (results present)      → ranked rows with snippet
 *
 * Snippet is rendered via dangerouslySetInnerHTML — ts_headline emits
 * `<b>…</b>` markup and HTML-escapes everything else in the source text,
 * so the injected HTML is safe. Never render arbitrary HTML from any
 * other field.
 */
export function SearchResults({
  hrefPattern = "/${entity}/${id}",
  skeletonRows = 5,
  pristineText = "Search across your data.",
  emptyText = "No matches found. Try different keywords or check spelling.",
  style,
  results: resultsOverride,
  loading: loadingOverride,
  query: queryOverride,
}: SearchResultsProps): React.ReactElement {
  // useSyncExternalStore — React-18 concurrent-safe subscription. The
  // getSnapshot is the whole state object; identity changes only when
  // setSearchState fires, so listeners re-render exactly on updates.
  const state = React.useSyncExternalStore(
    subscribeSearch,
    getSearchState,
    getSearchState,
  );
  const results = resultsOverride ?? state.results;
  const loading = loadingOverride ?? state.loading;
  const query = queryOverride ?? state.query;
  const motion = useMotion(style?.motion);
  const styleProps = resolveStyle(style);

  const buildHref = React.useCallback((hit: SearchHit): string => {
    if (!hrefPattern) return "";
    return hrefPattern
      .replaceAll("${entity}", String(hit.entity ?? ""))
      .replaceAll("${id}", String(hit.id ?? ""));
  }, [hrefPattern]);

  const wrapperStyle: React.CSSProperties = {
    display: "flex",
    flexDirection: "column",
    gap: 8,
    ...styleProps,
  };

  // ── PRISTINE ────────────────────────────────────────────────────────
  if (!query && !loading && results.length === 0) {
    return (
      <div
        data-search-results=""
        data-testid="search-results"
        data-state="pristine"
        {...motion}
        style={wrapperStyle}
      >
        <p style={{
          color: "var(--muted-foreground, hsl(0 0% 45%))",
          fontSize: "0.875rem",
          margin: 0,
          padding: "12px 8px",
        }}>
          {pristineText}
        </p>
      </div>
    );
  }

  // ── LOADING (skeleton rows) ─────────────────────────────────────────
  if (loading) {
    return (
      <div
        data-search-results=""
        data-testid="search-results"
        data-state="loading"
        {...motion}
        style={wrapperStyle}
      >
        {Array.from({ length: skeletonRows }, (_, i) => (
          <div
            key={i}
            data-testid="search-results-skeleton"
            style={{
              padding: "10px 12px",
              border: "1px solid var(--border, hsl(0 0% 90%))",
              borderRadius: "var(--radius-md, 0.375rem)",
              background: "var(--muted, hsl(0 0% 96%))",
              height: 44,
              opacity: 0.6,
            }}
          />
        ))}
      </div>
    );
  }

  // ── NO_MATCHES ──────────────────────────────────────────────────────
  if (results.length === 0) {
    return (
      <div
        data-search-results=""
        data-testid="search-results"
        data-state="empty"
        {...motion}
        style={wrapperStyle}
      >
        <p style={{
          color: "var(--muted-foreground, hsl(0 0% 45%))",
          fontSize: "0.875rem",
          margin: 0,
          padding: "12px 8px",
        }}>
          {emptyText}
        </p>
      </div>
    );
  }

  // ── LIST ────────────────────────────────────────────────────────────
  return (
    <ul
      data-search-results=""
      data-testid="search-results"
      data-state="list"
      role="list"
      {...motion}
      style={{
        ...wrapperStyle,
        listStyle: "none",
        margin: 0,
        padding: 0,
      }}
    >
      {results.map((hit, i) => {
        // Primary display value — every non-{id,entity,snippet,rank} key is a
        // candidate; take the first string-valued one (the resolver always
        // includes exactly one primary field per entity).
        const primaryValue = _pickPrimary(hit);
        const href = buildHref(hit);
        const Row: any = href ? "a" : "div";
        return (
          <li key={`${hit.entity}:${String(hit.id)}:${i}`}>
            <Row
              {...(href ? { href } : {})}
              data-testid="search-result-row"
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 4,
                padding: "10px 12px",
                border: "1px solid var(--border, hsl(0 0% 90%))",
                borderRadius: "var(--radius-md, 0.375rem)",
                background: "var(--background, white)",
                color: "var(--foreground, hsl(0 0% 15%))",
                textDecoration: "none",
                cursor: href ? "pointer" : "default",
              }}
            >
              <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <span style={{ fontWeight: 600, fontSize: "0.875rem", flex: 1, minWidth: 0 }}>
                  {primaryValue || "(untitled)"}
                </span>
                <span
                  data-testid="search-result-entity-badge"
                  style={{
                    fontSize: "0.688rem",
                    padding: "2px 6px",
                    borderRadius: 3,
                    background: "var(--muted, hsl(0 0% 96%))",
                    color: "var(--muted-foreground, hsl(0 0% 45%))",
                    textTransform: "capitalize",
                    flexShrink: 0,
                  }}
                >
                  {hit.entity}
                </span>
              </div>
              {hit.snippet ? (
                <div
                  data-testid="search-result-snippet"
                  style={{
                    fontSize: "0.813rem",
                    color: "var(--muted-foreground, hsl(0 0% 45%))",
                    lineHeight: 1.4,
                  }}
                  // ts_headline emits <b>...</b> markup around matches and
                  // HTML-escapes everything else — safe to inject.
                  dangerouslySetInnerHTML={{ __html: hit.snippet }}
                />
              ) : null}
            </Row>
          </li>
        );
      })}
    </ul>
  );
}

const _RESERVED = new Set(["id", "entity", "snippet", "rank"]);

function _pickPrimary(hit: SearchHit): string {
  for (const [k, v] of Object.entries(hit)) {
    if (_RESERVED.has(k)) continue;
    if (typeof v === "string" && v.length > 0) return v;
    if (typeof v === "number") return String(v);
  }
  return "";
}
