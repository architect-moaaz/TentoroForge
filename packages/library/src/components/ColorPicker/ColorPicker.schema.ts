import { z } from "zod";
import { Validators } from "@tentoroforge/schema";
export const ColorPickerProps = z.object({
  name:      z.string().default("color"),
  label:     z.string().optional(),
  disabled:  z.boolean().optional(),
  /** Declarative prefill from the schema. `value` alone is an INITIAL value,
   *  never a demand to be controlled — see util/useFieldValue.ts. */
  defaultValue: z.string().optional(),
  bind:      z.string().optional(),
  /** Shared validation vocabulary — see Validators in
   *  packages/schema/src/nodes/inputs.ts. */
  validators: Validators.optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type ColorPickerPropsType = z.infer<typeof ColorPickerProps>;
