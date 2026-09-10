import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { Calendar } from "../../src/components/Calendar/Calendar";
import { CalendarProps } from "../../src/components/Calendar/Calendar.schema";

describe("Calendar", () => {
  it("renders the month/year header for the controlled value", () => {
    render(<Calendar value="2026-06-15" />);
    expect(screen.getByText(/June 2026/i)).toBeInTheDocument();
  });
  it("renders day cells and fires onChange with an ISO date when a day is clicked", () => {
    const onChange = vi.fn();
    render(<Calendar value="2026-06-15" onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "20" }));
    expect(onChange).toHaveBeenCalledWith("2026-06-20");
  });
  it("navigates to the previous month when the prev control is clicked", () => {
    render(<Calendar value="2026-06-15" />);
    fireEvent.click(screen.getByRole("button", { name: /previous month/i }));
    expect(screen.getByText(/May 2026/i)).toBeInTheDocument();
  });
  it("validates props", () => {
    expect(() => CalendarProps.parse({ value: "2026-01-01" })).not.toThrow();
    expect(() => CalendarProps.parse({})).not.toThrow();
  });
});

const bookings = [
  { id: "b1", title: "Smith checkout", checkIn: "2026-06-15", room: "Deluxe" },
  { id: "b2", title: "Jones stay", checkIn: "2026-06-15", checkOut: "2026-06-17" },
];

describe("Calendar — event mode", () => {
  it("plots events as chips on their day", () => {
    render(<Calendar events={bookings} dateField="checkIn" value="2026-06-15" />);
    expect(screen.getByText(/June 2026/i)).toBeInTheDocument();
    expect(screen.getByText("Smith checkout")).toBeInTheDocument();
  });

  it("spans a multi-day event across the inclusive date range", () => {
    render(<Calendar events={bookings} dateField="checkIn" endDateField="checkOut" value="2026-06-15" />);
    // 'Jones stay' covers 15→17, so it must appear on the 16th cell.
    const day16 = screen.getByTestId("cal-day-16");
    expect(within(day16).getByText("Jones stay")).toBeInTheDocument();
  });

  it("shows an agenda for the clicked day", () => {
    render(<Calendar events={bookings} dateField="checkIn" value="2026-06-15" />);
    fireEvent.click(screen.getByTestId("cal-day-15"));
    expect(screen.getByText(/June 15, 2026/i)).toBeInTheDocument();
    // chip + agenda entry
    expect(screen.getAllByText("Smith checkout").length).toBe(2);
  });

  it("opens an event popover with details + deep link on event click", () => {
    const { container } = render(
      <Calendar events={bookings} dateField="checkIn" value="2026-06-15" eventHref="/bookings/{id}" />,
    );
    // Click the event chip → Outlook-style popover appears.
    fireEvent.click(within(screen.getByTestId("cal-day-15")).getAllByText("Smith checkout")[0]);
    const pop = container.querySelector('[data-event-popover]');
    expect(pop).toBeTruthy();
    // Popover carries the record's extra field + the deep link.
    expect(within(pop as HTMLElement).getByText("Deluxe")).toBeInTheDocument();
    expect(pop!.querySelector('a[data-nav-trigger="/bookings/b1"]')).toBeTruthy();
  });

  it("switches to week and agenda views", () => {
    render(<Calendar events={bookings} dateField="checkIn" value="2026-06-15" />);
    fireEvent.click(screen.getByRole("button", { name: "agenda" }));
    // agenda view lists the event (grid is gone)
    expect(screen.getByText("Smith checkout")).toBeInTheDocument();
    expect(screen.queryByTestId("cal-day-15")).not.toBeInTheDocument();
  });

  it("validates event-mode props including view + detailFields", () => {
    expect(() =>
      CalendarProps.parse({ events: bookings, dateField: "checkIn", titleField: "title", view: "week", detailFields: ["room"] }),
    ).not.toThrow();
  });
});

/**
 * User report #5: "What does this today do it is not doing anything."
 *
 * It genuinely did nothing in picker mode — which is what a Calendar dropped
 * from the palette is. `goToday()` set `displayed` (already the current month,
 * so a no-op) and `selected` (which the picker grid did not read: it painted its
 * highlight from the `value` PROP). The same bug also meant plain day clicks
 * never highlighted in any app that does not write `value` back.
 */
describe("Calendar — picker mode selection (report #5)", () => {
  const todayIso = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  };

  it("Today selects the current date and returns to the current month", () => {
    // Open on a month that is not the current one so both halves are observable.
    render(<Calendar value="2020-02-10" />);
    expect(screen.getByText(/February 2020/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^today$/i }));
    const now = new Date();
    const monthName = now.toLocaleDateString("en-US", { month: "long" });
    expect(screen.getByText(new RegExp(`${monthName} ${now.getFullYear()}`, "i"))).toBeInTheDocument();
    const cell = screen.getByTestId(`cal-day-${now.getDate()}`);
    expect(cell).toHaveAttribute("aria-pressed", "true");
  });

  it("highlights a clicked day with no controlled parent writing `value` back", () => {
    render(<Calendar value="2026-06-15" />);
    expect(screen.getByTestId("cal-day-15")).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByTestId("cal-day-20"));
    expect(screen.getByTestId("cal-day-20")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("cal-day-15")).toHaveAttribute("aria-pressed", "false");
  });

  it("still follows a controlled parent that rewrites `value`", () => {
    const { rerender } = render(<Calendar value="2026-06-15" />);
    rerender(<Calendar value="2026-07-04" />);
    expect(screen.getByText(/July 2026/i)).toBeInTheDocument();
    expect(screen.getByTestId("cal-day-4")).toHaveAttribute("aria-pressed", "true");
  });

  it("Today works from the current month too (the case that looked inert)", () => {
    render(<Calendar />);
    const now = new Date();
    // Nothing is selected on a freshly-dropped Calendar…
    expect(screen.getByTestId(`cal-day-${now.getDate()}`)).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByRole("button", { name: /^today$/i }));
    // …and pressing Today must visibly change that, not silently re-set the month.
    expect(screen.getByTestId(`cal-day-${now.getDate()}`)).toHaveAttribute("aria-pressed", "true");
    expect(todayIso()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});

/**
 * User report #2: "This calendar definitely needs a fix in the looks, it looks
 * terrible." Structural assertions only — the things that were visibly broken
 * rather than merely a matter of taste.
 */
describe("Calendar — surface chrome matches the rest of the library (report #2)", () => {
  it("clips its own children to the rounded border and carries a token surface", () => {
    const { container } = render(<Calendar events={[]} dateField="d" value="2026-06-15" />);
    const root = container.querySelector("[data-calendar]") as HTMLElement;
    // Without overflow-hidden the day cells' backgrounds and hairlines painted
    // straight over the rounded corners — Card carries the same class.
    expect(root.className).toContain("overflow-hidden");
    // Radius + elevation come from the tokens, not a hard-coded rounded-lg.
    expect(root.className).toMatch(/rounded-(none|lg|2xl)/);
    expect(root.className).toMatch(/shadow-(none|sm|lg)/);
  });

  it("pads the month grid out to whole weeks so the bottom edge is not ragged", () => {
    // June 2026 starts on a Monday (1 leading blank) and has 30 days → 31 cells,
    // so 4 trailing blanks are needed to reach 35.
    const { container } = render(<Calendar events={[]} dateField="d" value="2026-06-15" />);
    const cells = container.querySelectorAll("[data-testid^='cal-day-']");
    expect(cells.length).toBe(30);
    // The grid holding the day cells must be a whole number of weeks — the old
    // one simply stopped after the last day, leaving a torn bottom row.
    const dayGrid = (cells[0] as HTMLElement).parentElement as HTMLElement;
    expect(dayGrid.children.length).toBe(35);
  });
});
