import { z } from "zod";

export const SwitchProps = z.object({
  name:      z.string().default("switch"),
  label:     z.string().optional(),
  disabled:  z.boolean().optional(),
  size:      z.enum(["sm", "md"]).optional(),
  bind:      z.string().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type SwitchPropsType = z.infer<typeof SwitchProps>;
