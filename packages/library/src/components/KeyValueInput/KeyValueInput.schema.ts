import { z } from "zod";
export const KeyValueInputProps = z.object({
  name:        z.string().default("data"),
  label:       z.string().optional(),
  description: z.string().optional(),
  valueType:   z.enum(["text", "number", "boolean"]).optional(),
  disabled:    z.boolean().optional(),
  bind:        z.string().optional(),
  className:   z.string().optional(),
  style:       z.record(z.unknown()).optional(),
});
export type KeyValueInputPropsType = z.infer<typeof KeyValueInputProps>;
