import { z } from "zod";
export const QRCodeProps = z.object({
  value:     z.string().default(""),
  size:      z.number().int().positive().optional(),
  label:     z.string().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type QRCodePropsType = z.infer<typeof QRCodeProps>;
