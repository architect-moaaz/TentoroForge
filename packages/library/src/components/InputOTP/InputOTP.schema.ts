import { z } from "zod";
import { Validators } from "@tentoroforge/schema";
export const InputOTPProps = z.object({
  name:      z.string().default("otp"),
  label:     z.string().optional(),
  length:    z.number().int().positive().default(6),
  disabled:  z.boolean().optional(),
  bind:      z.string().optional(),
  /** Shared validation vocabulary — see Validators in
   *  packages/schema/src/nodes/inputs.ts. */
  validators: Validators.optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type InputOTPPropsType = z.infer<typeof InputOTPProps>;
