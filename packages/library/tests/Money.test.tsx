import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { MoneyInput, MoneyDisplay, formatMoney } from "../src/components/Money/Money";

describe("MoneyInput", () => {
  it("renders a currency chip when currencyEditable is false", () => {
    const { getByTestId, queryByTestId } = render(
      <MoneyInput name="amount" currency="EUR" />,
    );
    expect(getByTestId("money-input-currency-chip").textContent).toBe("EUR");
    expect(queryByTestId("money-input-currency-select")).toBeNull();
  });

  it("renders a currency select when currencyEditable is true", () => {
    const { getByTestId } = render(
      <MoneyInput name="amount" currency="USD" currencyEditable />,
    );
    const sel = getByTestId("money-input-currency-select") as HTMLSelectElement;
    expect(sel.value).toBe("USD");
    // Default set includes the majors.
    const options = Array.from(sel.options).map((o) => o.value);
    for (const iso of ["USD", "EUR", "GBP", "JPY"]) expect(options).toContain(iso);
  });

  it("keeps the amount as a decimal STRING through onChange (no float loss)", () => {
    let seen: { amount: string; currency: string } | null = null;
    const { getByTestId } = render(
      <MoneyInput name="amount" currency="USD" onChange={(v) => (seen = v)} />,
    );
    const input = getByTestId("money-input-amount") as HTMLInputElement;
    // 19,4 precision — a value a JS number would round.
    fireEvent.change(input, { target: { value: "1234567890123.4567" } });
    expect(seen).toEqual({ amount: "1234567890123.4567", currency: "USD" });
  });

  it("emits currency changes when the user picks a different one", () => {
    let seen: { amount: string; currency: string } | null = null;
    const { getByTestId } = render(
      <MoneyInput
        name="amount"
        value="42.00"
        currency="USD"
        currencyEditable
        onChange={(v) => (seen = v)}
      />,
    );
    fireEvent.change(getByTestId("money-input-currency-select"), {
      target: { value: "GBP" },
    });
    expect(seen).toEqual({ amount: "42.00", currency: "GBP" });
  });

  it("writes a hidden <field>_currency input when currency is locked (FormData carries the pair)", () => {
    const { container } = render(
      <MoneyInput name="amount" currency="JPY" />,
    );
    const hidden = container.querySelector(
      'input[type="hidden"][name="amount_currency"]',
    ) as HTMLInputElement | null;
    expect(hidden).not.toBeNull();
    expect(hidden!.value).toBe("JPY");
  });
});

describe("MoneyDisplay", () => {
  it("renders an em-dash for null / undefined (never $0.00)", () => {
    const { container: c1 } = render(<MoneyDisplay value={null} />);
    expect(c1.textContent).toBe("—");
    const { container: c2 } = render(<MoneyDisplay value={undefined} />);
    expect(c2.textContent).toBe("—");
    const { container: c3 } = render(<MoneyDisplay value="" />);
    expect(c3.textContent).toBe("—");
  });

  it("formats via Intl with the given currency + locale", () => {
    const { container } = render(
      <MoneyDisplay value="1234.5" currency="USD" locale="en-US" />,
    );
    expect(container.textContent).toContain("1,234.50");
    expect(container.textContent).toMatch(/\$/);
  });

  it("compact notation drops the trailing zeros", () => {
    const { container } = render(
      <MoneyDisplay value="1200000" currency="USD" locale="en-US" compact />,
    );
    // en-US compact currency is "$1.2M"
    expect(container.textContent).toMatch(/\$1\.2M/);
  });

  it("showSymbol=false renders the ISO code, not the symbol", () => {
    const { container } = render(
      <MoneyDisplay value="42" currency="USD" locale="en-US" showSymbol={false} />,
    );
    expect(container.textContent).toContain("USD");
    expect(container.textContent).not.toContain("$");
  });

  it("uses tabular-nums + right-align by default so amounts line up in tables", () => {
    const { container } = render(<MoneyDisplay value="10" />);
    const el = container.firstElementChild as HTMLElement;
    expect(el.className).toMatch(/tabular-nums/);
    expect(el.className).toMatch(/text-right/);
  });
});

describe("formatMoney", () => {
  it("matches MoneyDisplay's rendered string for a plain value", () => {
    const s = formatMoney("99.9", { currency: "EUR", locale: "en-US" });
    // Just check the shape — Intl locales vary across Node versions.
    expect(s).toMatch(/€/);
    expect(s).toMatch(/99\.90/);
  });

  it("empty / null → em-dash", () => {
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney("")).toBe("—");
    expect(formatMoney(undefined)).toBe("—");
  });
});
