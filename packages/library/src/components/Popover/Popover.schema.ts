import { z } from "zod";
export const PopoverProps = z.object({
  trigger:   z.string().default("Open"),
  title:     z.string().optional(),
  content:   z.string().default(""),
  align:     z.enum(["start", "center", "end"]).optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type PopoverPropsType = z.infer<typeof PopoverProps>;
