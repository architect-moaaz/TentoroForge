import { z } from "zod";
export const SpinnerProps = z.object({
  label:     z.string().default("Loading"),
  size:      z.enum(["sm", "md", "lg"]).default("md"),
  /** Shape of the busy indicator. "ring" is the previous, unchanged rendering. */
  variant:   z.enum(["ring", "dots", "bars"]).default("ring"),
  /** CSS colour (or "currentColor") for the moving part only. Unset keeps the
   *  theme's primary. Exists because `resolveStyle(style)` reaches the outer
   *  span, not the arc — so a spinner on a primary surface was invisible and
   *  the Style panel could not reach it. */
  color:     z.string().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type SpinnerPropsType = z.infer<typeof SpinnerProps>;
