import { z } from "zod";

const Item = z.object({ title: z.string(), subtitle: z.string().optional(), icon: z.string().optional() });
// AN ITEM, OR A DATA ROW. A record page binds the List to a child collection
// (the notes of a case: body, createdAt); the registry validates against THIS
// schema and stripped every column a row actually has. A row is admitted and
// the component shapes it by its own columns (style/rowShape.ts).
const ItemOrRow = z.union([Item.strict(), z.record(z.unknown())]);

export const ListProps = z.object({
  items:     z.array(ItemOrRow).default([]),
  divided:   z.boolean().optional(),
  /** Max rows to render — see ActivityFeedNode.limit. */
  limit:     z.number().int().positive().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});

export type ListPropsType = z.infer<typeof ListProps>;
