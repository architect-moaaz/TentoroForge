import { z } from "zod";
const Option = z.object({ value: z.string(), label: z.string(), disabled: z.boolean().optional() });
export const RadioGroupProps = z.object({
  name:        z.string().default("radio"),
  label:       z.string().optional(),
  options:     z.array(Option).default([]),
  orientation: z.enum(["vertical", "horizontal"]).optional(),
  required:    z.boolean().optional(),
  disabled:    z.boolean().optional(),
  bind:        z.string().optional(),
  className:   z.string().optional(),
  style:       z.record(z.unknown()).optional(),
});
export type RadioGroupPropsType = z.infer<typeof RadioGroupProps>;
