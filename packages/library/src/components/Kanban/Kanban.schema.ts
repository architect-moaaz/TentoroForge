import { z } from "zod";

const Card = z.object({
  id: z.string(),
  title: z.string(),
  description: z.string().optional(),
});
const Column = z.object({
  id: z.string(),
  title: z.string(),
  color: z.string().optional(),
  cards: z.array(Card).default([]),
});

/** One extra field to surface on a card, e.g. {field:"assignee",label:"Owner"}. */
const CardField = z.object({
  field: z.string(),
  label: z.string().optional(),
});

export const KanbanProps = z.object({
  // ── Data-driven mode (preferred) ──────────────────────────────────────────
  // `data` is a binding like "{{tasks}}" that the renderer interpolates to an
  // array of records before this component renders. Cards are grouped into
  // columns by `groupBy`.
  data: z.unknown().optional(),
  groupBy: z.string().optional(),
  // Explicit column order / allow-list (e.g. the status enum values). When
  // omitted, columns are derived from the distinct `groupBy` values in `data`.
  columnOrder: z.array(z.string()).optional(),
  // Field mappings used to render each card.
  cardTitle: z.string().optional(),
  cardDescription: z.string().optional(),
  cardBadge: z.string().optional(), // a field shown as a colored pill (e.g. priority)
  cardFields: z.array(CardField).optional(), // extra meta fields shown under the title
  // Per-record deep-link template, e.g. "/tasks/{id}". Renders the card as a
  // nav trigger the Engine swaps the page on.
  cardHref: z.string().optional(),

  // ── Legacy static mode (still supported) ─────────────────────────────────
  columns: z.array(Column).optional(),

  // ── Spec E Wave 1 — cross-lane drag/drop ─────────────────────────────
  /**
   * When set, cards can be dragged from one column to another. On drop
   * the runtime patches the card's `sourceField` (typically the same
   * field used for `groupBy`) via
   * `PATCH /api/data/:entity/:id/:field`.
   * Requires the entity to expose the field as writable.
   */
  moveBetweenLanes: z
    .object({
      sourceField: z.string().min(1),
    })
    .optional(),

  // ── Presentation ─────────────────────────────────────────────────────────
  emptyText: z.string().optional(),
  bind: z.string().optional(),
  className: z.string().optional(),
  style: z.record(z.unknown()).optional(),
});

export type KanbanPropsType = z.infer<typeof KanbanProps>;
