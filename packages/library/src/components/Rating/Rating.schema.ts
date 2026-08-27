import { z } from "zod";
export const RatingProps = z.object({
  name:      z.string().default("rating"),
  label:     z.string().optional(),
  max:       z.number().int().positive().default(5),
  disabled:  z.boolean().optional(),
  bind:      z.string().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type RatingPropsType = z.infer<typeof RatingProps>;
