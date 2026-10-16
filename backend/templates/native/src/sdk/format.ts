// The app SDK (native) — turning values into words and figures, without React.
// Money, numbers, the text of a widget's cells, a language's pick, a stored
// file's address. The hooks and components (money.ts, i18n.ts, ui/) bind these
// to the app's currency and language from `config.generated.ts`; keeping the
// logic here, with the app's choices passed in, is what lets it be tested.
//
// PURE — no react-native import.

export type Format = "number" | "currency" | "percent" | "duration";

/** A text in one language, or in each: `{ en: "Orders", hi: "ऑर्डर" }`. */
export type Text = string | Record<string, string>;

/** A MONEY FIELD HOLDS MAJOR UNITS (12.50 is twelve and a half) in the app's
 *  currency. `Intl` does the symbol and the grouping; an engine without the
 *  currency (or a bad code) falls back to "GBP 12.50" rather than throwing. */
export function formatMoney(amount: number, opts: { currency: string; locale?: string; maximumFractionDigits?: number }): string {
  if (!Number.isFinite(amount)) return "";
  try {
    return new Intl.NumberFormat(opts.locale, {
      style: "currency", currency: opts.currency, maximumFractionDigits: opts.maximumFractionDigits ?? 2,
    }).format(amount);
  } catch {
    return `${opts.currency} ${amount.toFixed(2)}`;
  }
}

/** "$" for USD, "£" for GBP, "₹" for INR — what a money field shows before the
 *  figure. The code itself when the engine cannot say. */
export function currencySymbol(currency: string, locale?: string): string {
  try {
    const part = new Intl.NumberFormat(locale, { style: "currency", currency }).formatToParts(0).find((p) => p.type === "currency");
    return part?.value ?? currency;
  } catch {
    return currency;
  }
}

export function formatNumber(value: number, locale?: string, maximumFractionDigits = 2): string {
  if (!Number.isFinite(value)) return "";
  try {
    return new Intl.NumberFormat(locale, { maximumFractionDigits }).format(value);
  } catch {
    return String(Math.round(value * 100) / 100);
  }
}

/** 0.12 -> "12%". */
export function formatPercent(fraction: number, locale?: string): string {
  if (!Number.isFinite(fraction)) return "";
  try {
    return new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1 }).format(fraction);
  } catch {
    return `${Math.round(fraction * 1000) / 10}%`;
  }
}

/** 1200 -> "1.2K": for an axis, where the room is small. */
export function formatCompact(value: number, locale?: string): string {
  if (!Number.isFinite(value)) return "";
  try {
    return new Intl.NumberFormat(locale, { notation: "compact", maximumFractionDigits: 1 }).format(value);
  } catch {
    return formatNumber(value, locale, 1);
  }
}

/** One cell of a widget's table or tile. Empty is a dash, a non-number is itself. */
export function formatCell(v: unknown, format: Format, opts: { currency: string; locale?: string }): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v !== "number") return String(v);
  if (format === "currency") return formatMoney(v, opts);
  if (format === "percent") return formatPercent(v, opts.locale);
  return formatNumber(v, opts.locale);
}

/** `placedAtLabel` -> "Placed At"; `order_total` -> "Order total". */
export function humanize(key: string): string {
  return key.replace(/Label$/, "").replace(/([a-z])([A-Z])/g, "$1 $2").replace(/[_-]+/g, " ")
    .replace(/^./, (c) => c.toUpperCase());
}

/** A gauge without a declared maximum reads against the next round number. */
export function niceCeiling(v: number): number {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  return [1, 2, 5, 10].map((m) => m * p).find((c) => c >= v) ?? 10 * p;
}

function base(tag: string): string {
  return String(tag || "").replace("_", "-").split("-")[0].toLowerCase();
}

/** The language a string is shown in: the chosen one, else the primary, else any. */
export function pick(text: Text, lang: string, primary: string): string {
  if (typeof text === "string") return text;
  return text[lang] ?? text[base(lang)] ?? text[primary] ?? text[base(primary)] ?? Object.values(text)[0] ?? "";
}

/** The configured language a tag stands for (`fr-CA` -> `fr` when only `fr` is
 *  offered), or null. */
export function knownLanguage(tag: string | null | undefined, offered: readonly { tag: string }[]): string | null {
  if (!tag) return null;
  const hit = offered.find((l) => l.tag === tag) ?? offered.find((l) => base(l.tag) === base(tag));
  return hit ? hit.tag : null;
}

const STORED = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The path a file field's value is loaded from. An `image` / `file` field
 *  holds the stored file's id, which is not a URL; the app's preview route
 *  serves it. A value that is already a URL is returned as it is; an empty one
 *  as null. (The web's `fileUrl`; `fileSource` in files.ts adds the origin.) */
export function filePath(value: string | null | undefined): string | null {
  const s = String(value ?? "").trim();
  if (!s) return null;
  return STORED.test(s) ? `/api/files/preview?src=${encodeURIComponent(s)}` : s;
}

/** Whole-minutes "HH:MM" and ISO-ish dates as a person reads them. Invalid in, same out. */
export function formatDate(value: string | null | undefined, locale?: string, withTime = false): string {
  if (!value) return "";
  // A bare date is a calendar day, not an instant: read as UTC it is the day
  // before for anyone west of Greenwich.
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  const d = day ? new Date(Number(day[1]), Number(day[2]) - 1, Number(day[3])) : new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  try {
    return withTime
      ? d.toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" })
      : d.toLocaleDateString(locale, { dateStyle: "medium" });
  } catch {
    return String(value);
  }
}
