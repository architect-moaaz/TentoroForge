import { z } from "zod";

const Item = z.object({ title: z.string(), subtitle: z.string().optional(), icon: z.string().optional() });

export const ListProps = z.object({
  items:     z.array(Item).default([]),
  divided:   z.boolean().optional(),
  /** Max rows to render — see ActivityFeedNode.limit. */
  limit:     z.number().int().positive().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});

export type ListPropsType = z.infer<typeof ListProps>;
