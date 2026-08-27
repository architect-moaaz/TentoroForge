import { z } from "zod";
export const HoverCardProps = z.object({
  label:     z.string().default("Hover"),
  title:     z.string().optional(),
  content:   z.string().default(""),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type HoverCardPropsType = z.infer<typeof HoverCardProps>;
