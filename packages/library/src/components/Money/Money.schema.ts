import { z } from "zod";

// A short, universal 3-letter default set. Real apps override via `currencies`.
export const DEFAULT_CURRENCIES = [
  "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "INR", "CNY",
] as const;

// ── MoneyInput — the amount field paired with a currency chip ────────────────
// Amount is a STRING (decimal) end-to-end so cent precision never rides through
// a JS `number`. `onChange` emits both parts so a controlled parent can persist
// the amount + the currency sibling column together (see the schema builder's
// `<field>_currency` sibling).
export const MoneyInputProps = z.object({
  name:              z.string().default("amount"),
  label:             z.string().optional(),
  value:             z.union([z.number(), z.string()]).nullable().optional(),
  currency:          z.string().default("USD"),
  currencyEditable:  z.boolean().default(false),
  currencies:        z.array(z.string()).optional(),
  min:               z.number().optional(),
  max:               z.number().optional(),
  step:              z.number().default(0.01),
  placeholder:       z.string().optional(),
  required:          z.boolean().optional(),
  disabled:          z.boolean().optional(),
  readOnly:          z.boolean().optional(),
  className:         z.string().optional(),
  style:             z.record(z.unknown()).optional(),
});
export type MoneyInputPropsType = z.infer<typeof MoneyInputProps>;

// ── MoneyDisplay — read-only formatted amount ─────────────────────────────────
// Renders via `Intl.NumberFormat` — locale + currency aware. `null`/`undefined`
// render as an em-dash so an empty cell doesn't lie with `$0.00`.
export const MoneyDisplayProps = z.object({
  value:       z.union([z.number(), z.string()]).nullable().optional(),
  currency:    z.string().default("USD"),
  locale:      z.string().default("en-US"),
  compact:     z.boolean().default(false),
  showSymbol:  z.boolean().default(true),
  align:       z.enum(["left", "right"]).default("right"),
  className:   z.string().optional(),
  style:       z.record(z.unknown()).optional(),
});
export type MoneyDisplayPropsType = z.infer<typeof MoneyDisplayProps>;
