import { z } from "zod";
export const NumberInputProps = z.object({
  name:      z.string().default("number"),
  label:     z.string().optional(),
  min:       z.number().optional(),
  max:       z.number().optional(),
  step:      z.number().default(1),
  showSteppers: z.boolean().optional().default(true),
  prefix:    z.string().optional(),
  suffix:    z.string().optional(),
  disabled:  z.boolean().optional(),
  bind:      z.string().optional(),
  className: z.string().optional(),
  // Spec B3: currency/percent look-and-feel — right-align the digits and
  // use tabular-nums so amounts line up in a column.
  align:        z.enum(["left", "right"]).optional(),
  tabularNums:  z.boolean().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type NumberInputPropsType = z.infer<typeof NumberInputProps>;
