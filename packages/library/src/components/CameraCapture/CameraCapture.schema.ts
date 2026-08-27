import { z } from "zod";
export const CameraCaptureProps = z.object({
  name:         z.string().default("photo"),
  label:        z.string().optional(),
  captureLabel: z.string().optional(),
  bind:         z.string().optional(),
  className:    z.string().optional(),
  style:        z.record(z.unknown()).optional(),
});
export type CameraCapturePropsType = z.infer<typeof CameraCaptureProps>;
