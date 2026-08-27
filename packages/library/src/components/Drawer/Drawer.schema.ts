import { z } from "zod";
export const DrawerProps = z.object({
  trigger:     z.string().default("Open"),
  title:       z.string().optional(),
  description: z.string().optional(),
  side:        z.enum(["left", "right", "top", "bottom"]).default("right"),
  content:     z.string().default(""),
  className:   z.string().optional(),
  style:       z.record(z.unknown()).optional(),
});
export type DrawerPropsType = z.infer<typeof DrawerProps>;
