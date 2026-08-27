import { z } from "zod";
const Item = z.object({ label: z.string(), value: z.string(), icon: z.string().optional(), disabled: z.boolean().optional() });
export const ContextMenuProps = z.object({
  label:     z.string().default("Right-click"),
  items:     z.array(Item).default([]),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type ContextMenuPropsType = z.infer<typeof ContextMenuProps>;
