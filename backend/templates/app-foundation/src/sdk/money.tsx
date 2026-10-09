/**
 * Money, in the application's one currency.
 *
 * Every page used to format its own amounts, each guessing the currency and
 * the locale: E-commerce showed GBP on the catalogue, US$ in the cart and $
 * at checkout (2026-10-09). The currency is decided once, in the definition
 * (`policies.money`, projected to `src/contracts/policies.json`), and this is
 * the one place that reads it. A record that carries its own currency — a
 * multi-currency ledger — passes it; nothing else names one.
 */
import * as React from "react";

type MoneyPolicy = { currency?: string; locale?: string };

function policy(): MoneyPolicy {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const p = require("@/contracts/policies.json");
    return (p && (p.default ?? p).money) || {};
  } catch {
    return {};
  }
}

/** The currency every amount is shown in (ISO 4217). */
export function currencyOf(): string {
  return policy().currency || "USD";
}

/** The locale amounts are formatted in. */
export function localeOf(): string {
  return policy().locale || "en";
}

/** `money(1240.5)` → "£1,240.50" in the application's currency and locale. */
export function money(
  value: number | string | null | undefined,
  opts: { currency?: string; locale?: string; maximumFractionDigits?: number } = {},
): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return String(value);
  return new Intl.NumberFormat(opts.locale || localeOf(), {
    style: "currency",
    currency: opts.currency || currencyOf(),
    maximumFractionDigits: opts.maximumFractionDigits ?? 2,
  }).format(n);
}

/** An amount, formatted; tabular figures so columns line up. */
export function Money({ value, currency, className }: {
  value: number | string | null | undefined;
  currency?: string;
  className?: string;
}) {
  return <span className={"tabular-nums " + (className ?? "")}>{money(value, { currency })}</span>;
}
