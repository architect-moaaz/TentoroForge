import { z } from "zod";
import { Validators } from "@tentoroforge/schema";
export const TimePickerProps = z.object({
  name:      z.string().default("time"),
  label:     z.string().optional(),
  min:       z.string().optional(),
  max:       z.string().optional(),
  step:      z.number().optional(),
  disabled:  z.boolean().optional(),
  /** Declarative prefill from the schema. `value` alone is an INITIAL value,
   *  never a demand to be controlled — see util/useFieldValue.ts. */
  defaultValue: z.string().optional(),
  bind:      z.string().optional(),
  /** Shared validation vocabulary — see Validators in
   *  packages/schema/src/nodes/inputs.ts. The NODE schema already allowed it
   *  (via baseField); this component schema did not, so the prop was dropped
   *  on the way in and the panel had nothing to render. */
  validators: Validators.optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type TimePickerPropsType = z.infer<typeof TimePickerProps>;
