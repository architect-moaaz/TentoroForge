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
