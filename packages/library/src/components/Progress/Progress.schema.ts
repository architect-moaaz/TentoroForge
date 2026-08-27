import { z } from "zod";
export const ProgressProps = z.object({
  label:     z.string().optional(),
  value:     z.number().optional(),
  max:       z.number().optional(),
  variant:   z.enum(["bar", "circular"]).optional(),
  showValue: z.boolean().optional(),
  bind:      z.string().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type ProgressPropsType = z.infer<typeof ProgressProps>;
