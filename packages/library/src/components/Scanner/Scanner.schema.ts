import { z } from "zod";
export const ScannerProps = z.object({
  label:         z.string().optional(),
  scanLabel:     z.string().optional(),
  deviceType:    z.enum(["rfid", "barcode", "qr"]).optional(),
  value:         z.string().optional(),
  status:        z.enum(["idle", "scanning", "success", "error"]).optional(),
  statusMessage: z.string().optional(),
  bind:          z.string().optional(),
  className:     z.string().optional(),
  style:         z.record(z.unknown()).optional(),
});
export type ScannerPropsType = z.infer<typeof ScannerProps>;
