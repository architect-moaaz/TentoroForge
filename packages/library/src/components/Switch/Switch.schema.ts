import { z } from "zod";

export const SwitchProps = z.object({
  name:      z.string().default("switch"),
  label:     z.string().optional(),
  // Registry-declared ("On/off state.", control: toggle) and read by the
  // component — but absent here, so zod stripped it and the toggle was inert.
  checked:   z.boolean().optional(),
  disabled:  z.boolean().optional(),
  size:      z.enum(["sm", "md"]).optional(),
  bind:      z.string().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type SwitchPropsType = z.infer<typeof SwitchProps>;
