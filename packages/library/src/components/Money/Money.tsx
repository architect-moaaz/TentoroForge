"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import type { MoneyInputPropsType, MoneyDisplayPropsType } from "./Money.schema";
import { DEFAULT_CURRENCIES } from "./Money.schema";

// ────────────────────────────────────────────────────────────────────────────
// Decimal helpers — money must never ride a JS `number`. Cent precision goes
// out the window on numbers > 2^53 or on subtractions like 0.1 + 0.2. We keep
// the amount as a STRING everywhere and only coerce to a Number at the last
// moment (Intl formatting, min/max clamping), where the loss is bounded.
// ────────────────────────────────────────────────────────────────────────────

function toDecimalString(v: unknown): string {
  if (v === null || v === undefined || v === "") return "";
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  const s = String(v).trim();
  // Strip everything that isn't a digit, a leading minus, or a decimal point.
  const cleaned = s.replace(/[^\d.\-]/g, "");
  return cleaned;
}

function formatWithLocale(decimal: string, locale: string): string {
  // Best-effort locale grouping for the raw editable amount. We do NOT use
  // currency style here — MoneyInput shows the currency as a chip, not a prefix.
  if (!decimal || decimal === "-" || decimal.endsWith(".")) return decimal;
  const n = Number(decimal);
  if (!Number.isFinite(n)) return decimal;
  const fractionDigits = decimal.includes(".")
    ? Math.min(decimal.split(".")[1].length, 4)
    : 0;
  try {
    return new Intl.NumberFormat(locale, {
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: 4,
      useGrouping: true,
    }).format(n);
  } catch {
    return decimal;
  }
}

export interface MoneyInputProps extends MoneyInputPropsType {
  style?: StyleSlotT;
  onChange?: (v: { amount: string; currency: string }) => void;
}

export function MoneyInput({
  name,
  label,
  value,
  currency = "USD",
  currencyEditable = false,
  currencies,
  min,
  max,
  step = 0.01,
  placeholder,
  required,
  disabled,
  readOnly,
  className,
  style,
  onChange,
}: MoneyInputProps & { onChange?: MoneyInputProps["onChange"] }) {
  // Controlled by an external onChange handler; otherwise self-managed so a
  // plain (FormData) form still works.
  const controlled = onChange !== undefined;
  const [internalAmount, setInternalAmount] = React.useState<string>(
    toDecimalString(value),
  );
  const [internalCurrency, setInternalCurrency] = React.useState<string>(currency);

  const amount = controlled ? toDecimalString(value) : internalAmount;
  const ccy = controlled ? currency : internalCurrency;
  const options = currencies && currencies.length > 0 ? currencies : DEFAULT_CURRENCIES;

  const emit = (nextAmount: string, nextCurrency: string) => {
    onChange?.({ amount: nextAmount, currency: nextCurrency });
  };

  const setAmount = (raw: string) => {
    const cleaned = toDecimalString(raw);
    // Clamp against min/max at edit time.
    let next = cleaned;
    if (cleaned && cleaned !== "-" && !cleaned.endsWith(".")) {
      const n = Number(cleaned);
      if (Number.isFinite(n)) {
        if (typeof min === "number" && n < min) next = String(min);
        if (typeof max === "number" && n > max) next = String(max);
      }
    }
    if (!controlled) setInternalAmount(next);
    emit(next, ccy);
  };

  const setCurrency = (next: string) => {
    if (!controlled) setInternalCurrency(next);
    emit(amount, next);
  };

  const rootClass = ["flex flex-col gap-1", className].filter(Boolean).join(" ");

  return (
    <div
      className={rootClass}
      data-money-input=""
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
    >
      {label && (
        <label className="text-sm font-medium text-foreground">
          {label}
          {required ? <span className="ml-0.5 text-danger">*</span> : null}
        </label>
      )}
      <div className="inline-flex items-stretch rounded-md border border-input focus-within:ring-1 focus-within:ring-ring">
        <input
          type="text"
          inputMode="decimal"
          name={name}
          value={amount}
          placeholder={placeholder ?? "0.00"}
          disabled={disabled}
          readOnly={readOnly}
          required={required}
          min={min}
          max={max}
          step={step}
          onChange={(e) => setAmount(e.target.value)}
          className="flex-1 bg-transparent px-3 py-1.5 text-right text-sm tabular-nums focus-visible:outline-none disabled:opacity-50"
          data-testid="money-input-amount"
        />
        {currencyEditable ? (
          <select
            name={`${name}_currency`}
            value={ccy}
            disabled={disabled || readOnly}
            onChange={(e) => setCurrency(e.target.value)}
            className="border-l border-input bg-muted px-2 py-1.5 text-xs font-medium text-muted-foreground focus-visible:outline-none disabled:opacity-50"
            data-testid="money-input-currency-select"
          >
            {options.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        ) : (
          <>
            <span
              className="flex items-center border-l border-input bg-muted px-2 py-1.5 text-xs font-medium text-muted-foreground"
              data-testid="money-input-currency-chip"
            >
              {ccy}
            </span>
            {/* Hidden field keeps the currency on FormData when not editable. */}
            <input type="hidden" name={`${name}_currency`} value={ccy} readOnly />
          </>
        )}
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// MoneyDisplay — read-only, tabular, Intl-formatted.
// ────────────────────────────────────────────────────────────────────────────

export interface MoneyDisplayProps extends MoneyDisplayPropsType {
  style?: StyleSlotT;
}

export function MoneyDisplay({
  value,
  currency = "USD",
  locale = "en-US",
  compact = false,
  showSymbol = true,
  align = "right",
  className,
  style,
}: MoneyDisplayProps) {
  const decimal = toDecimalString(value);
  const hasValue = decimal !== "" && decimal !== "-";
  const rootClass = [
    "tabular-nums",
    align === "right" ? "text-right" : "text-left",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  if (!hasValue) {
    return (
      <span
        className={rootClass}
        style={resolveStyle(style)}
        {...useMotion(style?.motion)}
        data-money-display=""
        data-empty=""
      >
        {"—"}
      </span>
    );
  }

  const n = Number(decimal);
  let text: string;
  if (!Number.isFinite(n)) {
    text = decimal;
  } else if (showSymbol) {
    try {
      text = new Intl.NumberFormat(locale, {
        style: "currency",
        currency,
        notation: compact ? "compact" : "standard",
      }).format(n);
    } catch {
      // Bad currency code (e.g. "" or "XXX") — fall back to code + amount.
      text = `${currency} ${n.toLocaleString(locale)}`;
    }
  } else {
    const amountText = new Intl.NumberFormat(locale, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
      notation: compact ? "compact" : "standard",
    }).format(n);
    text = `${amountText} ${currency}`;
  }

  return (
    <span
      className={rootClass}
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
      data-money-display=""
    >
      {text}
    </span>
  );
}

// Re-export the formatter for callers that want the string alone (row exports,
// snapshot tests, printable statements). Same rules as MoneyDisplay.
export function formatMoney(
  value: unknown,
  opts: { currency?: string; locale?: string; compact?: boolean; showSymbol?: boolean } = {},
): string {
  const { currency = "USD", locale = "en-US", compact = false, showSymbol = true } = opts;
  const decimal = toDecimalString(value);
  if (!decimal || decimal === "-") return "—";
  const n = Number(decimal);
  if (!Number.isFinite(n)) return decimal;
  if (showSymbol) {
    try {
      return new Intl.NumberFormat(locale, {
        style: "currency",
        currency,
        notation: compact ? "compact" : "standard",
      }).format(n);
    } catch {
      return `${currency} ${n.toLocaleString(locale)}`;
    }
  }
  return `${new Intl.NumberFormat(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    notation: compact ? "compact" : "standard",
  }).format(n)} ${currency}`;
}
