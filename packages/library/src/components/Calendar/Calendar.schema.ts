import { z } from "zod";

export const CalendarProps = z.object({
  // ── Event-calendar mode (preferred for data views) ────────────────────────
  // `events` is a binding like "{{bookings}}" the renderer interpolates to an
  // array of records. Each record is plotted on the day given by `dateField`.
  events: z.unknown().optional(),
  dateField: z.string().optional(), // field holding the (start) date — default "date"
  endDateField: z.string().optional(), // optional end date for multi-day spans
  titleField: z.string().optional(), // event label field — default "title"/"name"
  colorField: z.string().optional(), // categorical field → event colour
  eventHref: z.string().optional(), // per-event deep link template, e.g. "/bookings/{id}"
  emptyText: z.string().optional(),
  // Initial view. Users can switch between them in the header.
  view: z.enum(["month", "week", "agenda"]).optional(),
  // Which record fields to surface in the event-detail popup. When omitted, the
  // popup shows the record's own fields (minus id/date/title/system columns).
  detailFields: z.array(z.string()).optional(),

  // ── Date-picker mode (legacy) ─────────────────────────────────────────────
  name: z.string().default("date"),
  value: z.string().optional(), // ISO yyyy-mm-dd controlling the displayed month + selection

  bind: z.string().optional(),
  className: z.string().optional(),
  style: z.record(z.unknown()).optional(),
});

export type CalendarPropsType = z.infer<typeof CalendarProps>;
