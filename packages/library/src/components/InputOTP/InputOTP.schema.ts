import { z } from "zod";
export const InputOTPProps = z.object({
  name:      z.string().default("otp"),
  label:     z.string().optional(),
  length:    z.number().int().positive().default(6),
  disabled:  z.boolean().optional(),
  bind:      z.string().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type InputOTPPropsType = z.infer<typeof InputOTPProps>;
