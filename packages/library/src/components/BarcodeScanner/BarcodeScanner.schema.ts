import { z } from "zod";
export const BarcodeScannerProps = z.object({
  name:      z.string().default("barcode"),
  label:     z.string().optional(),
  hint:      z.string().optional(),
  formats:   z.array(z.string()).optional(),
  bind:      z.string().optional(),
  autoSubmit: z.boolean().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type BarcodeScannerPropsType = z.infer<typeof BarcodeScannerProps>;
