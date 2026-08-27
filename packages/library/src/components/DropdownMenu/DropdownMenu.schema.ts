import { z } from "zod";
const Item = z.object({ label: z.string(), value: z.string(), icon: z.string().optional(), disabled: z.boolean().optional() });
export const DropdownMenuProps = z.object({
  trigger:     z.string().default("Menu"),
  triggerIcon: z.string().optional(),
  items:       z.array(Item).default([]),
  align:       z.enum(["start", "center", "end"]).optional(),
  className:   z.string().optional(),
  style:       z.record(z.unknown()).optional(),
});
export type DropdownMenuPropsType = z.infer<typeof DropdownMenuProps>;
