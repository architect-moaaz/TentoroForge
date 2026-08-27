import { z } from "zod";
export const StatProps = z.object({
  label:     z.string().default("Metric"),
  value:     z.string().default("0"),
  delta:     z.string().optional(),
  trend:     z.enum(["up", "down", "neutral"]).optional(),
  caption:   z.string().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type StatPropsType = z.infer<typeof StatProps>;
