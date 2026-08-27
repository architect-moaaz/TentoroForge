import { z } from "zod";
export const ColorPickerProps = z.object({
  name:      z.string().default("color"),
  label:     z.string().optional(),
  disabled:  z.boolean().optional(),
  bind:      z.string().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type ColorPickerPropsType = z.infer<typeof ColorPickerProps>;
