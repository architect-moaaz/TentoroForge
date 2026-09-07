import { z } from "zod";
export const ScannerProps = z.object({
  // Form field name — the key the scanned code submits under. Without it the
  // component advertised no named control at all and FormData never saw it.
  name:          z.string().optional(),
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
