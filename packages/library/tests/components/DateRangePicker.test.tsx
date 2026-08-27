import { describe, it, expect, beforeEach } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { DateRangePicker } from "../../src/components/DateRangePicker/DateRangePicker";

// useUrlState persists to window.location; reset between tests so preset clicks
// in one test don't leak URL state into the next.
beforeEach(() => {
  window.history.replaceState({}, "", "/");
});

// The exact node shape emitted by a live generated app: `presets` is an array of
// { label, value } OBJECTS (not the enum strings the schema declares), and no
// value/startDate/endDate is provided. This used to crash React with
// "Objects are not valid as a React child" when the dropdown opened.
const CRASHING_PRESETS = [
  { label: "Today", value: "today" },
  { label: "Last 7 days", value: "last-7-days" },
  { label: "Last 30 days", value: "last-30-days" },
  { label: "This month", value: "month-to-date" },
] as any;

describe("DateRangePicker", () => {
  it("renders + opens with object-shaped presets and no value (the live crash) without throwing", () => {
    const { getByText, container } = render(
      <DateRangePicker
        name="appointmentRange"
        label="Date Range"
        presets={CRASHING_PRESETS}
      />
    );
    // Open the dropdown — this is where the object-as-child crash occurred.
    expect(() => fireEvent.click(getByText("Any date"))).not.toThrow();
    // Preset labels render from the object's label (or value) — never the raw object.
    expect(container.textContent).toContain("Today");
    expect(container.textContent).toContain("Last 7 days");
    expect(container.textContent).toContain("This month");
  });

  it("applies a valid preset click to produce a concrete range", () => {
    const { getByText, container } = render(
      <DateRangePicker
        name="r"
        presets={CRASHING_PRESETS}
      />
    );
    fireEvent.click(getByText("Any date"));
    fireEvent.click(getByText("Today"));
    // After picking "today", the trigger shows a concrete ISO date (start === end).
    const yyyy = new Date().getFullYear().toString();
    expect(container.textContent).toContain(yyyy);
  });

  it("tolerates an unknown preset value (no-op, no crash)", () => {
    const { getByText } = render(
      <DateRangePicker name="r" presets={CRASHING_PRESETS} />
    );
    fireEvent.click(getByText("Any date"));
    // "This month" maps to unknown value "month-to-date" → no range, but must not throw.
    expect(() => fireEvent.click(getByText("This month"))).not.toThrow();
  });

  it("renders with no presets prop using string defaults, no crash", () => {
    const { getByText } = render(<DateRangePicker name="r" label="Range" />);
    expect(() => fireEvent.click(getByText("Any date"))).not.toThrow();
    // A default preset label is visible.
    expect(getByText("Last 7 days")).toBeTruthy();
  });

  it("tolerates a non-array presets value without crashing", () => {
    const { getByText } = render(
      <DateRangePicker name="r" presets={undefined as any} />
    );
    expect(() => fireEvent.click(getByText("Any date"))).not.toThrow();
  });
});
