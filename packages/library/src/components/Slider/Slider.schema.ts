import { z } from "zod";
export const SliderProps = z.object({
  name:      z.string().default("slider"),
  label:     z.string().optional(),
  min:       z.number().default(0),
  max:       z.number().default(100),
  step:      z.number().default(1),
  range:     z.boolean().default(false),
  showValue: z.boolean().optional(),
  bind:      z.string().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type SliderPropsType = z.infer<typeof SliderProps>;
