import { z } from "zod";

/**
 * ResourceTimeline — a resource-scheduler / Gantt grid: resources as rows
 * (rooms, staff, vehicles, rentals), days as columns, and items (reservations,
 * shifts, bookings) drawn as horizontal bars spanning their date range.
 *
 * Data-driven: `resources` and `items` are bindings like "{{rooms}}" /
 * "{{reservations}}" that the renderer interpolates to arrays of records.
 */
export const ResourceTimelineProps = z.object({
  // ── Resources (rows) ───────────────────────────────────────────────────────
  resources: z.unknown().optional(), // binding → array of resource records
  resourceIdField: z.string().optional(), // default "id"
  resourceLabelField: z.string().optional(), // default "name"/"label"/"title"
  resourceSubField: z.string().optional(), // secondary line, e.g. "1 King"
  resourceGroupField: z.string().optional(), // group header, e.g. room type / floor

  // ── Items (bars) ───────────────────────────────────────────────────────────
  items: z.unknown().optional(), // binding → array of item records
  itemResourceField: z.string().optional(), // FK to a resource id — default "resourceId"
  startField: z.string().optional(), // ISO start date — default "start"/"startDate"
  endField: z.string().optional(), // ISO end date — default "end"/"endDate"
  titleField: z.string().optional(), // bar label — default "title"/"name"
  subtitleField: z.string().optional(), // small secondary bar label
  statusField: z.string().optional(), // categorical field → bar colour + legend
  itemHref: z.string().optional(), // per-item deep link, e.g. "/reservations/{id}"

  // ── Range / layout ─────────────────────────────────────────────────────────
  rangeStart: z.string().optional(), // ISO date of the first column — default today
  days: z.number().int().positive().optional(), // column count — default 14
  emptyText: z.string().optional(),

  bind: z.string().optional(),
  className: z.string().optional(),
  style: z.record(z.unknown()).optional(),
});

export type ResourceTimelinePropsType = z.infer<typeof ResourceTimelineProps>;
