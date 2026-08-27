import { z } from "zod";
export const SpinnerProps = z.object({
  label:     z.string().default("Loading"),
  size:      z.enum(["sm", "md", "lg"]).default("md"),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type SpinnerPropsType = z.infer<typeof SpinnerProps>;
