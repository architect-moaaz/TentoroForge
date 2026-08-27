import { z } from "zod";
const Option = z.object({ value: z.string(), label: z.string() });
export const ComboboxProps = z.object({
  name:        z.string().default("combobox"),
  label:       z.string().optional(),
  options:     z.array(Option).default([]),
  placeholder: z.string().optional(),
  filterable:  z.boolean().default(true),
  clearable:   z.boolean().optional(),
  bind:        z.string().optional(),
  className:   z.string().optional(),
  style:       z.record(z.unknown()).optional(),
});
export type ComboboxPropsType = z.infer<typeof ComboboxProps>;
