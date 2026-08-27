import { z } from "zod";
const Item = z.object({ label: z.string(), valid: z.boolean() });
export const ValidationChecklistProps = z.object({
  items:       z.array(Item).default([]),
  orientation: z.enum(["horizontal", "vertical"]).optional(),
  className:   z.string().optional(),
  style:       z.record(z.unknown()).optional(),
});
export type ValidationChecklistPropsType = z.infer<typeof ValidationChecklistProps>;
