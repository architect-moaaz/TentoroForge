import { z } from "zod";
const Option = z.object({ value: z.string(), label: z.string() });
export const SegmentedControlProps = z.object({
  name:      z.string().default("segment"),
  label:     z.string().optional(),
  options:   z.array(Option).default([]),
  bind:      z.string().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type SegmentedControlPropsType = z.infer<typeof SegmentedControlProps>;
