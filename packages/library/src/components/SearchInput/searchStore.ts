// SEARCH-3 shared search store.
//
// A tiny module-level pub/sub the SearchInput writes into and the
// SearchResults reads out of. Deliberately hand-rolled — the library has
// no zustand/redux dep and this needs to stay that way. Wrapped with
// useSyncExternalStore for React 18 concurrent-safe reads.
//
// One store per app. Multiple SearchInputs on one page share results by
// design (a search bar in a header + a results panel in the body is the
// common pattern); apps that want isolated searches nest a scope prop
// (future). Kept simple until it needs to be complex.

export interface SearchHit {
  id: unknown;
  entity: string;
  snippet: string;
  rank: number;
  [key: string]: unknown;
}

export interface SearchState {
  /** Last settled query string (post-debounce). Empty = no active search. */
  query: string;
  /** True while a fetch is in flight. */
  loading: boolean;
  /** Latest results from the endpoint. */
  results: SearchHit[];
  /** Non-null when the last fetch failed — the results panel renders it. */
  error: string | null;
}

const _initial: SearchState = {
  query: "",
  loading: false,
  results: [],
  error: null,
};

let _state: SearchState = _initial;
const _listeners = new Set<() => void>();

export function getSearchState(): SearchState {
  return _state;
}

export function setSearchState(patch: Partial<SearchState>): void {
  _state = { ..._state, ...patch };
  for (const l of _listeners) l();
}

export function resetSearchState(): void {
  _state = _initial;
  for (const l of _listeners) l();
}

export function subscribeSearch(fn: () => void): () => void {
  _listeners.add(fn);
  return () => {
    _listeners.delete(fn);
  };
}
