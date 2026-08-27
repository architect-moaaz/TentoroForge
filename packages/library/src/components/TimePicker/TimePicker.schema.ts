import { z } from "zod";
export const TimePickerProps = z.object({
  name:      z.string().default("time"),
  label:     z.string().optional(),
  min:       z.string().optional(),
  max:       z.string().optional(),
  step:      z.number().optional(),
  disabled:  z.boolean().optional(),
  bind:      z.string().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type TimePickerPropsType = z.infer<typeof TimePickerProps>;
