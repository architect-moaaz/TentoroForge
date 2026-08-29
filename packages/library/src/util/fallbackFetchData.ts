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
    // A REDIRECT IS NOT AN EMPTY RESULT. A gated /api/data answers 307 to
    // /login, fetch follows it, and the login page comes back 200 HTML — so
    // `res.ok` is true, `.json()` throws, and this returned [] as though the
    // table were genuinely empty. A public page whose data route is gated then
    // renders a perfect empty state and says nothing, which reads as "the app
    // has no data" rather than "you are not signed in".
    if (res.redirected) {
      // eslint-disable-next-line no-console
      console.error(
        `[forge] ${resource} could not be read — the request was redirected to ` +
          `${res.url}. This usually means the session has expired or the data ` +
          `route requires sign-in.`,
      );
      return [];
    }
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
