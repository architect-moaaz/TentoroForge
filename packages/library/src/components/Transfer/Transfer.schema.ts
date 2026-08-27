import { z } from "zod";
const Option = z.object({ value: z.string(), label: z.string() });
export const TransferProps = z.object({
  options:   z.array(Option).default([]),
  selected:  z.array(z.string()).optional(),
  titles:    z.array(z.string()).optional(),
  bind:      z.string().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type TransferPropsType = z.infer<typeof TransferProps>;
