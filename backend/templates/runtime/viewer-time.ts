/**
 * DATES ARE DRAWN IN THE VIEWER'S TIME ZONE ON THE SERVER TOO.
 *
 * A page is drawn twice: once on the server, once in the browser, and the two
 * must say the same thing. A date written without a time zone — a
 * `toLocaleDateString()`, an `Intl.DateTimeFormat` with no `timeZone` — came
 * out in the server's zone (UTC) on the server and in the person's own zone in
 * the browser. Whenever the hour or the day differed, React threw the server's
 * page away and drew it again (minified error #418): a console error and a
 * flicker on every such page. DITANS had 680 such lines in 294 files
 * (2026-11-18).
 *
 * So the server, while it draws a page, takes the viewer's zone and language
 * as the defaults: the zone the browser reported (`forge-tz` cookie, written by
 * `components/ViewerTime.tsx`), else the one the host infers from the address
 * (`x-vercel-ip-timezone`), and the first language the browser asks for. A
 * call that names its own zone or language is left alone. Outside a page
 * request — an API route, a scheduled job, the build — nothing changes.
 *
 * Installed once per server by `instrumentation.ts`, which hands in how to
 * read the current request. Platform runtime — do not remove.
 */

export const VIEWER_TIME_COOKIE = "forge-tz";

export interface Viewer {
  timeZone?: string;
  locale?: string;
}

/** The request being drawn, as much of it as the defaults need. */
export interface ViewerRequest {
  pathname?: string;
  cookie?: string | null;
  ipTimeZone?: string | null;
  acceptLanguage?: string | null;
}

const Native = {
  DateTimeFormat: Intl.DateTimeFormat,
  NumberFormat: Intl.NumberFormat,
  dateToLocaleString: Date.prototype.toLocaleString,
  dateToLocaleDateString: Date.prototype.toLocaleDateString,
  dateToLocaleTimeString: Date.prototype.toLocaleTimeString,
  numberToLocaleString: Number.prototype.toLocaleString,
};

const zones = new Map<string, boolean>();
function realZone(zone: string | null | undefined): string | undefined {
  if (!zone) return undefined;
  let ok = zones.get(zone);
  if (ok === undefined) {
    try { new Native.DateTimeFormat("en", { timeZone: zone }); ok = true; } catch { ok = false; }
    if (zones.size < 1000) zones.set(zone, ok);
  }
  return ok ? zone : undefined;
}

const locales = new Map<string, boolean>();
function realLocale(tag: string | null | undefined): string | undefined {
  const t = String(tag ?? "").trim();
  if (!t || t === "*") return undefined;
  let ok = locales.get(t);
  if (ok === undefined) {
    try { ok = Native.DateTimeFormat.supportedLocalesOf([t]).length > 0; } catch { ok = false; }
    if (locales.size < 1000) locales.set(t, ok);
  }
  return ok ? t : undefined;
}

/** Where the viewer is: what their browser said (`zone|language`), else what the request implies. */
export function viewerOf(req: ViewerRequest): Viewer | null {
  // An API route or a job answers for whoever asked, not for a page being drawn.
  if (req.pathname && /(^|\/)api(\/|$)/.test(req.pathname)) return null;
  let fromCookie: string[] = [];
  try { fromCookie = req.cookie ? decodeURIComponent(req.cookie).split("|") : []; } catch { fromCookie = []; }
  const firstLanguage = String(req.acceptLanguage ?? "").split(",")[0]?.split(";")[0];
  const timeZone = realZone(fromCookie[0]) ?? realZone(req.ipTimeZone);
  const locale = realLocale(fromCookie[1]) ?? realLocale(firstLanguage);
  return timeZone || locale ? { timeZone, locale } : null;
}

type Reader = () => Viewer | null;

function fill(viewer: Viewer | null, given: unknown, options: unknown, zone: boolean): [unknown, unknown] {
  if (!viewer) return [given, options];
  const locale = given === undefined && viewer.locale ? viewer.locale : given;
  const opts = (options ?? undefined) as Intl.DateTimeFormatOptions | undefined;
  if (!zone || !viewer.timeZone || (opts && opts.timeZone !== undefined)) return [locale, options];
  return [locale, { ...(opts ?? {}), timeZone: viewer.timeZone }];
}

/**
 * Make the viewer's zone and language the defaults wherever `read()` names a
 * viewer. Idempotent: a second call replaces the reader, never wraps twice.
 */
export function installViewerTime(read: Reader): void {
  const g = globalThis as unknown as { __forgeViewerTime?: { read: Reader } };
  if (g.__forgeViewerTime) { g.__forgeViewerTime.read = read; return; }
  const state = { read };
  g.__forgeViewerTime = state;
  const viewer = (): Viewer | null => { try { return state.read(); } catch { return null; } };

  const DateTimeFormat = function (this: unknown, given?: unknown, options?: unknown) {
    const [l, o] = fill(viewer(), given, options, true);
    return new Native.DateTimeFormat(l as never, o as never);
  } as unknown as typeof Intl.DateTimeFormat;
  Object.defineProperty(DateTimeFormat, "prototype", { value: Native.DateTimeFormat.prototype });
  Object.defineProperty(DateTimeFormat, "supportedLocalesOf", { value: Native.DateTimeFormat.supportedLocalesOf.bind(Native.DateTimeFormat) });
  Object.defineProperty(Intl, "DateTimeFormat", { value: DateTimeFormat, writable: true, configurable: true });

  const NumberFormat = function (this: unknown, given?: unknown, options?: unknown) {
    const [l, o] = fill(viewer(), given, options, false);
    return new Native.NumberFormat(l as never, o as never);
  } as unknown as typeof Intl.NumberFormat;
  Object.defineProperty(NumberFormat, "prototype", { value: Native.NumberFormat.prototype });
  Object.defineProperty(NumberFormat, "supportedLocalesOf", { value: Native.NumberFormat.supportedLocalesOf.bind(Native.NumberFormat) });
  Object.defineProperty(Intl, "NumberFormat", { value: NumberFormat, writable: true, configurable: true });

  const onDate = (native: (this: Date, l?: unknown, o?: unknown) => string) =>
    function (this: Date, given?: unknown, options?: unknown): string {
      const [l, o] = fill(viewer(), given, options, true);
      return native.call(this, l, o);
    };
  Object.defineProperty(Date.prototype, "toLocaleString", { value: onDate(Native.dateToLocaleString as never), writable: true, configurable: true });
  Object.defineProperty(Date.prototype, "toLocaleDateString", { value: onDate(Native.dateToLocaleDateString as never), writable: true, configurable: true });
  Object.defineProperty(Date.prototype, "toLocaleTimeString", { value: onDate(Native.dateToLocaleTimeString as never), writable: true, configurable: true });
  Object.defineProperty(Number.prototype, "toLocaleString", {
    value: function (this: number, given?: unknown, options?: unknown): string {
      const [l, o] = fill(viewer(), given, options, false);
      return (Native.numberToLocaleString as (this: number, l?: unknown, o?: unknown) => string).call(this, l, o);
    },
    writable: true, configurable: true,
  });
}
