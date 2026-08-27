// Default per-field data fetcher for the reactive Form controller (spec item 5,
// S1c — dependent dropdowns + onChange populate). Mirrors the page-level
// `fetchDataSources` loader's contract (`GET /api/data/<resource>?<filter>` +
// unwrap the `{ data, total, page, limit }` pagination envelope) so dependent
// selects and onChange side-effects read the SAME Data Engine endpoint the rest
// of the app does — no new fetch layer is introduced. It is injectable so tests
// (and the editor preview) can swap in a mock; the real default is used in
// generated apps. Safe no-op during SSR; never throws.

/**
 * Fetch rows from a data resource, optionally filtered. Returns a bare array of
 * records (envelope unwrapped). Injected into `Form`/`DeclarativeForm` via the
 * `__fetchData` prop; defaults to `fallbackFetchData`.
 */
export type FormDataFetcher = (
  resource: string,
  filter?: Record<string, string>,
) => Promise<unknown[]>;

export async function fallbackFetchData(
  resource: string,
  filter?: Record<string, string>,
): Promise<unknown[]> {
  if (typeof window === "undefined") return [];
  try {
    const qs = new URLSearchParams();
    if (filter) {
      for (const [k, v] of Object.entries(filter)) {
        if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
      }
    }
    const q = qs.toString();
    const url = `/api/data/${encodeURIComponent(resource)}${q ? `?${q}` : ""}`;
    const res = await fetch(url);
    if (!res.ok) return [];
    let payload: unknown = await res.json();
    // Unwrap the list API's pagination envelope down to its array (mirrors
    // loader.ts), so consumers receive rows rather than the envelope.
    if (
      payload &&
      typeof payload === "object" &&
      !Array.isArray(payload) &&
      Array.isArray((payload as { data?: unknown }).data)
    ) {
      payload = (payload as { data: unknown[] }).data;
    }
    if (Array.isArray(payload)) return payload;
    // A single-record response (e.g. get-by-id) — normalise to a one-item list.
    return payload ? [payload] : [];
  } catch {
    return [];
  }
}
